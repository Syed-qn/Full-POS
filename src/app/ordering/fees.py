from decimal import Decimal

_DEFAULT_TIERS = [
    {"max_km": 3.0, "fee": "0.00"},
    {"max_km": 5.0, "fee": "5.00"},
    {"max_km": 10.0, "fee": "10.00"},
]
_MAX_RADIUS_KM = 10.0


class UndeliverableError(Exception):
    """Raised when distance exceeds the maximum delivery radius."""


def calculate_fee(distance_km: float, settings: dict | None = None) -> Decimal:
    """Return delivery fee in AED for the given distance.

    Args:
        distance_km: haversine distance from restaurant to delivery address.
        settings: optional dict with key ``"tiers"`` (list of {max_km, fee} dicts,
                  sorted ascending by max_km). Defaults to spec §1 tiers.

    Raises:
        UndeliverableError: distance > max tier max_km.
    """
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
