from __future__ import annotations

from .http_providers import (
    Wise,
    Remitly,
    TapTapSend,
    Nala,
    Instarem,
    Xe,
    OrbitRemit,
    SendWave,
    Paysend,
)
from .browser_providers import (
    WesternUnion,
    WorldRemit,
    Xoom,
)
from .scrapling_providers import (
    Ria,
    MoneyGram,
    Nsave,
)

PROVIDERS: list = [
    Wise(), Remitly(), TapTapSend(), Nala(), Instarem(), Xe(),
    OrbitRemit(), SendWave(), Paysend(),
    WesternUnion(), WorldRemit(), Xoom(),
    Ria(), MoneyGram(), Nsave(),
]
