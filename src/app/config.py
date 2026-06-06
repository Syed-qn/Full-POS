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


@lru_cache
def get_settings() -> Settings:
    return Settings()
