from app.weather.port import WeatherPort

__all__ = ["FakeWeatherPort"]


class FakeWeatherPort:
    """Test/dev stub — configurable delay flag."""

    def __init__(self, delay_active: bool = False) -> None:
        self._delay_active = delay_active

    def is_delay_active(self) -> bool:
        return self._delay_active


# Static assertion: FakeWeatherPort structurally satisfies WeatherPort.
_: WeatherPort = FakeWeatherPort()
