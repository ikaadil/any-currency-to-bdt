"""Scrapling providers: scrape rates via Scrapling (batch/stealth fetcher)."""
from __future__ import annotations

from typing import ClassVar

from currency_rates.providers.base import Provider


class Ria(Provider):
    """Scrapes Ria via Scrapling StealthyFetcher (batch)."""

    name = "Ria"
    url = "https://www.riamoneytransfer.com/en-us/rates-conversion/?From=USD&To=BDT&Amount=1"
    delivery = "Bank, Cash Pickup, Mobile Wallet"

    uses_scrapling: ClassVar[bool] = True

    _CURRENCIES: ClassVar[set[str]] = {
        "USD", "GBP", "EUR", "CAD", "AUD", "SGD", "AED", "SAR", "JPY",
    }

    def __init__(self):
        self._scrapling_cache = {}

    async def fetch_rate(self, session, src):
        if src not in self._CURRENCIES:
            return None
        return self._scrapling_cache.get("Ria", {}).get(src)

    def get_url(self, src):
        return (
            f"https://www.riamoneytransfer.com/en-us/rates-conversion/"
            f"?From={src}&To=BDT&Amount=1"
        )


class MoneyGram(Provider):
    """Scrapes MoneyGram via Scrapling StealthyFetcher (batch)."""

    name = "MoneyGram"
    url = "https://www.moneygram.com/us/en/corridor/bangladesh"
    delivery = "Bank, Cash Pickup, Mobile Wallet"

    uses_scrapling: ClassVar[bool] = True

    def __init__(self):
        self._scrapling_cache = {}

    async def fetch_rate(self, session, src):
        if src != "USD":
            return None
        return self._scrapling_cache.get("MoneyGram")


class Nsave(Provider):
    """Scrapes nsave via Scrapling DynamicFetcher (best-effort)."""

    name = "nsave"
    url = "https://www.nsave.com/calculator/usd-bdt"
    delivery = "Bank, Mobile Wallet"

    uses_scrapling: ClassVar[bool] = True

    def __init__(self):
        self._scrapling_cache = {}

    async def fetch_rate(self, session, src):
        if src != "USD":
            return None
        return self._scrapling_cache.get("Nsave")
