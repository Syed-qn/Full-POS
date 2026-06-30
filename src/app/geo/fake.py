import difflib
import math
import re

from app.geo.haversine import distance_km as _haversine

_CITY_SPEED_KMH = 25.0

# Small Dubai gazetteer for offline geocoding (dev + tests). Real production
# geocoding is GoogleMapsGeoProvider.geocode. Coordinates are approximate area
# centroids — good enough for the coarse fee tiers / 10 km radius. Keys are
# matched as substrings against the lowercased address; the LONGEST matching key
# wins (so "mall of the emirates" beats a bare "mall").
_DUBAI_AREAS: dict[str, tuple[float, float]] = {
    "business bay": (25.1850, 55.2650),
    "downtown": (25.1972, 55.2744),
    "burj khalifa": (25.1972, 55.2744),
    "difc": (25.2110, 55.2796),
    "al quoz": (25.1400, 55.2300),
    "karama": (25.2450, 55.3050),
    "bur dubai": (25.2600, 55.2960),
    "deira": (25.2700, 55.3100),
    "satwa": (25.2300, 55.2700),
    "jumeirah": (25.2048, 55.2600),
    "al barsha": (25.1130, 55.1960),
    "mall of the emirates": (25.1180, 55.2000),
    "mall of emirates": (25.1180, 55.2000),
    "dubai marina": (25.0805, 55.1403),
    "marina": (25.0805, 55.1403),
    "jlt": (25.0700, 55.1400),
    "jumeirah lake towers": (25.0700, 55.1400),
    "jebel ali": (25.0107, 55.1326),
    "international city": (25.1600, 55.4100),
    "silicon oasis": (25.1210, 55.3770),
}


class FakeGeoProvider:
    """Haversine-backed provider for tests and Maps-API-down fallback.

    Uses static city speed 25 km/h.  is_estimate = True always.
    """

    is_estimate: bool = True

    def distance_km(
        self,
        lat1: float,
        lon1: float,
        lat2: float,
        lon2: float,
    ) -> float:
        return _haversine(lat1, lon1, lat2, lon2)

    def eta_minutes(self, distance_km: float, buffer_minutes: int = 0) -> int:
        raw = (distance_km / _CITY_SPEED_KMH) * 60
        return max(1, math.ceil(raw)) + buffer_minutes

    def distance_matrix(
        self,
        origins: list[tuple[float, float]],
        destinations: list[tuple[float, float]],
    ) -> list[list[float]]:
        """Return travel minutes from each origin to each destination (haversine + static speed)."""
        matrix: list[list[float]] = []
        for olat, olon in origins:
            row: list[float] = []
            for dlat, dlon in destinations:
                d = self.distance_km(olat, olon, dlat, dlon)
                row.append(float(self.eta_minutes(d, buffer_minutes=0)))
            matrix.append(row)
        return matrix

    def suggest(self, query, *, near=None, limit=5):
        """Offline address candidates from the Dubai gazetteer (dev/tests).

        Returns gazetteer areas whose name appears in (or fuzzily matches) the
        query, as AddressSuggestion(description, lat, lng). Empty on no match.
        """
        from app.geo.port import AddressSuggestion

        coords = self.geocode(query or "")
        if coords is None:
            return []
        # Label it by the matched area name (reverse from coords for a clean title).
        label = self.reverse_geocode(coords[0], coords[1]) or (query or "").strip()
        return [AddressSuggestion(description=label, latitude=coords[0], longitude=coords[1])][:limit]

    def geocode(self, address: str) -> tuple[float, float] | None:
        """Resolve a known Dubai area name in the address to coordinates.

        Tries an exact substring match (longest key wins), then a typo-tolerant
        fuzzy pass so "Jabel ali" still resolves to "Jebel Ali". Returns None
        when no known area is recognised (caller then asks for a location pin).
        """
        if not address:
            return None
        text = address.lower()

        # 1) Exact substring — longest key wins ("mall of the emirates" > "mall").
        best_key: str | None = None
        for key in _DUBAI_AREAS:
            if key in text and (best_key is None or len(key) > len(best_key)):
                best_key = key
        if best_key:
            return _DUBAI_AREAS[best_key]

        # 2) Fuzzy fallback: a key matches if ALL its words appear in the address,
        #    allowing small typos on words of 4+ chars (short words must be exact,
        #    so "ali" stays precise while "jebel" tolerates "jabel").
        words = re.findall(r"[a-z]+", text)

        def _word_in(kw: str) -> bool:
            if len(kw) < 4:
                return kw in words
            return any(
                difflib.SequenceMatcher(None, kw, w).ratio() >= 0.8 for w in words
            )

        for key, coords in _DUBAI_AREAS.items():
            if all(_word_in(kw) for kw in key.split()):
                return coords
        return None

    def reverse_geocode(self, lat: float, lng: float) -> str | None:
        """Return the nearest known Dubai area as "Area, Dubai" (dev/tests).

        Picks the gazetteer centroid closest to the point, so it stays in sync
        with ``geocode`` and is fully deterministic for tests.
        """
        if not _DUBAI_AREAS:
            return None
        # Skip alias keys that share coords with a canonical one — pick the
        # first (canonical) key per coordinate to avoid e.g. "Marina" vs
        # "Dubai Marina" being chosen arbitrarily.
        seen: set[tuple[float, float]] = set()
        nearest_key: str | None = None
        nearest_d = float("inf")
        for key, coords in _DUBAI_AREAS.items():
            if coords in seen:
                continue
            seen.add(coords)
            d = _haversine(lat, lng, coords[0], coords[1])
            if d < nearest_d:
                nearest_d, nearest_key = d, key
        if nearest_key is None:
            return None
        return f"{nearest_key.title()}, Dubai"
