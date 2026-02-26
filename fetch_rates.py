#!/usr/bin/env python3
"""Fetch BDT exchange rates and fees from provider websites, save to rates.json, build README.md.

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
                rate = data.get("rate")
                fee = data.get("fee")  # optional
                return (rate, fee) if fee is not None else rate

That's it — the provider auto-registers and the runner picks it up.
"""
from __future__ import annotations

import asyncio
import json
import re
import ssl
import time
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
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
    fee: float | None = None


# ── Browser pool (shared Chromium for all browser-based providers) ────────────


class BrowserPool:
    """Single Chromium instance with a semaphore-controlled page pool.

    Avoids launching multiple browsers and serialises page usage to *max_pages*
    concurrent tabs.  Lazy-starts on first ``page()`` call.
    """

    def __init__(self, max_pages: int = 12):
        self._sem = asyncio.Semaphore(max_pages)
        self._pw: object | None = None
        self._browser: object | None = None
        self._context: object | None = None
        self._started = False
        self._init_lock = asyncio.Lock()

    async def _start(self) -> None:
        if self._started:
            return
        async with self._init_lock:
            if self._started:
                return
            from playwright.async_api import async_playwright

            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            self._context = await self._browser.new_context(
                viewport={"width": 1440, "height": 900},
                user_agent=HEADERS["User-Agent"],
                locale="en-US",
            )
            await self._context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', "
                "{ get: () => undefined });"
            )
            self._started = True

    _BLOCKED = {"image", "media", "font", "stylesheet"}
    _BLOCKED_DOMAINS = {
        "google-analytics.com", "googletagmanager.com", "facebook.net",
        "doubleclick.net", "hotjar.com", "segment.io", "segment.com",
        "newrelic.com", "nr-data.net", "sentry.io", "datadoghq.com",
        "optimizely.com", "amplitude.com", "mixpanel.com", "braze.com",
        "appsflyer.com", "branch.io", "mparticle.com",
    }

    @asynccontextmanager
    async def page(self):
        """Yield a fresh browser page, then close it."""
        await self._start()
        async with self._sem:
            p = await self._context.new_page()

            def _should_block(route):
                req = route.request
                if req.resource_type in self._BLOCKED:
                    return True
                url = req.url
                return any(d in url for d in self._BLOCKED_DOMAINS)

            await p.route(
                "**/*",
                lambda route: (
                    route.abort() if _should_block(route) else route.continue_()
                ),
            )
            try:
                yield p
            finally:
                await p.close()

    async def stop(self) -> None:
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._pw:
            await self._pw.stop()
            self._pw = None
        self._started = False


_pool = BrowserPool()


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
    ) -> float | tuple[float, float | None] | None:
        """Return the BDT rate (or (rate, fee)) for *src* currency, or ``None``."""

    def get_url(self, src: str) -> str:
        """Return the user-facing URL for a given source currency."""
        return self.url

    async def scrape(
        self, session: aiohttp.ClientSession, src: str
    ) -> Rate | None:
        """Fetch, wrap in a ``Rate``, and handle errors. Do not override."""
        try:
            result = await self.fetch_rate(session, src)
            if result is None:
                return None
            if isinstance(result, (list, tuple)) and len(result) >= 2:
                rate, fee = result[0], result[1]
            else:
                rate, fee = result, None
            return Rate(
                self.name, self.get_url(src), round(rate, 3), self.delivery,
                fee=round(fee, 2) if fee is not None else None,
            )
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


