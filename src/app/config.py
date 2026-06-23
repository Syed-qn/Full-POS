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
    jwt_issuer: str = "restaurant-platform"
    jwt_audience_manager: str = "manager"
    jwt_audience_rider: str = "rider"
    llm_provider: str = "fake"  # fake | claude | deepseek
    # Which provider extracts dishes from uploaded menus (PDF/image/text).
    # "auto" = use Claude when an Anthropic key is set (it reads PDFs/images
    # natively so no dishes are missed), else fall back to llm_provider. The chat
    # provider (e.g. DeepSeek) can't ingest binaries, so PDFs need Claude.
    menu_extractor_provider: str = "auto"  # auto | claude | deepseek | fake
    anthropic_api_key: SecretStr = SecretStr("")
    claude_model: str = "claude-opus-4-8"
    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_model: str = "deepseek-chat"
    upload_dir: str = "var/uploads"
    public_base_url: str = "http://localhost:8000"
    # Public download link for the Android rider app APK, included in the WhatsApp
    # pairing message. Leave empty to send just the code (no install link).
    rider_app_apk_url: str = ""
    # Push notifications to the native rider app. fake = record only (tests/dev);
    # expo = call the Expo Push API.
    push_provider: str = "fake"  # fake | expo

    # WhatsApp
    whatsapp_provider: str = "mock"  # mock | cloud
    wa_verify_token: str = "dev-verify-token"
    wa_access_token: SecretStr = SecretStr("")
    wa_phone_number_id: str = ""
    wa_app_secret: SecretStr = SecretStr("")
    wa_business_account_id: str = ""  # WABA id for message-template management
    # Rider assignment is a business-INITIATED message; outside WhatsApp's 24h
    # window only an approved template delivers. Set this to the approved template
    # name (e.g. "rider_assignment") to send assignments as a template; leave empty
    # to send a free-form interactive button (works only inside the 24h window).
    # The template MUST have body text {{1}} (order numbers) + one quick-reply
    # button (e.g. "Orders Picked"); the button payload carries picked:{batch_id}.
    wa_rider_assign_template: str = ""
    wa_rider_assign_template_lang: str = "en"
    # Deliver outbound replies synchronously inside the webhook request instead of
    # via the Celery outbox worker. Lets a single web service run the full WhatsApp
    # flow with NO worker/Redis (e.g. a free Render web service). Trade-off: the
    # webhook holds the connection until the reply is sent (~1-2s extra).
    outbox_sync_delivery: bool = False

    # Marketing
    marketing_send_dry_run: bool = True  # safe default — no real Meta calls
    marketing_template_provider: str = "mock"  # mock | meta
    wa_app_id: str = ""  # Facebook App ID for resumable /uploads (template IMAGE header examples per research §5.1)
    graph_api_version: str = "v21.0"  # for graph base urls (no hardcode)
    marketing_ephemeral_delete_hour: int = 23  # Asia/Dubai EOD for ephemeral daily specials (spec §4.7)
    marketing_ephemeral_delete_minute: int = 30
    marketing_template_poll_minutes: int = 2  # poll pending_meta status interval
    # Shared secret guarding the public POST /api/v1/marketing/tick heartbeat that
    # drives the "Today's Special" auto-timed send. An external cron job sends it
    # as the X-Tick-Secret header. Empty (default) DISABLES the endpoint (503) so
    # it's never open. Generate a long random value and set it on the server + cron.
    marketing_tick_secret: SecretStr = SecretStr("")

    # Geo
    geo_provider: str = "fake"  # fake | google_maps
    google_maps_api_key: SecretStr = SecretStr("")
    # Geocode cache (address -> lat/lng) in Redis; positive results, 30-day TTL.
    geocode_cache_enabled: bool = True
    geocode_cache_ttl_seconds: int = 2_592_000  # 30 days

    # Geo / dispatch fallbacks (used by haversine eta in geo/fake + batch inter-stop calc)
    geo_city_speed_kmh: float = 25.0  # spec §5 graceful: haversine + static 25km/h city

    # Predictions
    forecast_provider: str = "rolling"  # rolling | fake | lightgbm (stub/note per GAP#5)
    # Weekly retrain (spec §4.6 "manager-configurable day/time, default Mon 04:00"; GAP_LIST #5; producer beat uses these, NO hardcode in celery_app or worker)
    predictions_weekly_retrain_dow: int = 0  # 0=Mon ... 6=Sun for crontab day_of_week
    predictions_weekly_retrain_hour: int = 4
    predictions_weekly_retrain_minute: int = 0

    # SLA / batching (spec §1 hard rules, §4.3 dispatch engine + batching; GAP_LIST #4; NO hardcode in src)
    # customer-facing 40min, internal target 30min, +10min buffer per additional batched order
    sla_customer_minutes: int = 40
    sla_internal_target_minutes: int = 30
    sla_buffer_per_order_minutes: int = 10
    # When true, restaurants still on greedy ALSO run the OR-Tools optimizer in shadow
    # (no writes) so we can log what it WOULD do vs greedy before flipping the flag.
    dispatch_shadow_compare: bool = False
    # Periodic dispatch sweep cadence (seconds): re-runs dispatch for every restaurant
    # with ready+unassigned orders, so held (batch-window) orders are released once
    # they mature and stuck no-rider orders keep retrying without a new ready event.
    dispatch_sweep_seconds: float = 30.0

    # Rate limiting (redis token bucket)
    rate_limit_enabled: bool = True
    auth_rate_limit: str = "5/minute"
    webhook_rate_limit: str = "120/minute"

    # CORS / security headers (P7-T13)
    cors_allow_origins: list[str] = []
    hsts_enabled: bool = False

    # Observability
    sentry_dsn: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
