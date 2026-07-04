from functools import lru_cache
from typing import Literal

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
    llm_provider: str = "fake"  # fake | claude | deepseek | kimi
    # W1 parity gate: ClaudeConversationAgent is schema-parity-complete but gated
    # behind an explicit ops flag so a future regression can't silently ship a
    # non-compliant Claude action surface. Flip to True once the offline parity
    # contract test (W1 Task 5) passes in CI. Falls back to DeepSeek when False.
    claude_conversation_enabled: bool = False
    # E-11: Anthropic platform context management (beta clear_tool_uses).
    claude_context_management_enabled: bool = False
    claude_context_clear_trigger_tokens: int = 80_000
    claude_context_keep_tool_uses: int = 3
    claude_context_clear_at_least_tokens: int = 0
    # Which provider extracts dishes from uploaded menus (PDF/image/text).
    # "auto" = use Claude when an Anthropic key is set (it reads PDFs/images
    # natively so no dishes are missed), else fall back to llm_provider. The chat
    # provider (e.g. DeepSeek) can't ingest binaries, so PDFs need Claude.
    menu_extractor_provider: str = "auto"  # auto | claude | deepseek | fake
    anthropic_api_key: SecretStr = SecretStr("")
    claude_model: str = "claude-opus-4-8"
    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_model: str = "deepseek-chat"
    # Live-path resilience — stays on DeepSeek (Claude is NEVER used for conversation,
    # only for menu/image extraction). When the primary deepseek_model is slow or
    # errors on an inbound call (conversation agent, router, completion detector),
    # retry the same call against this faster/previous DeepSeek model. Empty = off.
    deepseek_fallback_model: str = ""  # e.g. "deepseek-chat"
    # Kimi (Moonshot AI) — OpenAI-compatible chat provider served through the same
    # adapter layer as DeepSeek (base https://api.moonshot.ai/v1). K2.6 constraints
    # that shape payloads: temperature/top_p are FIXED by the API (custom values
    # error), thinking mode restricts tool_choice to auto/none. Live path always
    # disables thinking (latency + the forced take_action tool call must work).
    kimi_api_key: SecretStr = SecretStr("")
    kimi_model: str = "kimi-k2.6"
    kimi_fallback_model: str = ""  # e.g. "kimi-k2-turbo-preview"
    # Seconds to wait on the primary model before cutting over to the fallback model.
    # Also caps a reasoning model's runaway think phase so one slow call can't stall a reply.
    llm_primary_timeout_s: float = 12.0
    upload_dir: str = "var/uploads"
    public_base_url: str = "http://localhost:8000"
    # Public download link for the Android rider app APK, included in the WhatsApp
    # pairing message. Leave empty to send just the code (no install link).
    rider_app_apk_url: str = ""
    # Push notifications to the native rider app. fake = record only (tests/dev);
    # expo = call the Expo Push API.
    push_provider: str = "fake"  # fake | expo

    # Speech-to-text for inbound WhatsApp voice notes. "fake" = deterministic stub
    # (tests/dev, NO real transcription — do not use in production). "elevenlabs" =
    # ElevenLabs Scribe API (needs a key + a paid plan for commercial use).
    stt_provider: str = "fake"  # fake | elevenlabs
    elevenlabs_api_key: SecretStr = SecretStr("")
    elevenlabs_stt_model: str = "scribe_v1"

    # WhatsApp
    whatsapp_provider: str = "mock"  # mock | cloud
    wa_verify_token: str = "dev-verify-token"
    wa_access_token: SecretStr = SecretStr("")
    wa_phone_number_id: str = ""
    wa_app_secret: SecretStr = SecretStr("")
    wa_business_account_id: str = ""  # WABA id for message-template management
    # System-user token with `catalog_management` permission, used ONLY to READ the
    # Meta Commerce catalog (GET /{catalog_id}/products) for the OPS "Sync from Meta"
    # feature. Separate from wa_access_token (the messaging token, which can't read
    # catalogs). Empty = catalog sync disabled.
    wa_catalog_token: SecretStr = SecretStr("")
    # Placeholder image for dishes pushed to Meta without a photo (items_batch
    # requires image_link). Must be a public JPEG/PNG URL, ≥500×500 px.
    catalog_placeholder_image_url: str = "https://placehold.co/500x500/png?text=Menu"
    # External POS integration (e.g. Cratis). Provider chosen by APP_POS_PROVIDER
    # (cratis | fake); per-restaurant account/location live in restaurant.settings.
    pos_provider: str = "cratis"
    pos_base_url: str = "https://online.cratis.live/hnc_test/pos/"
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
    # Restrict marketing sends to the UAE 09:00-18:00 telemarketing window
    # (Cabinet Decision 56/2024). OFF by default: WhatsApp template messaging is
    # treated as exempt and restaurants peak in the evening, so sends run any time.
    marketing_send_window_enabled: bool = False
    marketing_send_dry_run: bool = True  # safe default — no real Meta calls
    marketing_template_provider: str = "mock"  # mock | meta
    wa_app_id: str = ""  # Facebook App ID for resumable /uploads (template IMAGE header examples per research §5.1)
    # WhatsApp Embedded Signup: the tech-provider app's ES configuration id. Set
    # (with wa_app_id + wa_app_secret) to enable the "Connect with Facebook" popup on
    # onboarding — each restaurant connects its OWN WABA/number through this one app,
    # and we exchange the returned code for that restaurant's own token. Empty = the
    # popup is hidden and managers connect by pasting values manually.
    wa_es_config_id: str = ""
    graph_api_version: str = "v21.0"  # for graph base urls (no hardcode)
    marketing_ephemeral_delete_hour: int = 23  # Asia/Dubai EOD for ephemeral daily specials (spec §4.7)
    marketing_ephemeral_delete_minute: int = 30
    marketing_template_poll_minutes: int = 2  # poll pending_meta status interval
    # Shared secret guarding the public POST /api/v1/marketing/tick heartbeat that
    # drives the "Today's Special" auto-timed send. An external cron job sends it
    # as the X-Tick-Secret header. Empty (default) DISABLES the endpoint (503) so
    # it's never open. Generate a long random value and set it on the server + cron.
    marketing_tick_secret: SecretStr = SecretStr("")
    # Promo header image generation (Phase 5 — placeholder default, no paid APIs in CI).
    marketing_image_provider: Literal["placeholder", "openai"] = "placeholder"
    marketing_image_openai_model: str = "dall-e-3"
    marketing_image_max_per_day: int = 20
    openai_api_key: SecretStr = SecretStr("")

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
    # Run the dispatch sweep IN-PROCESS from the web app (lifespan background task),
    # not just via Celery beat. Needed on web-only deploys (e.g. Render) where no
    # Celery worker/beat runs — otherwise held/stuck orders are never re-dispatched.
    # Disabled in tests. Safe to leave on alongside Celery (dispatch is idempotent).
    dispatch_inprocess_sweep: bool = True
    # Dashboard batch-preview labels (orders list + detail). Cached per tenant so
    # list endpoints stay under the 400 ms budget on Render without skipping labels.
    batch_preview_cache_enabled: bool = True
    batch_preview_cache_ttl_seconds: int = 30
    # LLM conversation history window (in Message rows fetched before merge/render).
    # Kept at the pre-W7 default of 10 so the window itself doesn't change customer
    # behaviour — W7a only makes what's already in the window render faithfully
    # (R-080/F55). E-01: per-phase overrides below take precedence in _build_history.
    conversation_history_limit: int = 10
    conversation_history_limit_ordering: int = 10
    conversation_history_limit_post_order: int = 5
    conversation_history_limit_address: int = 8
    # Session freshness: if a customer returns after this many minutes of silence, the
    # LLM memory starts fresh from the new session — older turns (e.g. yesterday's chat)
    # are NOT fed to the model, so a stale request can't colour a brand-new order. The
    # draft cart has its own separate expiry (cart_expiry_minutes). 0 disables the cut.
    conversation_session_gap_minutes: int = 240

    # Vector KB over context.txt — inject retrieved prompt specs into the LLM system prompt.
    prompt_kb_enabled: bool = True
    prompt_kb_top_k: int = 3
    prompt_kb_max_chars: int = 2400

    # Wallet store credit + complaint-refund abuse controls.
    # Credit older than this with unspent balance is expired by the sweep. 0 = never.
    wallet_credit_ttl_days: int = 0
    # Per-customer refund velocity caps over a rolling window; breach auto-freezes
    # the wallet for manager review. 0 = disabled.
    wallet_refund_window_days: int = 30
    wallet_refund_max_count: int = 5
    wallet_refund_max_aed: float = 200.0

    # Rate limiting (redis token bucket)
    rate_limit_enabled: bool = True
    auth_rate_limit: str = "5/minute"
    webhook_rate_limit: str = "120/minute"
    partner_rate_limit: str = "60/minute"
    # POS partner (Cratis) auto-provisioning on Meta connect. Industry-standard single
    # webhook endpoint: one receiver URL + one shared signing secret for ALL stores;
    # each event's payload carries order_number / pos_store_id so the POS routes it.
    # When partner_webhook_url is set, connecting Meta auto-wires the store's webhook
    # (enabled + url + secret) and mints its per-restaurant API key. Blank = off.
    # Multi-partner registry (SINGLE source of truth for partner webhooks). A
    # restaurant is tagged with its partner slug at onboarding (?partner=<slug>).
    # NO tag = STANDALONE (no POS): the store uses our platform end-to-end — no
    # webhook, no partner key. Only tagged stores wire to a partner. Every partner
    # (including the majority one) lives in APP_PARTNERS JSON, e.g.
    #   {"cratis": {"name": "Cratis", "webhook_url": "https://...", "webhook_secret": "..."},
    #    "pos2":   {"name": "Acme POS", "webhook_url": "https://...", "webhook_secret": "..."}}
    # `default_partner` only supplies a slug when normalizing a blank value.
    # See app/partner/registry.py.
    default_partner: str = "cratis"
    partners_json: str = ""

    # CORS / security headers (P7-T13)
    cors_allow_origins: list[str] = []
    hsts_enabled: bool = False

    # Observability
    sentry_dsn: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
