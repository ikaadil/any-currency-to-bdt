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
    updated = datetime.fromisoformat(raw["updated_at"]).strftime("%B %d, %Y at %H:%M UTC")
    rates_map: dict[str, list[dict]] = raw["rates"]
    lines: list[str] = []

    lines.append("# 💱 Any Currency to BDT — Live Exchange Rates\n")
    lines.append("> Compare live remittance rates to **BDT** from top transfer services.\n>")
    lines.append(f"> 🔄 **Last updated:** {updated}\n>")
    lines.append("> ⚙️ Auto-updated daily via GitHub Actions.\n")

    nav = " | ".join(f"[{flag} {code}](#{code.lower()}-to-bdt)" for code, _, flag, _ in CURRENCIES)
    lines.append(nav + "\n")
    lines.append("---\n")

    for code, symbol, flag, name in CURRENCIES:
        rates = rates_map.get(code, [])
        lines.append(f"### {flag} {code} to BDT\n")
        if not rates:
            lines.append("> ⚠️ No rates available at this time.\n")
        else:
            best = rates[0]["rate"]
            lines.append("| # | Provider | Rate | Delivery |")
            lines.append("|:-:|----------|-----:|----------|")
            for i, r in enumerate(rates, 1):
                star = " ⭐" if r["rate"] == best else ""
                fmt = f"**{r['rate']:.3f}**" if r["rate"] == best else f"{r['rate']:.3f}"
                lines.append(f"| {i} | [{r['provider']}]({r['url']}){star} | {fmt} | {r['delivery']} |")
            lines.append(f"\n> 1 {symbol} {code} = **{best:.3f} BDT** (best rate)\n")
        lines.append("---\n")

    lines.append("### Tracked Providers\n")
    lines.append("- [Wise](https://wise.com)")
    lines.append("- [Remitly](https://www.remitly.com)\n")
    lines.append("> *More providers coming soon — PRs welcome!*\n")
    lines.append("### Disclaimer\n")
    lines.append(
        "> This project is independent and not affiliated with any provider. "
        "Rates are scraped from public pages and may differ from actual transfer rates. "
        "Always confirm on the provider's site before sending money.\n")
    lines.append(f"<sub>Last updated: {updated}</sub>\n")
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    json_path = ROOT / "rates.json"
    readme_path = ROOT / "README.md"

    data = asyncio.run(fetch_all())

    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n📄 rates.json written")

    readme = build_readme(data)
    readme_path.write_text(readme, encoding="utf-8")

    total = sum(len(v) for v in data["rates"].values())
    print(f"📝 README.md written — {total} rates")