class Xe(Provider):
    """Scrapes Xe currency converter (mid-market rate; they also offer send-money to Bangladesh)."""

    name = "Xe"
    url = "https://www.xe.com/currencyconverter/convert/?Amount=1&From=USD&To=BDT"
    delivery = "Bank"

    async def fetch_rate(self, session, src):
        url = f"https://www.xe.com/currencyconverter/convert/?Amount=1&From={src}&To=BDT"
        async with session.get(url, timeout=TIMEOUT) as r:
            if r.status != 200:
                return None
            html = await r.text()
            text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
            # Xe format: "1.00 EUR = 144.26367589 BDT" or "1.00 EUR \= 144.26... BDT" (all pairs)
            # Allow optional backslash before = (HTML/encoding quirk)
            for pat in (
                rf"1\.0+\s+{re.escape(src)}\s*\\?=\s*([\d.,]+)\s*BDT",
                rf"1\s+{re.escape(src)}\s*\\?=\s*([\d.,]+)\s*BDT",
            ):
                m = re.search(pat, text)
                if m:
                    try:
                        rate = float(m.group(1).replace(",", ""))
                    except (ValueError, TypeError):
                        continue
                    # Plausible BDT per 1 unit: JPY ~0.78, AED/SAR/QAR/MYR ~31-34, USD/GBP/EUR etc 80-165, KWD ~398
                    if src == "JPY":
                        if 0.1 < rate < 2:
                            return rate
                    elif 5 < rate < 1000:
                        return rate
            return None

    def get_url(self, src):
        return f"https://www.xe.com/currencyconverter/convert/?Amount=1&From={src}&To=BDT"


class OrbitRemit(Provider):
    """Scrapes OrbitRemit currency converter (AUD/NZD to BDT)."""

    name = "OrbitRemit"
    url = "https://www.orbitremit.com/currency-converter/aud-to-bdt"
    delivery = "Bank, Mobile Wallet"

    _CURRENCIES: ClassVar[dict[str, str]] = {
        "AUD": "aud-to-bdt",
        "NZD": "nzd-to-bdt",
    }

    async def fetch_rate(self, session, src):
        path = self._CURRENCIES.get(src)
        if not path:
            return None
        url = f"https://www.orbitremit.com/currency-converter/{path}"
        async with session.get(url, timeout=TIMEOUT) as r:
            if r.status != 200:
                return None
            html = await r.text()
            text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
            # Prefer "1 AUD = X BDT" if present
            m = re.search(rf"1\s+{src}\s*=\s*([\d,.]+)\s*BDT", text, re.I)
            if m:
                rate = float(m.group(1).replace(",", ""))
                if 50 < rate < 200 or (0.1 < rate < 2 and src == "NZD"):
                    return rate
            # Page table has 5 AUD = 434.76 BDT (no 1 AUD row); derive rate = bdt/amount
            for amount in (5, 10, 1):
                m = re.search(rf"{amount}\s+{src}\s+([\d,.]+)\s*BDT", text, re.I)
                if m:
                    bdt = float(m.group(1).replace(",", ""))
                    rate = bdt / amount
                    if 80 < rate < 95 and src == "AUD":
                        return rate
                    if 50 < rate < 100 and src == "NZD":
                        return rate
            matches = re.findall(r"(\d{2,4}\.\d{1,6})\s*BDT", text)
            valid = [float(x) for x in matches if 80 < float(x) < 95]  # AUD→BDT ~86
            if valid and src == "AUD":
                return min(valid)
            valid = [float(x) for x in matches if 50 < float(x) < 200]
            return min(valid) if valid else None

    def get_url(self, src):
        path = self._CURRENCIES.get(src, "aud-to-bdt")
        return f"https://www.orbitremit.com/currency-converter/{path}"


class SendWave(Provider):
    name = "SendWave"
    url = "https://www.sendwave.com/en/currency-converter/usd_us-bdt_bd"
    delivery = "Bank, Mobile Wallet"

    _API = "https://app.sendwave.com/v2/pricing-public"
    _CORRIDORS: ClassVar[dict[str, tuple[str, str]]] = {
        "USD": ("US", "USD"), "GBP": ("GB", "GBP"),
        "EUR": ("DE", "EUR"), "CAD": ("CA", "CAD"),
    }

    async def fetch_rate(self, session, src):
        corridor = self._CORRIDORS.get(src)
        if not corridor:
            return None
        country, curr = corridor
        params = {
            "amount": "100",
            "amountType": "SEND",
            "sendCountryIso2": country,
            "sendCurrency": curr,
            "receiveCountryIso2": "BD",
            "receiveCurrency": "BDT",
        }
        async with session.get(self._API, params=params, timeout=TIMEOUT) as r:
            if r.status != 200:
                return None
            data = await r.json(content_type=None)
            rate = data.get("baseExchangeRate")
            fee_str = data.get("baseFeeAmount")
            if not rate:
                return None
            fee = float(fee_str) if fee_str is not None else None
            return (float(rate), fee)

    def get_url(self, src):
        corridor = self._CORRIDORS.get(src)
        if corridor:
            country, curr = corridor
            return f"https://www.sendwave.com/en/currency-converter/{curr.lower()}_{country.lower()}-bdt_bd"
        return self.url


