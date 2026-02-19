#!/usr/bin/env python3
"""Fetch BDT exchange rates from provider websites, save to rates.json, build README.md.

To add a new provider, subclass ``Provider`` and implement ``fetch_rate``:

    class MyProvider(Provider):
        name     = "MyProvider"
        url      = "https://example.com/bangladesh"
        delivery = "Bank"

        async def fetch_rate(self, session, src):
            async with session.get(f"https://api.example.com/{src}", timeout=TIMEOUT) as r:
                if r.status != 200:
                    return None
                data = await r.json(content_type=None)
                return data.get("rate")

That's it — the provider auto-registers and the runner picks it up.
"""
from __future__ import annotations

import asyncio
import json
import re
import ssl
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar

import aiohttp
import certifi
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
TARGET = "BDT"
TIMEOUT = aiohttp.ClientTimeout(total=10)

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


@dataclass
class Rate:
    provider: str
    url: str
    rate: float
    delivery: str


# ── Provider base class ──────────────────────────────────────────────────────

_providers: list[Provider] = []


class Provider(ABC):
    """Base class for all rate providers.

    Subclasses must set three class attributes (``name``, ``url``,
    ``delivery``) and implement :meth:`fetch_rate`.  Everything else —
    error handling, ``Rate`` construction, registration — is automatic.

    Override :meth:`get_url` if the provider URL varies per currency.
    """

    name: ClassVar[str]
    url: ClassVar[str]
    delivery: ClassVar[str]

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not getattr(cls, "__abstractmethods__", frozenset()):
            _providers.append(cls())

    @abstractmethod
    async def fetch_rate(
        self, session: aiohttp.ClientSession, src: str
    ) -> float | None:
        """Return the BDT exchange rate for *src* currency, or ``None``."""

    def get_url(self, src: str) -> str:
        """Return the user-facing URL for a given source currency."""
        return self.url

    async def scrape(
        self, session: aiohttp.ClientSession, src: str
    ) -> Rate | None:
        """Fetch, wrap in a ``Rate``, and handle errors. Do not override."""
        try:
            rate = await self.fetch_rate(session, src)
            if rate is None:
                return None
            return Rate(self.name, self.get_url(src), round(rate, 3), self.delivery)
        except Exception as e:
            print(f"  [{self.name}] {src}: {e}")
            return None


# ── Providers ────────────────────────────────────────────────────────────────


class Wise(Provider):
    name = "Wise"
    url = "https://wise.com/us/currency-converter/usd-to-bdt-rate"
    delivery = "Bank"

    _REGIONS: ClassVar[dict[str, str]] = {
        "USD": "us", "GBP": "gb", "EUR": "de", "CAD": "ca", "AUD": "au",
        "SGD": "sg", "AED": "ae", "MYR": "my", "SAR": "sa", "KWD": "kw",
        "QAR": "qa", "JPY": "jp", "NZD": "nz", "BHD": "bh", "OMR": "om",
    }

    async def fetch_rate(self, session, src):
        url = f"https://wise.com/rates/live?source={src}&target={TARGET}"
        async with session.get(url, timeout=TIMEOUT) as r:
            if r.status != 200:
                return None
            data = await r.json(content_type=None)
            return data.get("value")

    def get_url(self, src):
        region = self._REGIONS.get(src, "us")
        return f"https://wise.com/{region}/currency-converter/{src.lower()}-to-bdt-rate"


class Remitly(Provider):
    name = "Remitly"
    url = "https://www.remitly.com/us/en/bangladesh"
    delivery = "Bank, Mobile Wallet, Cash Pickup"

    _REGIONS: ClassVar[dict[str, tuple[str, str]]] = {
        "USD": ("us", "en"), "GBP": ("gb", "en"), "EUR": ("de", "en"),
        "CAD": ("ca", "en"), "AUD": ("au", "en"),
    }

    async def fetch_rate(self, session, src):
        region = self._REGIONS.get(src)
        if not region:
            return None
        country, lang = region
        url = f"https://www.remitly.com/{country}/{lang}/bangladesh"
        async with session.get(url, timeout=TIMEOUT) as r:
            if r.status != 200:
                return None
            html = await r.text()
            text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
            matches = re.findall(r"(\d{2,4}\.\d{1,6})\s*BDT", text)
            if not matches:
                return None
            return max(float(m) for m in matches)

    def get_url(self, src):
        country, lang = self._REGIONS.get(src, ("us", "en"))
        return f"https://www.remitly.com/{country}/{lang}/bangladesh"


class TapTapSend(Provider):
    name = "TapTapSend"
    url = "https://www.taptapsend.com/send-money-to/bangladesh"
    delivery = "Bank, Mobile Wallet"

    _API = "https://api.taptapsend.com/api/fxRates"
    _API_HEADERS: ClassVar[dict[str, str]] = {
        "Appian-Version": "web/2022-05-03.0",
        "X-Device-Id": "web",
        "X-Device-Model": "web",
    }

    def __init__(self):
        self._cache: dict[str, float] | None = None

    async def _load(self, session: aiohttp.ClientSession) -> dict[str, float]:
        if self._cache is not None:
            return self._cache
        rates: dict[str, float] = {}
        async with session.get(self._API, headers=self._API_HEADERS,
                               timeout=TIMEOUT) as r:
            if r.status != 200:
                return rates
            data = await r.json(content_type=None)
            for country in data.get("availableCountries", []):
                cur = country["currency"]
                for corridor in country.get("corridors", []):
                    if corridor.get("currency") == TARGET:
                        rate = float(corridor["fxRate"])
                        if cur not in rates or rate > rates[cur]:
                            rates[cur] = rate
        self._cache = rates
        return rates

    async def fetch_rate(self, session, src):
        return (await self._load(session)).get(src)


