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


def zone_fee_aed(
    lat: float,
    lon: float,
    zones: list[dict] | None,
    *,
    distance_km: float | None = None,
) -> Decimal | None:
    """If drop-off falls in a zone with ``fee_aed``, return that fee (zone pricing).

    Zones without fee_aed are ignored (still used for batching only).
    Returns None when no priced zone matches — caller falls back to distance tiers.
    """
    if not zones:
        return None
    from app.dispatch.zones import zone_for_point

    name = zone_for_point(lat, lon, zones)
    if name is None:
        return None
    for zone in zones:
        if zone.get("name") == name and zone.get("fee_aed") is not None:
            return Decimal(str(zone["fee_aed"])).quantize(Decimal("0.01"))
    return None


def resolve_delivery_fee(
    distance_km: float,
    *,
    drop_lat: float | None = None,
    drop_lon: float | None = None,
    restaurant_settings: dict | None = None,
) -> Decimal:
    """Prefer zone fee when configured; else distance tiers from settings/spec."""
    settings = restaurant_settings or {}
    zones = settings.get("delivery_zones") or []
    if drop_lat is not None and drop_lon is not None and zones:
        zfee = zone_fee_aed(drop_lat, drop_lon, zones, distance_km=distance_km)
        if zfee is not None:
            return zfee
    from app.ordering.fees import calculate_fee, fee_settings_from_restaurant

    fee_cfg = fee_settings_from_restaurant(settings)
    return calculate_fee(distance_km, fee_cfg)