class Paysend(Provider):
    name = "Paysend"
    url = "https://paysend.com/en-us/send-money/from-the-united-states-of-america-to-bangladesh"
    delivery = "Bank, Card"

    _REGIONS: ClassVar[dict[str, tuple[str, str]]] = {
        "USD": ("en-us", "the-united-states-of-america"),
        "EUR": ("en-us", "germany"),
        "CAD": ("en-ca", "canada"),
        "AUD": ("en-au", "australia"),
    }

    async def fetch_rate(self, session, src):
        region = self._REGIONS.get(src)
        if not region:
            return None
        locale, country = region
        url = f"https://paysend.com/{locale}/send-money/from-{country}-to-bangladesh"
        async with session.get(url, timeout=TIMEOUT) as r:
            if r.status != 200:
                return None
            html = await r.text()
            text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
            m = re.search(rf"1\.00\s+{src}\s*=\s*([\d.]+)\s*BDT", text)
            if not m:
                return None
            rate = float(m.group(1))
            fee_m = re.search(r"Fee:\s*([\d.]+)\s*(?:USD|EUR|GBP|CAD|AUD)", text)
            fee = float(fee_m.group(1)) if fee_m else None
            return (rate, fee)

    def get_url(self, src):
        region = self._REGIONS.get(src, ("en-us", "the-united-states-of-america"))
        locale, country = region
        return f"https://paysend.com/{locale}/send-money/from-{country}-to-bangladesh"


class WesternUnion(Provider):
    """Scrapes WU's currency converter pages via the shared browser pool."""

    name = "Western Union"
    url = "https://www.westernunion.com/us/en/currency-converter/usd-to-bdt-rate.html"
    delivery = "Bank, Cash Pickup, Mobile Wallet"

    _REGIONS: ClassVar[dict[str, str]] = {
        "USD": "us", "GBP": "gb", "EUR": "de", "CAD": "ca", "AUD": "au",
        "SGD": "sg", "JPY": "jp",
    }

    async def fetch_rate(self, session, src):
        if src not in self._REGIONS:
            return None
        region = self._REGIONS[src]
        url = (
            f"https://www.westernunion.com/{region}/en/"
            f"currency-converter/{src.lower()}-to-bdt-rate.html"
        )
        js = """
            () => {
                const m = document.body.innerText.match(
                    /FX:\\s*1\\.00\\s*%s\\s*[–\\-]\\s*([\\d,]+\\.\\d+)\\s*BDT/
                );
                return m ? parseFloat(m[1].replace(/,/g, '')) : null;
            }
        """ % src
        async with _pool.page() as page:
            await page.goto(url, wait_until="domcontentloaded", timeout=10000)
            try:
                handle = await page.wait_for_function(js, timeout=6000)
                return await handle.json_value()
            except Exception:
                return None

    def get_url(self, src):
        region = self._REGIONS.get(src, "us")
        return (
            f"https://www.westernunion.com/{region}/en/"
            f"currency-converter/{src.lower()}-to-bdt-rate.html"
        )


class WorldRemit(Provider):
    """Scrapes WorldRemit's send-money pages via the shared browser pool."""

    name = "WorldRemit"
    url = "https://www.worldremit.com/en-us/bangladesh"
    delivery = "Bank, Mobile Wallet, Cash Pickup"

    _REGIONS: ClassVar[dict[str, str]] = {
        "USD": "en-us", "GBP": "en-gb", "CAD": "en-ca", "AUD": "en-au",
    }

    async def fetch_rate(self, session, src):
        region = self._REGIONS.get(src)
        if not region:
            return None
        url = f"https://www.worldremit.com/{region}/bangladesh"
        js = """
            () => {
                const m = document.body.innerText.match(
                    /1\\s*%s\\s*=\\s*([\\d,]+\\.\\d+)\\s*BDT/
                );
                return m ? parseFloat(m[1].replace(/,/g, '')) : null;
            }
        """ % src
        async with _pool.page() as page:
            await page.goto(url, wait_until="domcontentloaded", timeout=10000)
            try:
                handle = await page.wait_for_function(js, timeout=6000)
                return await handle.json_value()
            except Exception:
                return None

    def get_url(self, src):
        region = self._REGIONS.get(src, "en-us")
        return f"https://www.worldremit.com/{region}/bangladesh"


