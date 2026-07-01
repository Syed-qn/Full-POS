# tests/conftest.py
import os

os.environ.setdefault("APP_DATABASE_URL", "postgresql+asyncpg://app:app@localhost:5433/restaurant_test")
os.environ.setdefault("APP_LLM_PROVIDER", "fake")  # never hit real AI APIs in tests
# Pin the WhatsApp provider for tests so they're deterministic regardless of the
# runtime .env (which may be set to "cloud" for live WhatsApp). The simulator
# router only mounts under "mock", and tests rely on it.
os.environ.setdefault("APP_WHATSAPP_PROVIDER", "mock")
# Pin geo to the offline provider so tests never make live Google Maps calls
# (the runtime .env may set google_maps + a real key). Tests that exercise the
# google_maps path override settings/get_geo_provider explicitly.
os.environ.setdefault("APP_GEO_PROVIDER", "fake")
# Pin push to the in-memory fake provider so rider-assignment tests inspect
# FakePushProvider.sent instead of hitting the real Expo push API (the runtime
# .env may set APP_PUSH_PROVIDER=expo for live devices).
os.environ.setdefault("APP_PUSH_PROVIDER", "fake")
# Pin speech-to-text to the in-memory FakeTranscriber so voice-note tests never
# call ElevenLabs (the runtime .env may set APP_STT_PROVIDER=elevenlabs + a key).
os.environ.setdefault("APP_STT_PROVIDER", "fake")
# Pin marketing to dry-run so template submit uses MockTemplateProvider (lint +
# auto-approve) instead of calling the real Meta Graph API — the runtime .env may
# enable live sending (APP_MARKETING_SEND_DRY_RUN=false / provider=meta).
os.environ.setdefault("APP_MARKETING_SEND_DRY_RUN", "true")
os.environ.setdefault("APP_MARKETING_TEMPLATE_PROVIDER", "mock")
# Never start the in-process dispatch sweep loop during tests — it would re-dispatch
# orders out from under tests on a timer. Production/dev leave it on (default True).
os.environ.setdefault("APP_DISPATCH_INPROCESS_SWEEP", "false")
# Disable lifespan-installed rate limiting by default — tests that exercise the
# limiter opt in via the ``rate_limiter`` fixture (isolated redis DB 9).
os.environ.setdefault("APP_RATE_LIMIT_ENABLED", "false")


import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db import Base
import app.audit.models  # noqa: F401
import app.identity.models  # noqa: F401
import app.menu.models  # noqa: F401
import app.webhook.models   # noqa: F401
import app.outbox.models    # noqa: F401
import app.conversation.models  # noqa: F401
import app.ordering.models  # noqa: F401
import app.dispatch.models  # noqa: F401
import app.sla.models  # noqa: F401
import app.coupons.models  # noqa: F401
import app.cod.models  # noqa: F401
import app.marketing.models  # noqa: F401
import app.predictions.models  # noqa: F401
import app.partner.models  # noqa: F401
import app.wallet.models  # noqa: F401
import app.tickets.models  # noqa: F401
import app.okf.models  # noqa: F401
import app.catalog.models  # noqa: F401


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """Clear the get_settings() lru_cache before AND after every test.

    Many tests monkeypatch APP_* env vars + cache_clear(); if one forgets to
    reset, the cached Settings (built with that env) leaks into later tests in
    the full run. Clearing around each test makes settings deterministic and
    eliminates cross-file test-isolation cascades.
    """
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="session")
async def engine():
    eng = create_async_engine(os.environ["APP_DATABASE_URL"])
    async with eng.begin() as conn:
        # pg_trgm is created by migrations in prod; schema here is built via
        # create_all, so install the extension for similarity()-based matching.
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db_session(engine):
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        yield session
        await session.close()
        await trans.rollback()


from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.db import get_session  # noqa: E402
from app.llm.factory import get_menu_extractor  # noqa: E402
from app.llm.fake import FakeExtractor  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture
async def client(engine, db_session):
    app = create_app()

    async def _override_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_menu_extractor] = lambda: FakeExtractor()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


import redis.asyncio as _redis  # noqa: E402

from app.ratelimit.bucket import TokenBucketLimiter  # noqa: E402
from app.ratelimit.deps import set_limiter  # noqa: E402

# Dedicated redis logical DB for tests so limiter keys never collide with dev.
_TEST_REDIS_URL = os.environ.get("APP_TEST_REDIS_URL", "redis://localhost:6380/9")


@pytest.fixture
async def redis_client():
    client = _redis.from_url(_TEST_REDIS_URL, decode_responses=False)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
