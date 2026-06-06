from app.weather.fake import FakeWeatherPort
from app.weather.port import WeatherPort


def test_fake_weather_port_default_no_delay():
    port = FakeWeatherPort(delay_active=False)
    assert port.is_delay_active() is False


def test_fake_weather_port_delay_active():
    port = FakeWeatherPort(delay_active=True)
    assert port.is_delay_active() is True


def test_fake_weather_port_satisfies_protocol():
    port: WeatherPort = FakeWeatherPort()
    assert callable(port.is_delay_active)