class Nala(Provider):
    name = "NALA"
    url = "https://www.nala.com/country/bangladesh"
    delivery = "Bank, Mobile Wallet"

    _API = "https://partners-api.prod.nala-api.com/v1/fx/rates"

    def __init__(self):
        self._cache: dict[str, float] | None = None

    async def _load(self, session: aiohttp.ClientSession) -> dict[str, float]:
        if self._cache is not None:
            return self._cache
        rates: dict[str, float] = {}
        async with session.get(self._API, timeout=TIMEOUT) as r:
            if r.status != 200:
                return rates
            data = await r.json(content_type=None)
            for entry in data.get("data", []):
                if (entry.get("destination_currency") == TARGET
                        and entry.get("provider_name") == "NALA"):
                    rates[entry["source_currency"]] = float(entry["rate"])
        self._cache = rates
        return rates

    async def fetch_rate(self, session, src):
        return (await self._load(session)).get(src)


class Instarem(Provider):
    name = "Instarem"
    url = "https://www.instarem.com/en-us/currency-conversion/usd-to-bdt/"
    delivery = "Bank"

    _API = "https://www.instarem.com/wp-json/instarem/v2/convert-rate"

    def __init__(self):
        self._cache: dict[str, float] = {}

    async def fetch_rate(self, session, src):
        if src in self._cache:
            return self._cache[src]
        url = f"{self._API}/{src.lower()}/"
        async with session.get(url, timeout=TIMEOUT) as r:
            if r.status != 200:
                return None
            data = await r.json(content_type=None)
            rates = data.get("data", {}) if data.get("status") else data
            bdt = rates.get(TARGET)
            if bdt is not None:
                self._cache[src] = float(bdt)
                return self._cache[src]
        return None

    def get_url(self, src):
        return f"https://www.instarem.com/en-us/currency-conversion/{src.lower()}-to-bdt/"


# ── Runner ───────────────────────────────────────────────────────────────────


async def _fetch_one(
    session: aiohttp.ClientSession, provider: Provider, code: str
) -> tuple[str, Rate | None]:
    result = await provider.scrape(session, code)
    tag = f"✅ {result.provider}: {result.rate}" if result else f"❌ {provider.name}"
    print(f"  {code}: {tag}")
    return (code, result)


async def fetch_all() -> dict:
    now = datetime.now(timezone.utc).isoformat()
    data: dict[str, list[dict]] = {code: [] for code, *_ in CURRENCIES}

    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    conn = aiohttp.TCPConnector(ssl=ssl_ctx)
    async with aiohttp.ClientSession(headers=HEADERS, connector=conn) as session:
        tasks = [
            _fetch_one(session, provider, code)
            for code, *_ in CURRENCIES
            for provider in _providers
        ]
        results = await asyncio.gather(*tasks)

    for code, rate in results:
        if rate:
            data[code].append(asdict(rate))

    for code in data:
        data[code].sort(key=lambda r: r["rate"], reverse=True)

    return {"updated_at": now, "target": TARGET, "rates": data}


# ── README builder ───────────────────────────────────────────────────────────


def build_readme(raw: dict) -> str:
    updated = datetime.fromisoformat(raw["updated_at"]).strftime("%Y-%m-%d %H:%M UTC")
    rates_map: dict[str, list[dict]] = raw["rates"]
    lines: list[str] = []

    lines.append("# Any Currency to BDT")
    lines.append("")
    lines.append("Live remittance exchange rates to **Bangladeshi Taka (BDT)**,"
                  " scraped directly from provider websites.")
    lines.append("")
    lines.append(f"**Last updated:** `{updated}`")
    lines.append("")

    lines.append("## Rates")
    lines.append("")
    for code, symbol, flag, name in CURRENCIES:
        rates = rates_map.get(code, [])
        lines.append(f"### {code} to BDT")
        lines.append("")
        if not rates:
            lines.append("No rates available.")
            lines.append("")
            continue
        best = rates[0]["rate"]
        lines.append(f"| # | Provider | 1 {code} = BDT | Delivery |")
        lines.append("|--:|----------|---------------:|----------|")
        for i, r in enumerate(rates, 1):
            is_best = r["rate"] == best
            rank = f"**{i}**" if is_best else str(i)
            rate_str = f"**{r['rate']:.3f}**" if is_best else f"{r['rate']:.3f}"
            provider_str = f"[{r['provider']}]({r['url']})"
            lines.append(f"| {rank} | {provider_str} | {rate_str} | {r['delivery']} |")
        lines.append("")

    lines.append("## Data")
    lines.append("")
    lines.append("Raw rate data is available in [`rates.json`](rates.json)"
                  " for programmatic use:")
    lines.append("")
    lines.append("```json")
    lines.append("{")
    lines.append(f'  "updated_at": "{raw["updated_at"]}",')
    lines.append('  "target": "BDT",')
    lines.append('  "rates": {')
    lines.append('    "USD": [')
    lines.append('      { "provider": "Wise", "rate": 122.200, ... },')
    lines.append('      { "provider": "Remitly", "rate": 121.920, ... }')
    lines.append("    ],")
    lines.append("    ...")
    lines.append("  }")
    lines.append("}")
    lines.append("```")
    lines.append("")

    lines.append("## Disclaimer")
    lines.append("")
    lines.append("This project is independent and not affiliated with any"
                  " remittance provider. Rates are scraped from publicly"
                  " accessible pages and may not reflect actual transfer rates"
                  " or fees. Always confirm on the provider's website before"
                  " sending money.")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"*Auto-generated on {updated}*")
    lines.append("")

    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────────

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
