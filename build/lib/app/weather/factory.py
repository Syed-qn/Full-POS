from app.weather.fake import FakeWeatherPort
from app.weather.port import WeatherPort


def get_weather_port() -> WeatherPort:
    """FastAPI dependency. Returns FakeWeatherPort for now; real implementation in Phase 4."""
    return FakeWeatherPort(delay_active=False)
