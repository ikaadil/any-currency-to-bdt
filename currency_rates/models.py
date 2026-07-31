"""Data models for fetched rates."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Rate:
    provider: str
    url: str
    rate: float
    delivery: str
    fee: float | None = None
