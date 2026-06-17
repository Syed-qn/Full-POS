from typing import Protocol


class WeatherPort(Protocol):
    def is_delay_active(self) -> bool:
        """Return True if current weather conditions may delay delivery."""
        ...
