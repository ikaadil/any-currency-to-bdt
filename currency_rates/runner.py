from __future__ import annotations

import asyncio
import logging
import ssl
from dataclasses import asdict
from datetime import datetime, timezone

import aiohttp
import certifi

from currency_rates.config import CURRENCIES, HEADERS, TARGET
from currency_rates.models import Rate
from currency_rates.browser_pool import BrowserPool
from currency_rates.scrapling_fetch import scrapling_stealthy_batch_sync, scrapling_nsave_sync
from currency_rates.providers import PROVIDERS
from currency_rates.providers.base import Provider

logger = logging.getLogger(__name__)


async def _fetch_one(
    session: aiohttp.ClientSession, provider: Provider, code: str
) -> tuple[str, Rate | None]:
    result = await provider.scrape(session, code)
    tag = f"✅ {result.provider}: {result.rate}" if result else f"❌ {provider.name}"
    logger.info(f"  {code}: {tag}")
    return (code, result)


async def fetch_all(providers: list[Provider] | None = None) -> dict:
    logger = logging.getLogger(__name__)
    now = datetime.now(timezone.utc).isoformat()
    data: dict[str, list[dict]] = {code: [] for code, *_ in CURRENCIES}

    if providers is None:
        providers = PROVIDERS

    # Create dependencies locally — NO module-level globals
    pool = BrowserPool()
    scrapling_cache: dict = {}

    # Wire dependencies into providers
    for p in providers:
        if p.uses_browser:
            p._pool = pool
        if p.uses_scrapling:
            p._scrapling_cache = scrapling_cache

    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    conn = aiohttp.TCPConnector(ssl=ssl_ctx)
    async with aiohttp.ClientSession(headers=HEADERS, connector=conn) as session:
        # Classify providers by dispatch type (using class attrs, NOT isinstance)
        http_tasks = [
            _fetch_one(session, p, code)
            for code, *_ in CURRENCIES
            for p in providers
            if not p.uses_browser and not p.uses_scrapling
        ]
        browser_tasks = [
            _fetch_one(session, p, code)
            for code, *_ in CURRENCIES
            for p in providers
            if p.uses_browser
        ]
        batch_task = asyncio.create_task(asyncio.to_thread(scrapling_stealthy_batch_sync, scrapling_cache))
        nsave_task = asyncio.create_task(
            asyncio.wait_for(asyncio.to_thread(scrapling_nsave_sync, scrapling_cache), timeout=14.0)
        )

        results = await asyncio.gather(
            pool._start(),
            *http_tasks,
            *browser_tasks,
            batch_task,
            nsave_task,
            return_exceptions=True,
        )
        n_main = 1 + len(http_tasks) + len(browser_tasks)
        main_results = results[:n_main]
        # nsave_result is the last item in results (check it's not an exception)
        last = results[-1]
        nsave_result = last if not isinstance(last, BaseException) else None

    await pool.stop()

    # Populate data from main_results (skip index 0 which is pool._start(), skip exceptions)
    for i, r in enumerate(main_results):
        if i == 0:
            continue
        if isinstance(r, BaseException):
            continue
        code, rate = r
        if rate:
            data[code].append(asdict(rate))

    # Write nsave result into cache (mirrors original: `if nsave_result is not None: _scrapling_cache["Nsave"] = nsave_result`)
    if nsave_result is not None:
        scrapling_cache["Nsave"] = nsave_result

    # Populate Ria rates from cache
    ria_p = next((p for p in providers if p.name == "Ria"), None)
    if ria_p:
        for src, rate in scrapling_cache.get("Ria", {}).items():
            data[src].append(asdict(Rate(ria_p.name, ria_p.get_url(src), round(rate, 3), ria_p.delivery, fee=None)))

    # Populate MoneyGram rate from cache
    mg_p = next((p for p in providers if p.name == "MoneyGram"), None)
    if mg_p and scrapling_cache.get("MoneyGram") is not None:
        r = scrapling_cache["MoneyGram"]
        data["USD"].append(asdict(Rate(mg_p.name, mg_p.get_url("USD"), round(r, 3), mg_p.delivery, fee=None)))

    # Populate Nsave rate from cache
    nsave_p = next((p for p in providers if p.name == "nsave"), None)
    if nsave_p and scrapling_cache.get("Nsave") is not None:
        r = scrapling_cache["Nsave"]
        data["USD"].append(asdict(Rate(nsave_p.name, nsave_p.get_url("USD"), round(r, 3), nsave_p.delivery, fee=None)))

    # Sort each currency's rates descending (best first)
    for code in data:
        data[code].sort(key=lambda r: r["rate"], reverse=True)

    return {"updated_at": now, "target": TARGET, "rates": data}
