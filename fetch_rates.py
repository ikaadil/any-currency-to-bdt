#!/usr/bin/env python3
"""Fetch BDT exchange rates by scraping provider websites, save to rates.json, build README.md."""
from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from pathlib import Path

import ssl

import aiohttp
import certifi
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
TARGET = "BDT"

CURRENCIES = [
    ("USD", "$", "🇺🇸", "US Dollar"),
    ("GBP", "£", "🇬🇧", "British Pound"),
    ("EUR", "€", "🇪🇺", "Euro"),
    ("CAD", "C$", "🇨🇦", "Canadian Dollar"),
    ("AUD", "A$", "🇦🇺", "Australian Dollar"),
    ("SGD", "S$", "🇸🇬", "Singapore Dollar"),
    ("AED", "د.إ", "🇦🇪", "UAE Dirham"),
    ("MYR", "RM", "🇲🇾", "Malaysian Ringgit"),
    ("SAR", "﷼", "🇸🇦", "Saudi Riyal"),
    ("KWD", "د.ك", "🇰🇼", "Kuwaiti Dinar"),
    ("QAR", "﷼", "🇶🇦", "Qatari Riyal"),
    ("JPY", "¥", "🇯🇵", "Japanese Yen"),
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
}

WISE_REGION = {
    "USD": "us", "GBP": "gb", "EUR": "de", "CAD": "ca", "AUD": "au",
    "SGD": "sg", "AED": "ae", "MYR": "my", "SAR": "sa", "KWD": "kw",
    "QAR": "qa", "JPY": "jp", "NZD": "nz", "BHD": "bh", "OMR": "om",
}

REMITLY_REGION = {
    "USD": ("us", "en"), "GBP": ("gb", "en"), "EUR": ("de", "en"),
    "CAD": ("ca", "en"), "AUD": ("au", "en"),
}


@dataclass
class Rate:
    provider: str
    url: str
    rate: float
    delivery: str


# ── Scrapers ──────────────────────────────────────────────────────────────────

async def scrape_wise(session: aiohttp.ClientSession, src: str) -> Rate | None:
    try:
        url = f"https://wise.com/rates/live?source={src}&target={TARGET}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status != 200:
                return None
            data = await r.json(content_type=None)
            val = data.get("value")
            if val is None:
                return None
            region = WISE_REGION.get(src, "us")
            return Rate("Wise",
                        f"https://wise.com/{region}/currency-converter/{src.lower()}-to-bdt-rate",
                        round(float(val), 3), "Bank")
    except Exception as e:
        print(f"  [Wise] {src}: {e}")
        return None


async def scrape_remitly(session: aiohttp.ClientSession, src: str) -> Rate | None:
    region = REMITLY_REGION.get(src)
    if not region:
        return None
    country, lang = region
    url = f"https://www.remitly.com/{country}/{lang}/bangladesh"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status != 200:
                return None
            html = await r.text()
            text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
            matches = re.findall(r"(\d{2,4}\.\d{1,6})\s*BDT", text)
            if not matches:
                return None
            return Rate("Remitly", url, round(max(float(m) for m in matches), 3),
                        "Bank, Mobile Wallet, Cash Pickup")
    except Exception as e:
        print(f"  [Remitly] {src}: {e}")
        return None


TAPTAPSEND_API = "https://api.taptapsend.com/api/fxRates"
TAPTAPSEND_HEADERS = {
    "Appian-Version": "web/2022-05-03.0",
    "X-Device-Id": "web",
    "X-Device-Model": "web",
}
TAPTAPSEND_URL = "https://www.taptapsend.com/send-money-to/bangladesh"

_taptapsend_cache: dict[str, float] | None = None


