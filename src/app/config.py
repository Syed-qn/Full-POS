from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="APP_", extra="ignore")

    env: str = "dev"
    database_url: str = "postgresql+asyncpg://app:app@localhost:5433/restaurant"
    redis_url: str = "redis://localhost:6380/0"
    jwt_secret: SecretStr = SecretStr("dev-secret-change-me-0123456789abcdef")
    jwt_ttl_minutes: int = 60
    llm_provider: str = "fake"  # fake | claude
    anthropic_api_key: SecretStr = SecretStr("")
    claude_model: str = "claude-opus-4-8"
    upload_dir: str = "var/uploads"

    # WhatsApp
    whatsapp_provider: str = "mock"  # mock | cloud
    wa_verify_token: str = "dev-verify-token"
    wa_access_token: SecretStr = SecretStr("")
    wa_phone_number_id: str = ""
    wa_app_secret: SecretStr = SecretStr("")
    wa_business_account_id: str = ""  # WABA id for message-template management

    # Marketing
    marketing_send_dry_run: bool = True  # safe default — no real Meta calls
    marketing_template_provider: str = "mock"  # mock | meta

    # Geo
    geo_provider: str = "fake"  # fake | google_maps
    google_maps_api_key: SecretStr = SecretStr("")

    # Predictions
    forecast_provider: str = "rolling"  # rolling | fake

    # Rate limiting (redis token bucket)
    rate_limit_enabled: bool = True
    auth_rate_limit: str = "5/minute"
    webhook_rate_limit: str = "120/minute"

    # CORS / security headers (P7-T13)
    cors_allow_origins: list[str] = []
    hsts_enabled: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
