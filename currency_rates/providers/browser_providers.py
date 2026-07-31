"""Browser providers: scrape rates via Playwright (JS-rendered pages)."""
from __future__ import annotations

import asyncio
from typing import ClassVar

from currency_rates.providers.base import Provider


class WesternUnion(Provider):
    """Scrapes WU currency converter via Playwright (JS-rendered)."""

    name = "Western Union"
    url = "https://www.westernunion.com/us/en/currency-converter/usd-to-bdt-rate.html"
    delivery = "Bank, Cash Pickup, Mobile Wallet"

    uses_browser: ClassVar[bool] = True

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
        js = "() => { const m = document.body.innerText.match(/FX:\\s*1\\.00\\s*%s\\s*[–\\-]\\s*([\\d,]+\\.\\d+)\\s*BDT/); return m ? parseFloat(m[1].replace(/,/g,'')) : null; }" % src
        async with self._pool.page() as page:
            await page.goto(url, wait_until="domcontentloaded", timeout=8000)
            try:
                h = await page.wait_for_function(js, timeout=4000)
                return await h.json_value()
            except Exception:
                return None

    def get_url(self, src):
        region = self._REGIONS.get(src, "us")
        return (
            f"https://www.westernunion.com/{region}/en/"
            f"currency-converter/{src.lower()}-to-bdt-rate.html"
        )


class WorldRemit(Provider):
    """Scrapes WorldRemit send-money pages via Playwright (JS-rendered)."""

    name = "WorldRemit"
    url = "https://www.worldremit.com/en-us/bangladesh"
    delivery = "Bank, Mobile Wallet, Cash Pickup"

    uses_browser: ClassVar[bool] = True

    _REGIONS: ClassVar[dict[str, str]] = {
        "USD": "en-us", "GBP": "en-gb", "CAD": "en-ca", "AUD": "en-au",
    }

    async def fetch_rate(self, session, src):
        region = self._REGIONS.get(src)
        if not region:
            return None
        url = f"https://www.worldremit.com/{region}/bangladesh"
        js = "() => { const m = document.body.innerText.match(/1\\s*%s\\s*=\\s*([\\d,]+\\.\\d+)\\s*BDT/); return m ? parseFloat(m[1].replace(/,/g,'')) : null; }" % src
        async with self._pool.page() as page:
            await page.goto(url, wait_until="domcontentloaded", timeout=8000)
            try:
                h = await page.wait_for_function(js, timeout=4000)
                return await h.json_value()
            except Exception:
                return None

    def get_url(self, src):
        region = self._REGIONS.get(src, "en-us")
        return f"https://www.worldremit.com/{region}/bangladesh"


class Xoom(Provider):
    """Scrapes Xoom (PayPal) via Playwright; one page load, detect currency and rate."""

    name = "Xoom"
    url = "https://www.xoom.com/bangladesh/send-money"
    delivery = "Bank, Cash Pickup, Mobile Wallet"

    uses_browser: ClassVar[bool] = True

    _JS = "() => { const m = document.body.innerText.match(/1\\s+([A-Z]{3})\\s*=\\s*([\\d,]+\\.\\d+)\\s*BDT/); return m ? [m[1], parseFloat(m[2].replace(/,/g,''))] : null; }"

    def __init__(self):
        self._cache: dict[str, float] = {}
        self._loaded = False
        self._load_lock = asyncio.Lock()
        self._pool = None

    async def _load(self) -> None:
        if self._loaded:
            return
        async with self._load_lock:
            if self._loaded:
                return
            async with self._pool.page() as page:
                await page.goto(self.url, wait_until="domcontentloaded", timeout=8000)
                try:
                    h = await page.wait_for_function(self._JS, timeout=4000)
                    pair = await h.json_value()
                    if pair:
                        self._cache[pair[0]] = pair[1]
                except Exception:
                    pass
            self._loaded = True

    async def fetch_rate(self, session, src):
        await self._load()
        return self._cache.get(src)
