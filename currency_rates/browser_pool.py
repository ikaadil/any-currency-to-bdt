"""BrowserPool: a single Chromium instance with serialised page usage."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from currency_rates.config import HEADERS


class BrowserPool:
    """Single Chromium instance; serialised page usage for WU, WorldRemit, Xoom."""

    def __init__(self, max_pages: int = 12):
        self._sem = asyncio.Semaphore(max_pages)
        self._pw = None
        self._browser = None
        self._context = None
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
                "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
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
        await self._start()
        async with self._sem:
            p = await self._context.new_page()
            def _block(route):
                req = route.request
                if req.resource_type in self._BLOCKED:
                    return True
                return any(d in req.url for d in self._BLOCKED_DOMAINS)
            await p.route("**/*", lambda route: route.abort() if _block(route) else route.continue_())
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
