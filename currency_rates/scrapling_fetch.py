"""Scrapling sync functions and parse helpers.

Extracted from the original ``fetch_rates.py``. The sync functions take a
``cache: dict`` parameter and mutate it in place instead of referencing a
module-level global. Lazy ``scrapling.fetchers`` imports remain inside the
functions to avoid a hard dependency at import time.
"""
from __future__ import annotations

import json
import logging
import re

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


_RIA_VALID_RANGES = {
    "USD": (80, 150), "GBP": (140, 200), "EUR": (120, 170), "CAD": (75, 110),
    "AUD": (75, 110), "SGD": (85, 110), "AED": (25, 45), "MYR": (25, 40),
    "SAR": (28, 45), "KWD": (350, 450), "QAR": (28, 45), "JPY": (0.1, 2),
}


def _valid_ria_rate(rate: float, src: str) -> bool:
    """Rate must fall within plausible BDT-per-unit range for the source currency."""
    lo, hi = _RIA_VALID_RANGES.get(src, (5, 1000))
    return lo <= rate <= hi


def _parse_ria_from_html(html: str, src: str) -> float | None:
    """Parse Ria rate from HTML. Prefer JSON-LD, then explicit '1 SRC = RATE BDT', then table."""
    # 1. JSON-LD structured data (most reliable, always present in Ria pages)
    m = re.search(r'"price"\s*:\s*"([\d.]+)"\s*,?\s*"priceCurrency"\s*:\s*"BDT"', html)
    if m:
        rate = float(m.group(1))
        if _valid_ria_rate(rate, src):
            return rate

    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)

    # 2. "1.00 SRC = RATE BDT" (hero text with currency code)
    m = re.search(rf"1\.0*\s*{re.escape(src)}\s*=\s*([\d,.]+)\s*BDT", text, re.I)
    if m:
        rate = float(m.group(1).replace(",", ""))
        if _valid_ria_rate(rate, src):
            return rate

    # 3. Table row: "1 SRC RATE BDT" (no = sign, e.g. "1 USD123.48873 BDT")
    m = re.search(rf"1\s*{re.escape(src)}\s*([\d,.]+)\s*BDT", text, re.I)
    if m:
        rate = float(m.group(1).replace(",", ""))
        if _valid_ria_rate(rate, src):
            return rate

    # 4. Fallback: find standalone numbers (not fragments of larger comma-separated values)
    matches = re.findall(r"(?<![\d,])(\d{2,4}\.\d{1,6})\s*BDT", text)
    valid = [float(x) for x in matches if _valid_ria_rate(float(x), src)]
    return max(valid) if valid else None


def _scrapling_body(page) -> str:
    """Get HTML from Scrapling page (body may be bytes or str)."""
    body = page.body
    if isinstance(body, bytes):
        return body.decode(getattr(page, "encoding", None) or "utf-8")
    return body if isinstance(body, str) else ""


def _parse_moneygram_from_html(html: str) -> float | None:
    """Parse MoneyGram USD->BDT rate from HTML (__NEXT_DATA__ or BDT text)."""
    nd_match = re.search(r'<script id="__NEXT_DATA__"[^>]*>([^<]+)</script>', html)
    if nd_match:
        try:
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


def scrapling_stealthy_batch_sync(cache: dict) -> None:
    """One StealthySession: fetch all Ria + MoneyGram; fill ``cache``. Uses Playwright Chromium."""
    cache["Ria"] = {}
    cache["MoneyGram"] = None
    cache["Nsave"] = None
    try:
        from scrapling.fetchers import StealthySession
    except ImportError:
        return
    ria_currencies = {"USD", "GBP", "EUR", "CAD", "AUD", "SGD", "AED", "SAR", "JPY"}
    try:
        with StealthySession(headless=True, network_idle=False) as session:
            for src in ria_currencies:
                url = f"https://www.riamoneytransfer.com/en-us/rates-conversion/?From={src}&To=BDT&Amount=1"
                try:
                    page = session.fetch(url)
                    rate = _parse_ria_from_html(_scrapling_body(page), src)
                    if rate is not None:
                        cache["Ria"][src] = rate
                except Exception:
                    pass
            try:
                page = session.fetch("https://www.moneygram.com/us/en/corridor/bangladesh")
                cache["MoneyGram"] = _parse_moneygram_from_html(_scrapling_body(page))
            except Exception:
                pass
    except Exception:
        pass


def scrapling_nsave_sync(cache: dict) -> float | None:
    """Fetch nsave USD->BDT via Scrapling DynamicFetcher (best-effort)."""
    try:
        from scrapling.fetchers import DynamicFetcher
    except ImportError:
        return None
    try:
        page = DynamicFetcher.fetch("https://www.nsave.com/calculator/usd-bdt", headless=True, network_idle=False)
    except Exception:
        return None
    text = BeautifulSoup(_scrapling_body(page), "html.parser").get_text(" ", strip=True)
    m = re.search(r"1\s*USD\s*[=:]\s*([\d,.]+)\s*BDT", text, re.I)
    if m:
        rate = float(m.group(1).replace(",", ""))
        if 50 < rate < 200:
            return rate
    for x in re.findall(r"(\d{2,4}\.\d{1,6})\s*BDT", text):
        v = float(x)
        if 50 < v < 200:
            return v
    return None
