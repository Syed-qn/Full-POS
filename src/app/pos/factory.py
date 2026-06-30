from functools import lru_cache

from app.config import get_settings
from app.pos.port import PosProvider


@lru_cache
def get_pos_provider() -> PosProvider:
    """Resolve the POS provider from ``APP_POS_PROVIDER`` (cratis | fake)."""
    provider = (get_settings().pos_provider or "cratis").lower()
    if provider == "cratis":
        from app.pos.cratis import CratisPosAdapter

        return CratisPosAdapter()
    if provider == "fake":
        from app.pos.port import FakePos

        return FakePos()
    raise ValueError(f"Unknown POS provider: {provider!r}")
