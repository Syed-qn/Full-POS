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
