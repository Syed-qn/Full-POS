from dataclasses import dataclass
from typing import Protocol


@dataclass
class AddressSuggestion:
    """One geocoded address candidate for the manual-order type-ahead."""

    description: str   # human-readable address, e.g. "Marina Tower, Dubai Marina"
    latitude: float
    longitude: float


class GeoPort(Protocol):
    """Distance + ETA provider port.

    Implementations: FakeGeoProvider (haversine + static speed, tests/fallback)
    and GoogleMapsGeoProvider (production, traffic-aware with haversine fallback).
    """

    is_estimate: bool  # True = using haversine fallback (not road/traffic data)

    def distance_km(
        self,
        lat1: float,
        lon1: float,
        lat2: float,
        lon2: float,
    ) -> float:
        """Return distance between two points in km."""
        ...

    def eta_minutes(self, distance_km: float, buffer_minutes: int = 0) -> int:
        """Return ETA in whole minutes. buffer_minutes added after calculation."""
        ...

    def suggest(
        self,
        query: str,
        *,
        near: tuple[float, float] | None = None,
        limit: int = 5,
    ) -> list[AddressSuggestion]:
        """Return up to ``limit`` address candidates for ``query``, each with a
        human description and exact coordinates, biased toward ``near`` (the
        restaurant's location). Powers the manual-order address type-ahead so the
        manager picks a real place instead of relying on blind geocoding. Empty
        list on no match / any failure.
        """
        ...

    def geocode(self, address: str) -> tuple[float, float] | None:
        """Convert a free-text address to ``(lat, lng)``, or None if not found.

        FakeGeoProvider uses a small Dubai gazetteer (dev/tests);
        GoogleMapsGeoProvider calls the Geocoding API. The backend — never the
        LLM — uses the result to compute distance / fee / eligibility.
        """
        ...

    def reverse_geocode(self, lat: float, lng: float) -> str | None:
        """Convert ``(lat, lng)`` to a concise human area label, or None.

        e.g. ``(25.2489, 55.3061) -> "Al Karama, Dubai"``. Used to ground the
        bot's "where are you located?" answer in the restaurant's REAL saved
        coordinates instead of letting the LLM invent an area.
        FakeGeoProvider uses the Dubai gazetteer; GoogleMapsGeoProvider calls the
        Geocoding API reverse lookup.
        """
        ...
