"""Constants for the currency_rates package."""
from __future__ import annotations

from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parent.parent
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
