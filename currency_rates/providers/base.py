from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import asdict
from typing import ClassVar

import aiohttp

from currency_rates.models import Rate

logger = logging.getLogger(__name__)


class Provider(ABC):
    """Base class for all rate providers.

    Subclasses must set three class attributes (``name``, ``url``,
    ``delivery``) and implement :meth:`fetch_rate`.  Everything else —
    error handling, ``Rate`` construction — is automatic.

    Override :meth:`get_url` if the provider URL varies per currency.
    """

    name: ClassVar[str]
    url: ClassVar[str]
    delivery: ClassVar[str]
    uses_browser: ClassVar[bool] = False
    uses_scrapling: ClassVar[bool] = False

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
            logger.error("  [%s] %s: %s", self.name, src, e)
            return None
