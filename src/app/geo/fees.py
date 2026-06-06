"""Canonical delivery-fee primitive (spec §1, CLAUDE.md non-negotiable rules).

Single source of truth for the fixed spec tiers + 10 km radius rejection.
``ordering/fees.py`` keeps its settings-driven ``calculate_fee`` (per-tenant
overridable tiers) but re-exports these primitives so there is exactly one
hardcoded spec-default implementation.
"""

from decimal import Decimal

MAX_RADIUS_KM = 10.0
_FREE_KM = 3.0
_MID_KM = 5.0
_MID_FEE = Decimal("5.00")
_FAR_FEE = Decimal("10.00")
_FREE_FEE = Decimal("0.00")


class OutOfRadiusError(ValueError):
    """Raised when a delivery distance exceeds the 10 km service radius."""


def delivery_fee_aed(distance_km: float) -> Decimal:
    """Return the COD delivery fee for a distance in km.

    Tiers (boundaries inclusive on the lower-fee side):
      <=3 km  -> free
      <=5 km  -> AED 5
      <=10 km -> AED 10
      >10 km  -> OutOfRadiusError
    """
    if distance_km <= _FREE_KM:
        return _FREE_FEE
    if distance_km <= _MID_KM:
        return _MID_FEE
    if distance_km <= MAX_RADIUS_KM:
        return _FAR_FEE
    raise OutOfRadiusError(
        f"Distance {distance_km:.2f} km exceeds {MAX_RADIUS_KM} km service radius"
    )