class Xoom(Provider):
    """Scrapes Xoom (PayPal) send-money pages via the shared browser pool.

    Xoom auto-detects the sending currency from IP geolocation. We load the
    page once, detect which currency is displayed, and cache that single rate.
    """

    name = "Xoom"
    url = "https://www.xoom.com/bangladesh/send-money"
    delivery = "Bank, Cash Pickup, Mobile Wallet"

    _JS = """
        () => {
            const m = document.body.innerText.match(
                /1\\s+([A-Z]{3})\\s*=\\s*([\\d,]+\\.\\d+)\\s*BDT/
            );
            return m ? [m[1], parseFloat(m[2].replace(/,/g, ''))] : null;
        }
    """

    def __init__(self):
        self._cache: dict[str, float] = {}
        self._loaded = False
        self._load_lock = asyncio.Lock()

    async def _load(self) -> None:
        if self._loaded:
            return
        async with self._load_lock:
            if self._loaded:
                return
            async with _pool.page() as page:
                await page.goto(self.url, wait_until="domcontentloaded", timeout=10000)
                try:
                    handle = await page.wait_for_function(self._JS, timeout=6000)
                    pair = await handle.json_value()
                    if pair:
                        self._cache[pair[0]] = pair[1]
                except Exception:
                    pass
            self._loaded = True

    async def fetch_rate(self, session, src):
        await self._load()
        return self._cache.get(src)


_ria_fetch_lock: asyncio.Lock | None = None


def _scrapling_body_html(page) -> str:
    """Get HTML string from Scrapling response; page.body may be bytes or str."""
    body = page.body
    if isinstance(body, bytes):
        return body.decode(getattr(page, "encoding", None) or "utf-8")
    return body if isinstance(body, str) else ""


def _scrapling_ria_fetch_sync(src: str) -> float | None:
    """Fetch Ria rate via Scrapling StealthyFetcher (blocking). Returns rate or None."""
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return None
    StealthyFetcher.adaptive = True
    url = f"https://www.riamoneytransfer.com/en-us/rates-conversion/?From={src}&To=BDT&Amount=1"
    try:
        page = StealthyFetcher.fetch(url, headless=True, network_idle=True)
    except Exception:
        return None
    html = _scrapling_body_html(page)
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    # Page shows "1.00000 = 121.95062" for the conversion result; prefer that over any "X BDT"
    m = re.search(r"1\.0+\s*=\s*([\d.]+)", text)
    if m:
        rate = float(m.group(1))
        if 5 < rate < 1000 or (0.1 < rate < 2 and src == "JPY"):
            return rate
    # Fallback: first "= NNN.NN" that looks like a rate (conversion box)
    m = re.search(r"=\s*([\d]{2,4}\.\d{1,6})\s", text)
    if m:
        rate = float(m.group(1))
        if 5 < rate < 1000 or (0.1 < rate < 2 and src == "JPY"):
            return rate
    matches = re.findall(r"(\d{2,4}\.\d{1,6})\s*BDT", text)
    valid = [float(x) for x in matches if 5 < float(x) < 1000 or (0.1 < float(x) < 2 and src == "JPY")]
    # Use min: page can show both the 1-unit rate (~122) and a higher amount; we want the conversion rate
    return min(valid) if valid else None


async def _scrapling_ria_fetch(src: str) -> float | None:
    """Run Ria fetch in a thread; one at a time to avoid spawning many browsers."""
    global _ria_fetch_lock
    if _ria_fetch_lock is None:
        _ria_fetch_lock = asyncio.Lock()  # noqa: PLW0603
    async with _ria_fetch_lock:
        return await asyncio.to_thread(_scrapling_ria_fetch_sync, src)


