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
import logging
import time

from currency_rates import (
    ROOT,
    CURRENCIES,
    PROVIDERS,
    Rate,
    TARGET,
    TIMEOUT,
    BrowserPool,
    Provider,
    build_readme,
    fetch_all,
)

__all__ = [
    "fetch_all",
    "CURRENCIES",
    "TARGET",
    "TIMEOUT",
    "ROOT",
    "Rate",
    "BrowserPool",
    "build_readme",
    "Provider",
    "PROVIDERS",
]

logger = logging.getLogger(__name__)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    json_path = ROOT / "rates.json"
    readme_path = ROOT / "README.md"

    start = time.monotonic()
    data = asyncio.run(fetch_all())
    elapsed = time.monotonic() - start

    json_path.write_text(
        json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8"
    )
    readme = build_readme(data)
    readme_path.write_text(readme, encoding="utf-8")

    total = sum(len(v) for v in data["rates"].values())
    logger.info("\n✅ %d rates fetched in %.1fs", total, elapsed)
