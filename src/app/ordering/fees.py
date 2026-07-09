from decimal import Decimal

# Canonical spec primitive lives in app.geo.fees (single source of truth for the
# fixed spec tiers + 10 km radius rejection). Re-exported here so callers that
# only need the spec default can import from either place without divergence.
from app.geo.fees import (  # noqa: F401
    MAX_RADIUS_KM,
    OutOfRadiusError,
    delivery_fee_aed,
)

_DEFAULT_TIERS = [
    {"max_km": 3.0, "fee": "0.00"},
    {"max_km": 5.0, "fee": "5.00"},
    {"max_km": 10.0, "fee": "10.00"},
]
_MAX_RADIUS_KM = 10.0


class UndeliverableError(Exception):
    """Raised when distance exceeds the maximum delivery radius."""


def fee_settings_from_restaurant(restaurant_settings: dict | None) -> dict | None:
    """Convert a restaurant's stored ``delivery_fee_tiers`` into the shape
    ``calculate_fee`` expects, so the fee + radius are driven by the manager's
    Ops settings rather than the hardcoded spec defaults.

    Stored shape:  [{"max_km": 3, "fee_aed": 0}, ...]
    calculate_fee: {"tiers": [{"max_km": 3.0, "fee": "0.00"}, ...]}

    The largest tier's ``max_km`` becomes the delivery radius. Returns ``None``
    (→ spec defaults) when the restaurant has no tiers configured or they are
    malformed, so a bad/empty config can never make checkout crash.
    """
    raw = (restaurant_settings or {}).get("delivery_fee_tiers")
    if not raw:
        return None
    tiers: list[dict] = []
    for t in raw:
        try:
            tiers.append(
                {"max_km": float(t["max_km"]), "fee": str(Decimal(str(t["fee_aed"])))}
            )
        except (KeyError, TypeError, ValueError, ArithmeticError):
            return None
    if not tiers:
        return None
    return {"tiers": tiers}


def radius_km(settings: dict | None) -> float:
    """The delivery radius in km = the largest tier's ``max_km``.

    Single source of truth so the deliverability gate, the customer-facing
    "maximum N km" messages, and the LLM context never diverge. ``settings`` is
    the ``calculate_fee`` shape ({"tiers": [...]}); ``None`` → spec defaults (10 km).
    """
    tiers = (settings or {}).get("tiers", _DEFAULT_TIERS)
    return max(t["max_km"] for t in tiers)


def _fmt_aed(fee_str: str) -> str:
    """Render a stored fee string as a clean integer/decimal (no 1E+1 sci-notation)."""
    return f"{Decimal(fee_str).normalize():f}"


def delivery_info_text(restaurant_settings: dict | None) -> str:
    """One short line stating the restaurant's REAL delivery fee tiers, for the
    conversation agent to recite verbatim.

    The AI must NEVER invent fee numbers — distance/fee/eligibility are backend
    decisions. This renders the manager's Ops tiers when configured, otherwise the
    spec defaults, so whatever the bot says about delivery cost is always true.

    Example (spec defaults):
        "Delivery: free within 3 km, AED 5 for 3-5 km, AED 10 for 5-10 km. "
        "We deliver up to 10 km."
    """
    settings = fee_settings_from_restaurant(restaurant_settings)
    tiers = (settings or {}).get("tiers") or _DEFAULT_TIERS
    tiers = sorted(tiers, key=lambda t: t["max_km"])

    parts: list[str] = []
    prev = 0.0
    for tier in tiers:
        max_km = tier["max_km"]
        fee = Decimal(tier["fee"])
        if fee == 0:
            parts.append(f"free within {max_km:g} km")
        else:
            parts.append(f"AED {_fmt_aed(tier['fee'])} for {prev:g}-{max_km:g} km")
        prev = max_km

    max_radius = max(t["max_km"] for t in tiers)
    return "Delivery: " + ", ".join(parts) + f". We deliver up to {max_radius:g} km."


def calculate_fee(
    distance_km: float,
    settings: dict | None = None,
    *,
    drop_lat: float | None = None,
    drop_lon: float | None = None,
    restaurant_settings: dict | None = None,
) -> Decimal:
    """Return delivery fee in AED for the given distance.

    Args:
        distance_km: haversine distance from restaurant to delivery address.
        settings: optional dict with key ``"tiers"`` (list of {max_km, fee} dicts,
                  sorted ascending by max_km). Defaults to spec §1 tiers.
        drop_lat/drop_lon + restaurant_settings: when provided, zone ``fee_aed``
            overrides distance tiers if the drop-off falls in a priced zone.

    Raises:
        UndeliverableError: distance > max tier max_km.
    """
    # Zone pricing (Category 7): first matching delivery_zone with fee_aed wins.
    if drop_lat is not None and drop_lon is not None:
        from app.geo.fees import zone_fee_aed

        zones = (restaurant_settings or {}).get("delivery_zones") or []
        zfee = zone_fee_aed(drop_lat, drop_lon, zones)
        if zfee is not None:
            return zfee

    tiers = (settings or {}).get("tiers", _DEFAULT_TIERS)
    max_radius = max(t["max_km"] for t in tiers)

    if distance_km > max_radius:
        raise UndeliverableError(
            f"Distance {distance_km:.2f} km exceeds maximum delivery radius "
            f"{max_radius:.1f} km."
        )

    for tier in sorted(tiers, key=lambda t: t["max_km"]):
        if distance_km <= tier["max_km"]:
            return Decimal(tier["fee"])

    raise UndeliverableError(f"No fee tier matched for {distance_km:.2f} km.")