class Ria(Provider):
    """Scrapes Ria Money Transfer rates-conversion page via Scrapling (stealth browser)."""

    name = "Ria"
    url = "https://www.riamoneytransfer.com/en-us/rates-conversion/?From=USD&To=BDT&Amount=1"
    delivery = "Bank, Cash Pickup, Mobile Wallet"

    _CURRENCIES: ClassVar[set[str]] = {
        "USD", "GBP", "EUR", "CAD", "AUD", "SGD", "AED", "SAR", "JPY",
    }

    async def fetch_rate(self, session, src):
        if src not in self._CURRENCIES:
            return None
        return await _scrapling_ria_fetch(src)

    def get_url(self, src):
        return (
            f"https://www.riamoneytransfer.com/en-us/rates-conversion/"
            f"?From={src}&To=BDT&Amount=1"
        )


def _scrapling_moneygram_fetch_sync() -> float | None:
    """Fetch MoneyGram USD->BDT rate via Scrapling (blocking). Returns rate or None."""
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return None
    StealthyFetcher.adaptive = True
    url = "https://www.moneygram.com/us/en/corridor/bangladesh"
    try:
        page = StealthyFetcher.fetch(url, headless=True, network_idle=True)
    except Exception:
        return None
    html = _scrapling_body_html(page)
    # Try __NEXT_DATA__ JSON first
    nd_match = re.search(r'<script id="__NEXT_DATA__"[^>]*>([^<]+)</script>', html)
    if nd_match:
        try:
            import json
            data = json.loads(nd_match.group(1))
            def find_rate(obj, seen=None):
                seen = seen or set()
                if id(obj) in seen:
                    return None
                if isinstance(obj, (int, float)) and 50 < obj < 200:
                    return float(obj)
                if isinstance(obj, str) and re.match(r"^\d+\.?\d*$", obj):
                    v = float(obj)
                    if 50 < v < 200:
                        return v
                if isinstance(obj, dict):
                    seen.add(id(obj))
                    for k, v in obj.items():
                        if "rate" in k.lower() and isinstance(v, (int, float)) and 50 < v < 200:
                            return float(v)
                        r = find_rate(v, seen)
                        if r is not None:
                            return r
                if isinstance(obj, list):
                    for item in obj:
                        r = find_rate(item, seen)
                        if r is not None:
                            return r
                return None
            rate = find_rate(data)
            if rate is not None:
                return rate
        except Exception:
            pass
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    matches = re.findall(r"(\d{2,4}\.\d{1,6})\s*BDT", text)
    valid = [float(x) for x in matches if 50 < float(x) < 200]
    return min(valid) if valid else None


def _scrapling_nsave_fetch_sync() -> float | None:
    """Fetch nsave USD->BDT rate via Scrapling DynamicFetcher (blocking). Returns rate or None."""
    try:
        from scrapling.fetchers import DynamicFetcher
    except ImportError:
        return None
    url = "https://www.nsave.com/calculator/usd-bdt"
    try:
        page = DynamicFetcher.fetch(url, headless=True, network_idle=True)
    except Exception:
        return None
    html = _scrapling_body_html(page)
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    # "1 USD = X BDT" or "X.XX BDT"
    m = re.search(r"1\s*USD\s*[=:]\s*([\d,.]+)\s*BDT", text, re.I)
    if m:
        rate = float(m.group(1).replace(",", ""))
        if 50 < rate < 200:
            return rate
    matches = re.findall(r"(\d{2,4}\.\d{1,6})\s*BDT", text)
    valid = [float(x) for x in matches if 50 < float(x) < 200]
    return min(valid) if valid else None


async def _scrapling_extra_fetch(sync_fn, *args):
    """Run a Scrapling fetch in a thread; reuse Ria lock so one browser at a time."""
    global _ria_fetch_lock
    if _ria_fetch_lock is None:
        _ria_fetch_lock = asyncio.Lock()  # noqa: PLW0603
    async with _ria_fetch_lock:
        return await asyncio.to_thread(sync_fn, *args)


class MoneyGram(Provider):
    """Scrapes MoneyGram corridor page via Scrapling (stealth browser). Best-effort."""

    name = "MoneyGram"
    url = "https://www.moneygram.com/us/en/corridor/bangladesh"
    delivery = "Bank, Cash Pickup, Mobile Wallet"

    async def fetch_rate(self, session, src):
        if src != "USD":
            return None
        return await _scrapling_extra_fetch(_scrapling_moneygram_fetch_sync)