async def rate_limiter(redis_client, monkeypatch):
    """Install a live token-bucket limiter for the app under test, isolated per
    test (redis/9 flushed before+after), and reset afterwards."""
    monkeypatch.setenv("APP_RATE_LIMIT_ENABLED", "true")
    from app.config import get_settings

    get_settings.cache_clear()
    limiter = TokenBucketLimiter(redis_client)
    set_limiter(limiter)
    yield limiter
    set_limiter(None)


@pytest.fixture
async def seed_biryani_menu(db_session, restaurant):
    """Seed the four dishes used by the biryani capability evals.

    Each dish is available via BOTH paths:
    - catalogue ORDER path  → matched by catalog_retailer_id
    - text / AI path        → matched by name / name_normalized

    CatalogProduct rows are required by handle_catalog_order's strict-membership
    check (dish + active CatalogProduct must both exist for the retailer_id).
    The restaurant settings are updated to enable catalogue ordering so the
    ORDER turn is routed to handle_catalog_order (matching production behaviour).
    """
    from decimal import Decimal

    from app.catalog.models import CatalogProduct
    from app.menu.models import Dish, Menu

    # Enable catalogue ordering on this restaurant so the ORDER message path works.
    restaurant.settings = {
        **(restaurant.settings or {}),
        "catalog_id": "TEST-CAT-001",
        "catalog_ordering_enabled": True,
    }
    await db_session.flush()

    menu = Menu(
        restaurant_id=restaurant.id,
        version=1,
        status="active",
        source_files=[],
    )
    db_session.add(menu)
    await db_session.flush()

    dishes = [
        Dish(
            menu_id=menu.id,
            restaurant_id=restaurant.id,
            dish_number=1,
            name="Chicken Biryani",
            price_aed=Decimal("20.00"),
            category="Biryani",
            is_available=True,
            name_normalized="chicken biryani",
            catalog_retailer_id="ju9f8jfy90",
        ),
        Dish(
            menu_id=menu.id,
            restaurant_id=restaurant.id,
            dish_number=2,
            name="Lemon Mint",
            price_aed=Decimal("12.00"),
            category="Drinks",
            is_available=True,
            name_normalized="lemon mint",
            catalog_retailer_id="dv5fh8l7j6",
        ),
        Dish(
            menu_id=menu.id,
            restaurant_id=restaurant.id,
            dish_number=3,
            name="Mndhi - 2",
            price_aed=Decimal("50.00"),
            category="Mandi",
            is_available=True,
            name_normalized="mndhi - 2",
            catalog_retailer_id="dish-8-6",
        ),
        Dish(
            menu_id=menu.id,
            restaurant_id=restaurant.id,
            dish_number=4,
            name="Mutton Biryani",
            price_aed=Decimal("10.00"),
            category="Biryani",
            is_available=True,
            name_normalized="mutton biryani",
            catalog_retailer_id="mutton-biryani-01",
        ),
    ]
    for d in dishes:
        db_session.add(d)

    catalog_products = [
        CatalogProduct(
            restaurant_id=restaurant.id,
            retailer_id="ju9f8jfy90",
            name="Chicken Biryani",
            price_aed=Decimal("20.00"),
            currency="AED",
            availability="in stock",
            category="Biryani",
            is_active=True,
            raw={},
        ),
        CatalogProduct(
            restaurant_id=restaurant.id,
            retailer_id="dv5fh8l7j6",
            name="Lemon Mint",
            price_aed=Decimal("12.00"),
            currency="AED",
            availability="in stock",
            category="Drinks",
            is_active=True,
            raw={},
        ),
        CatalogProduct(
            restaurant_id=restaurant.id,
            retailer_id="dish-8-6",
            name="Mndhi - 2",
            price_aed=Decimal("50.00"),
            currency="AED",
            availability="in stock",
            category="Mandi",
            is_active=True,
            raw={},
        ),
        CatalogProduct(
            restaurant_id=restaurant.id,
            retailer_id="mutton-biryani-01",
            name="Mutton Biryani",
            price_aed=Decimal("10.00"),
            currency="AED",
            availability="in stock",
            category="Biryani",
            is_active=True,
            raw={},
        ),
    ]
    for cp in catalog_products:
        db_session.add(cp)

    await db_session.flush()
    return dishes


@pytest.fixture
async def auth_headers(client):
    signup = {
        "name": "Biryani House", "phone": "+971501234567",
        "password": "hunter2!", "lat": 25.2048, "lng": 55.2708,
    }
    await client.post("/api/v1/auth/signup", json=signup)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"phone": "+971501234567", "password": "hunter2!"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}