async def _load_taptapsend(session: aiohttp.ClientSession) -> dict[str, float]:
    """Fetch all BDT rates from TapTapSend in a single API call, cached."""
    global _taptapsend_cache
    if _taptapsend_cache is not None:
        return _taptapsend_cache

    rates: dict[str, float] = {}
    try:
        async with session.get(TAPTAPSEND_API, headers=TAPTAPSEND_HEADERS,
                               timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status != 200:
                return rates
            data = await r.json(content_type=None)
            for country in data.get("availableCountries", []):
                cur = country["currency"]
                for corridor in country.get("corridors", []):
                    if corridor.get("currency") == "BDT":
                        rate = float(corridor["fxRate"])
                        if cur not in rates or rate > rates[cur]:
                            rates[cur] = rate
    except Exception as e:
        print(f"  [TapTapSend] load failed: {e}")

    _taptapsend_cache = rates
    return rates


async def scrape_taptapsend(session: aiohttp.ClientSession, src: str) -> Rate | None:
    try:
        rates = await _load_taptapsend(session)
        rate = rates.get(src)
        if rate is None:
            return None
        return Rate("TapTapSend", TAPTAPSEND_URL,
                    round(rate, 3), "Bank, Mobile Wallet")
    except Exception as e:
        print(f"  [TapTapSend] {src}: {e}")
        return None


SCRAPERS = [scrape_wise, scrape_remitly, scrape_taptapsend]


# ── Fetch (all currencies × all providers in parallel) ───────────────────────

async def _fetch_one(session: aiohttp.ClientSession, fn, code: str) -> tuple[str, str, Rate | None]:
    result = await fn(session, code)
    name = fn.__name__.replace("scrape_", "")
    tag = f"✅ {result.provider}: {result.rate}" if result else f"❌ {name}"
    print(f"  {code}: {tag}")
    return (code, name, result)


async def fetch_all() -> dict:
    now = datetime.now(timezone.utc).isoformat()
    data: dict[str, list[dict]] = {code: [] for code, *_ in CURRENCIES}

    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    conn = aiohttp.TCPConnector(ssl=ssl_ctx)
    async with aiohttp.ClientSession(headers=HEADERS, connector=conn) as session:
        tasks = [
            _fetch_one(session, fn, code)
            for code, *_ in CURRENCIES
            for fn in SCRAPERS
        ]
        results = await asyncio.gather(*tasks)

    for code, _, rate in results:
        if rate:
            data[code].append(asdict(rate))

    for code in data:
        data[code].sort(key=lambda r: r["rate"], reverse=True)

    return {"updated_at": now, "target": TARGET, "rates": data}


# ── README from JSON ──────────────────────────────────────────────────────────

def build_readme(raw: dict) -> str:
    updated = datetime.fromisoformat(raw["updated_at"]).strftime("%Y-%m-%d %H:%M UTC")
    rates_map: dict[str, list[dict]] = raw["rates"]
    L: list[str] = []

    L.append("# Any Currency to BDT")
    L.append("")
    L.append("Live remittance exchange rates to **Bangladeshi Taka (BDT)**, scraped directly from provider websites.")
    L.append("")
    L.append(f"**Last updated:** `{updated}`")
    L.append("")

    L.append("## Rates")
    L.append("")
    for code, symbol, flag, name in CURRENCIES:
        rates = rates_map.get(code, [])
        L.append(f"### {code} to BDT")
        L.append("")
        if not rates:
            L.append("No rates available.")
            L.append("")
            continue
        best = rates[0]["rate"]
        L.append(f"| # | Provider | 1 {code} = BDT | Delivery |")
        L.append("|--:|----------|---------------:|----------|")
        for i, r in enumerate(rates, 1):
            is_best = r["rate"] == best
            rank = f"**{i}**" if is_best else str(i)
            rate_str = f"**{r['rate']:.3f}**" if is_best else f"{r['rate']:.3f}"
            provider_str = f"[{r['provider']}]({r['url']})"
            L.append(f"| {rank} | {provider_str} | {rate_str} | {r['delivery']} |")
        L.append("")

    L.append("## Data")
    L.append("")
    L.append("Raw rate data is available in [`rates.json`](rates.json) for programmatic use:")
    L.append("")
    L.append("```json")
    L.append('{')
    L.append(f'  "updated_at": "{raw["updated_at"]}",')
    L.append('  "target": "BDT",')
    L.append('  "rates": {')
    L.append('    "USD": [')
    L.append('      { "provider": "Wise", "rate": 122.200, ... },')
    L.append('      { "provider": "Remitly", "rate": 121.920, ... }')
    L.append('    ],')
    L.append('    ...')
    L.append('  }')
    L.append('}')
    L.append("```")
    L.append("")

    L.append("## Disclaimer")
    L.append("")
    L.append("This project is independent and not affiliated with any remittance provider. Rates are scraped from publicly accessible pages and may not reflect actual transfer rates or fees. Always confirm on the provider's website before sending money.")
    L.append("")

    L.append("---")
    L.append("")
    L.append(f"*Auto-generated on {updated}*")
    L.append("")

    return "\n".join(L)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    json_path = ROOT / "rates.json"
    readme_path = ROOT / "README.md"

    start = time.monotonic()
    data = asyncio.run(fetch_all())
    elapsed = time.monotonic() - start

    json_path.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")
    readme = build_readme(data)
    readme_path.write_text(readme, encoding="utf-8")

    total = sum(len(v) for v in data["rates"].values())
    print(f"\n✅ {total} rates fetched in {elapsed:.1f}s")