class Nsave(Provider):
    """Scrapes nsave calculator via Scrapling DynamicFetcher. Best-effort."""

    name = "nsave"
    url = "https://www.nsave.com/calculator/usd-bdt"
    delivery = "Bank, Mobile Wallet"

    async def fetch_rate(self, session, src):
        if src != "USD":
            return None
        return await _scrapling_extra_fetch(_scrapling_nsave_fetch_sync)


# ── Runner ───────────────────────────────────────────────────────────────────


async def _fetch_one(
    session: aiohttp.ClientSession, provider: Provider, code: str
) -> tuple[str, Rate | None]:
    result = await provider.scrape(session, code)
    tag = f"✅ {result.provider}: {result.rate}" if result else f"❌ {provider.name}"
    print(f"  {code}: {tag}")
    return (code, result)


def _needs_browser(provider: Provider) -> bool:
    return isinstance(provider, (WesternUnion, WorldRemit, Xoom))


async def fetch_all() -> dict:
    now = datetime.now(timezone.utc).isoformat()
    data: dict[str, list[dict]] = {code: [] for code, *_ in CURRENCIES}

    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    conn = aiohttp.TCPConnector(ssl=ssl_ctx)
    async with aiohttp.ClientSession(headers=HEADERS, connector=conn) as session:
        http_tasks = [
            _fetch_one(session, provider, code)
            for code, *_ in CURRENCIES
            for provider in _providers
            if not _needs_browser(provider)
        ]
        browser_tasks = [
            _fetch_one(session, provider, code)
            for code, *_ in CURRENCIES
            for provider in _providers
            if _needs_browser(provider)
        ]
        # Pre-warm the browser while HTTP tasks run
        results = await asyncio.gather(
            _pool._start(),
            *http_tasks,
            *browser_tasks,
        )
        results = results[1:]  # drop _start() result

    await _pool.stop()

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

    lines.append("# Best remittance rate to Bangladesh?")
    lines.append("")
    lines.append("I compared Wise, Remitly, Ria, Western Union + 11 more and update it hourly.")
    lines.append("")
    lines.append(f"**Last updated:** `{updated}`")
    lines.append("")
    lines.append("## Why this exists")
    lines.append("")
    lines.append("Sending money to Bangladesh? Provider sites show one rate at a time."
                  " This repo **scrapes 14+ providers** (Wise, Remitly, Ria, Xe,"
                  " Western Union, WorldRemit, SendWave, Paysend, NALA, TapTapSend,"
                  " Instarem, Xoom, OrbitRemit, MoneyGram) and **ranks them by rate**"
                  " for each currency — so you can pick the best deal in seconds."
                  " Data is refreshed every hour via GitHub Actions. Use the tables"
                  " below or grab [`rates.json`](rates.json) for your own app.")
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
        has_fee = any(r.get("fee") is not None for r in rates)
        if has_fee:
            lines.append(f"| # | Provider | 1 {code} = BDT | Fee | Delivery |")
            lines.append("|--:|----------|---------------:|-----:|----------|")
        else:
            lines.append(f"| # | Provider | 1 {code} = BDT | Delivery |")
            lines.append("|--:|----------|---------------:|----------|")
        for i, r in enumerate(rates, 1):
            is_best = r["rate"] == best
            rank = f"**{i}**" if is_best else str(i)
            rate_str = f"**{r['rate']:.3f}**" if is_best else f"{r['rate']:.3f}"
            provider_str = f"[{r['provider']}]({r['url']})"
            if has_fee:
                fee_val = r.get("fee")
                fee_str = f"{fee_val:.2f} {code}" if fee_val is not None else "—"
                lines.append(f"| {rank} | {provider_str} | {rate_str} | {fee_str} | {r['delivery']} |")
            else:
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
    lines.append('      { "provider": "Wise", "rate": 122.200, "fee": null, ... },')
    lines.append('      { "provider": "SendWave", "rate": 121.569, "fee": 0.99, ... }')
    lines.append("    ],")
    lines.append("    ...")
    lines.append("  }")
    lines.append("}")
    lines.append("```")
    lines.append("")

    lines.append("## Disclaimer")
    lines.append("")
    lines.append("This project is independent and not affiliated with any"
                  " remittance provider. Rates and fees are scraped from publicly"
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
