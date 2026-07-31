"""HTTP-only providers: scrape rates via aiohttp without a browser."""
from __future__ import annotations

import re
from typing import ClassVar

import aiohttp
from bs4 import BeautifulSoup

from currency_rates.config import TARGET, TIMEOUT
from currency_rates.providers.base import Provider


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
            m = re.search(rf"1\s+{src}\s*=\s*([\d,.]+)\s*BDT", text, re.I)
            if m:
                rate = float(m.group(1).replace(",", ""))
                if 50 < rate < 200 or (0.1 < rate < 2 and src == "NZD"):
                    return rate
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
            valid = [float(x) for x in matches if 80 < float(x) < 95]
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
