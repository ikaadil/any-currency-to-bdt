#!/usr/bin/env python3
"""Fetch BDT exchange rates by scraping provider websites, save to rates.json, build README.md."""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from pathlib import Path

import httpx
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

async def scrape_wise(client: httpx.AsyncClient, src: str) -> Rate | None:
    try:
        r = await client.get(
            "https://wise.com/rates/live",
            params={"source": src, "target": TARGET},
            headers=HEADERS, timeout=15,
        )
        if r.status_code != 200:
            return None
        val = r.json().get("value")
        if val is None:
            return None
        region = WISE_REGION.get(src, "us")
        return Rate("Wise",
                     f"https://wise.com/{region}/currency-converter/{src.lower()}-to-bdt-rate",
                     round(float(val), 3), "Bank")
    except Exception as e:
        print(f"  [Wise] {src}: {e}")
        return None


async def scrape_remitly(client: httpx.AsyncClient, src: str) -> Rate | None:
    region = REMITLY_REGION.get(src)
    if not region:
        return None
    country, lang = region
    url = f"https://www.remitly.com/{country}/{lang}/bangladesh"
    try:
        r = await client.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
        if r.status_code != 200:
            return None
        text = BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)
        matches = re.findall(r"(\d{2,4}\.\d{1,6})\s*BDT", text)
        if not matches:
            return None
        return Rate("Remitly", url, round(max(float(m) for m in matches), 3),
                     "Bank, Mobile Wallet, Cash Pickup")
    except Exception as e:
        print(f"  [Remitly] {src}: {e}")
        return None


SCRAPERS = [scrape_wise, scrape_remitly]


# ── Fetch ─────────────────────────────────────────────────────────────────────

async def fetch_all() -> dict:
    now = datetime.now(timezone.utc).isoformat()
    data: dict[str, list[dict]] = {}

    async with httpx.AsyncClient(follow_redirects=True) as client:
        for code, *_ in CURRENCIES:
            print(f"📡 {code} -> {TARGET}")
            rates: list[Rate] = []
            for fn in SCRAPERS:
                result = await fn(client, code)
                if result:
                    rates.append(result)
                    print(f"   ✅ {result.provider}: {result.rate}")
                else:
                    print(f"   ❌ {fn.__name__.replace('scrape_', '')}")
            rates.sort(key=lambda r: r.rate, reverse=True)
            data[code] = [asdict(r) for r in rates]

    return {"updated_at": now, "target": TARGET, "rates": data}


# ── README from JSON ──────────────────────────────────────────────────────────

def build_readme(raw: dict) -> str:
    updated = datetime.fromisoformat(raw["updated_at"]).strftime("%Y-%m-%d %H:%M UTC")
    rates_map: dict[str, list[dict]] = raw["rates"]
    providers = _collect_providers(rates_map)
    L: list[str] = []

    # Header
    L.append("# Any Currency to BDT")
    L.append("")
    L.append("Live remittance exchange rates to **Bangladeshi Taka (BDT)**, scraped directly from provider websites.")
    L.append("")
    L.append(f"**Last updated:** `{updated}`")
    L.append("")

    # Quick nav
    L.append("## Currencies")
    L.append("")
    for code, symbol, flag, name in CURRENCIES:
        count = len(rates_map.get(code, []))
        label = "provider" if count == 1 else "providers"
        L.append(f"- [{flag} **{code}** — {name}](#{code.lower()}-to-bdt) ({count} {label})")
    L.append("")

    # Rate tables
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

    # Providers
    L.append("## Providers")
    L.append("")
    L.append("| Provider | Source | Method |")
    L.append("|----------|--------|--------|")
    L.append("| [Wise](https://wise.com) | `wise.com/rates/live` | JSON endpoint |")
    L.append("| [Remitly](https://www.remitly.com) | `remitly.com/{region}/en/bangladesh` | HTML scrape |")
    L.append("")
    L.append("Adding a provider? Write one async function in `fetch_rates.py` and append it to `SCRAPERS`.")
    L.append("")

    # How it works
    L.append("## How it works")
    L.append("")
    L.append("```")
    L.append("fetch_rates.py  →  rates.json  →  README.md")
    L.append("     ↑                                 ↑")
    L.append("  scrape providers              generated from JSON")
    L.append("```")
    L.append("")
    L.append("A [GitHub Actions cron job](.github/workflows/update-rates.yml) runs this daily at `00:00 UTC` and commits the results.")
    L.append("")

    # Data
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

    # Disclaimer
    L.append("## Disclaimer")
    L.append("")
    L.append("This project is independent and not affiliated with any remittance provider. Rates are scraped from publicly accessible pages and may not reflect actual transfer rates or fees. Always confirm on the provider's website before sending money.")
    L.append("")

    # Footer
    L.append("---")
    L.append("")
    L.append(f"*Auto-generated on {updated}*")
    L.append("")

    return "\n".join(L)


def _collect_providers(rates_map: dict[str, list[dict]]) -> set[str]:
    providers: set[str] = set()
    for rates in rates_map.values():
        for r in rates:
            providers.add(r["provider"])
    return providers


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    json_path = ROOT / "rates.json"
    readme_path = ROOT / "README.md"

    data = asyncio.run(fetch_all())

    json_path.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")
    print(f"\n📄 rates.json written")

    readme = build_readme(data)
    readme_path.write_text(readme, encoding="utf-8")

    total = sum(len(v) for v in data["rates"].values())
    print(f"📝 README.md written — {total} rates")
