from pydantic import SecretStr

from app.config import Settings


def test_defaults_load_without_env_file():
    s = Settings(_env_file=None)
    assert s.env == "dev"
    assert s.database_url.startswith("postgresql+asyncpg://")
    assert s.llm_provider == "fake"
    assert s.jwt_ttl_minutes == 60


def test_env_prefix_overrides(monkeypatch):
    monkeypatch.setenv("APP_JWT_SECRET", "s3cret")
    s = Settings(_env_file=None)
    assert s.jwt_secret.get_secret_value() == "s3cret"


def test_whatsapp_settings_defaults():
    s = Settings(_env_file=None)
    assert s.whatsapp_provider == "mock"
    assert s.wa_verify_token == "dev-verify-token"
    assert isinstance(s.wa_access_token, SecretStr)
    assert isinstance(s.wa_app_secret, SecretStr)


def test_whatsapp_provider_env_override(monkeypatch):
    monkeypatch.setenv("APP_WHATSAPP_PROVIDER", "cloud")
    monkeypatch.setenv("APP_WA_ACCESS_TOKEN", "tok123")
    s = Settings(_env_file=None)
    assert s.whatsapp_provider == "cloud"
    assert s.wa_access_token.get_secret_value() == "tok123"
