# Phase 0+1: Foundation, Identity & AI Menu — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Working multi-tenant backend skeleton: restaurant signup/login, AI menu upload → extraction → manager confirm/edit → versioned activation with price-diff on re-upload, rider registration, delivery settings — fully tested.

**Architecture:** FastAPI modular monolith (`src/app/<module>`), async SQLAlchemy 2 + PostgreSQL, Celery skeleton for later phases, LLM behind a port (`FakeExtractor` for tests/dev, `ClaudeExtractor` for production). Audit log primitive from day 0. Restaurant row doubles as the manager account in this phase (single-login per restaurant; separate `manager_users` arrives when multi-user is needed — YAGNI). Location stored as lat/lng floats; PostGIS columns arrive in the logistics phase where geo queries actually start.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2 + pydantic-settings, SQLAlchemy 2 (asyncpg), Alembic, Celery + Redis, passlib[argon2], PyJWT, anthropic SDK, pytest + pytest-asyncio + httpx.

**Spec:** `docs/superpowers/specs/2026-06-06-whatsapp-restaurant-platform-design.md`

---

## File structure (locked in)

```
pyproject.toml                      deps + tooling config
docker-compose.yml                  postgres:16 (port 5433), redis:7 (port 6380)
.env.example                        all APP_* vars documented
alembic.ini  alembic/               migrations
src/app/
  __init__.py
  config.py                         Settings (pydantic-settings), get_settings()
  db.py                             engine, session factory, Base, TimestampMixin, get_session
  main.py                           create_app() factory, router mounting, /health
  audit/__init__.py  models.py  service.py     AuditLog table + record_audit()
  identity/__init__.py  models.py  auth.py  router.py  deps.py  schemas.py
  menu/__init__.py  models.py  service.py  diff.py  router.py  schemas.py
  llm/__init__.py  port.py  fake.py  claude.py  factory.py
apps/workers/__init__.py  celery_app.py
tests/
  conftest.py                       engine/session/client fixtures, FakeExtractor override
  test_config.py  test_audit.py  test_health.py
  identity/test_auth.py  identity/test_signup_login.py  identity/test_riders.py
  menu/test_upload.py  menu/test_edit.py  menu/test_activate.py  menu/test_diff.py
  llm/test_fake.py  llm/test_claude.py
```

Responsibilities: `service.py` = business logic, `router.py` = HTTP only, `schemas.py` = Pydantic I/O models, `models.py` = SQLAlchemy tables. Routers never touch other modules' models directly — they call services.

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`, `src/app/__init__.py`, `apps/workers/__init__.py`, `tests/__init__.py`, `.gitignore`, `.env.example`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "restaurant-platform"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pydantic>=2.8",
    "pydantic-settings>=2.4",
    "sqlalchemy[asyncio]>=2.0.30",
    "asyncpg>=0.29",
    "alembic>=1.13",
    "celery[redis]>=5.4",
    "redis>=5.0",
    "passlib[argon2]>=1.7.4",
    "pyjwt>=2.9",
    "anthropic>=0.40",
    "python-multipart>=0.0.9",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2",
    "pytest-asyncio>=0.23",
    "httpx>=0.27",
    "ruff>=0.5",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
src = ["src", "apps", "tests"]

[tool.setuptools.packages.find]
where = ["src"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"
```

- [ ] **Step 2: Write `.gitignore`**

```
.venv/
__pycache__/
*.pyc
.env
var/
.pytest_cache/
.ruff_cache/
dist/
```

- [ ] **Step 3: Write `.env.example`**

```
APP_ENV=dev
APP_DATABASE_URL=postgresql+asyncpg://app:app@localhost:5433/restaurant
APP_REDIS_URL=redis://localhost:6380/0
APP_JWT_SECRET=change-me-in-prod
APP_LLM_PROVIDER=fake
APP_ANTHROPIC_API_KEY=
APP_UPLOAD_DIR=var/uploads
```

- [ ] **Step 4: Create empty packages**

```bash
mkdir -p src/app apps/workers tests
touch src/app/__init__.py apps/workers/__init__.py tests/__init__.py
```

- [ ] **Step 5: Create venv, install, verify**

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -c "import fastapi, sqlalchemy, celery, anthropic; print('ok')"
```
Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore .env.example src apps tests
git commit -m "chore: scaffold project skeleton and dependencies"
```

---

### Task 2: Settings

**Files:**
- Create: `src/app/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
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
    assert s.jwt_secret == "s3cret"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.config'`

- [ ] **Step 3: Write implementation**

```python
# src/app/config.py
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="APP_", extra="ignore")

    env: str = "dev"
    database_url: str = "postgresql+asyncpg://app:app@localhost:5433/restaurant"
    redis_url: str = "redis://localhost:6380/0"
    jwt_secret: str = "dev-secret-change-me"
    jwt_ttl_minutes: int = 60
    llm_provider: str = "fake"  # fake | claude
    anthropic_api_key: str = ""
    claude_model: str = "claude-opus-4-8"
    upload_dir: str = "var/uploads"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/config.py tests/test_config.py
git commit -m "feat: typed settings with APP_ env prefix"
```

---

### Task 3: docker-compose + database layer

**Files:**
- Create: `docker-compose.yml`, `src/app/db.py`
- Test: `tests/conftest.py` (first version)

- [ ] **Step 1: Write `docker-compose.yml`**

```yaml
services:
  db:
    image: postgis/postgis:16-3.4
    environment:
      POSTGRES_USER: app
      POSTGRES_PASSWORD: app
      POSTGRES_DB: restaurant
    ports: ["5433:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d restaurant"]
      interval: 3s
      retries: 20
  redis:
    image: redis:7-alpine
    ports: ["6380:6379"]
```

(PostGIS image now so logistics phase needs no image swap; extension unused until then.)

- [ ] **Step 2: Start services**

```bash
docker compose up -d && docker compose ps
```
Expected: `db` healthy, `redis` running. Also create the test database:
```bash
docker compose exec db psql -U app -d restaurant -c "CREATE DATABASE restaurant_test;"
```

- [ ] **Step 3: Write `src/app/db.py`**

```python
# src/app/db.py
from collections.abc import AsyncIterator
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import get_settings


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )


engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session
```

- [ ] **Step 4: Write `tests/conftest.py` (first version)**

```python
# tests/conftest.py
import os

os.environ["APP_DATABASE_URL"] = (
    "postgresql+asyncpg://app:app@localhost:5433/restaurant_test"
)

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base


@pytest.fixture
async def engine():
    eng = create_async_engine(os.environ["APP_DATABASE_URL"])
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db_session(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
```

- [ ] **Step 5: Smoke-verify connection**

```bash
.venv/bin/python - <<'EOF'
import asyncio
from sqlalchemy import text
from app.db import engine
async def main():
    async with engine.connect() as c:
        print((await c.execute(text("select 1"))).scalar())
asyncio.run(main())
EOF
```
Expected: `1`

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml src/app/db.py tests/conftest.py
git commit -m "feat: database layer, docker services, test fixtures"
```

---

### Task 4: Audit log primitive

**Files:**
- Create: `src/app/audit/__init__.py`, `src/app/audit/models.py`, `src/app/audit/service.py`
- Test: `tests/test_audit.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_audit.py
from sqlalchemy import select

from app.audit.models import AuditLog
from app.audit.service import record_audit


async def test_record_audit_persists_row(db_session):
    await record_audit(
        db_session,
        actor="system",
        entity="order",
        entity_id="42",
        action="status_change",
        before={"status": "ready"},
        after={"status": "assigned"},
    )
    await db_session.commit()
    row = (await db_session.execute(select(AuditLog))).scalar_one()
    assert row.entity == "order"
    assert row.before == {"status": "ready"}
    assert row.after == {"status": "assigned"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_audit.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/app/audit/models.py
from sqlalchemy import BigInteger, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    actor: Mapped[str] = mapped_column(String(64))
    restaurant_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    entity: Mapped[str] = mapped_column(String(64), index=True)
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(128))
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
```

```python
# src/app/audit/service.py
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog


async def record_audit(
    session: AsyncSession,
    *,
    actor: str,
    entity: str,
    entity_id: str,
    action: str,
    restaurant_id: int | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> AuditLog:
    row = AuditLog(
        actor=actor,
        restaurant_id=restaurant_id,
        entity=entity,
        entity_id=entity_id,
        action=action,
        before=before,
        after=after,
    )
    session.add(row)
    return row
```

```python
# src/app/audit/__init__.py
from app.audit.service import record_audit  # noqa: F401
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_audit.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/audit tests/test_audit.py
git commit -m "feat: append-only audit log primitive"
```

---

### Task 5: FastAPI app factory + /health

**Files:**
- Create: `src/app/main.py`
- Test: `tests/test_health.py`, modify `tests/conftest.py` (add client fixture)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_health.py
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 2: Add client fixture to `tests/conftest.py`**

```python
# append to tests/conftest.py
from httpx import ASGITransport, AsyncClient

from app.db import get_session
from app.main import create_app


@pytest.fixture
async def client(engine, db_session):
    app = create_app()

    async def _override_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_health.py -v`
Expected: FAIL with `ImportError: cannot import name 'create_app'`

- [ ] **Step 4: Write implementation**

```python
# src/app/main.py
from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="Restaurant WhatsApp Platform")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_health.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/app/main.py tests/conftest.py tests/test_health.py
git commit -m "feat: app factory with health endpoint"
```

---

### Task 6: Alembic + Celery skeletons

**Files:**
- Create: `alembic.ini`, `alembic/env.py`, `alembic/versions/`, `apps/workers/celery_app.py`

- [ ] **Step 1: Init alembic**

```bash
.venv/bin/alembic init alembic
```

- [ ] **Step 2: Wire async engine + metadata in `alembic/env.py`** (replace generated file)

```python
# alembic/env.py
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.db import Base
import app.audit.models  # noqa: F401  (register tables; later tasks append imports)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online():
    asyncio.run(run_async_migrations())


run_migrations_online()
```

- [ ] **Step 3: Generate + apply initial migration**

```bash
.venv/bin/alembic revision --autogenerate -m "audit_log"
.venv/bin/alembic upgrade head
```
Expected: `audit_log` table created in `restaurant` DB. Verify:
```bash
docker compose exec db psql -U app -d restaurant -c "\dt"
```

- [ ] **Step 4: Write `apps/workers/celery_app.py`**

```python
# apps/workers/celery_app.py
from celery import Celery

from app.config import get_settings

settings = get_settings()
celery_app = Celery(
    "restaurant",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(task_default_queue="default", timezone="Asia/Dubai")
```

- [ ] **Step 5: Verify worker boots**

```bash
.venv/bin/celery -A apps.workers.celery_app:celery_app worker --loglevel=info --pool=solo &
sleep 5 && kill %1
```
Expected: banner shows `default` queue, connects to redis, no traceback.

- [ ] **Step 6: Commit**

```bash
git add alembic.ini alembic apps/workers/celery_app.py
git commit -m "feat: alembic migrations and celery skeleton"
```

---

### Task 7: Identity models

**Files:**
- Create: `src/app/identity/__init__.py`, `src/app/identity/models.py`
- Modify: `alembic/env.py` (add import), `tests/conftest.py` (add import)

- [ ] **Step 1: Write implementation** (models are exercised by Task 8–10 tests; no standalone behavior to test)

```python
# src/app/identity/models.py
from sqlalchemy import BigInteger, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin

DEFAULT_SETTINGS: dict = {
    "max_orders_per_batch": 3,
    "max_items_per_order": 20,
    "delivery_fee_tiers": [
        {"max_km": 3, "fee_aed": 0},
        {"max_km": 5, "fee_aed": 5},
        {"max_km": 10, "fee_aed": 10},
    ],
    "max_radius_km": 10,
}


class Restaurant(Base, TimestampMixin):
    __tablename__ = "restaurants"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    settings: Mapped[dict] = mapped_column(JSONB, default=lambda: dict(DEFAULT_SETTINGS))


class Rider(Base, TimestampMixin):
    __tablename__ = "riders"
    __table_args__ = (UniqueConstraint("restaurant_id", "phone"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="available")
    # available | on_delivery | off_shift | deactivated
```

```python
# src/app/identity/__init__.py
```

- [ ] **Step 2: Register models** — add to `alembic/env.py` after the audit import:

```python
import app.identity.models  # noqa: F401
```

Add same import line near the top of `tests/conftest.py` (after `from app.db import Base`):

```python
import app.audit.models  # noqa: F401
import app.identity.models  # noqa: F401
```

- [ ] **Step 3: Generate + apply migration**

```bash
.venv/bin/alembic revision --autogenerate -m "restaurants_riders"
.venv/bin/alembic upgrade head
```
Expected: tables `restaurants`, `riders` exist.

- [ ] **Step 4: Commit**

```bash
git add src/app/identity alembic/versions tests/conftest.py alembic/env.py
git commit -m "feat: restaurant and rider models"
```

---

### Task 8: Auth service (argon2 + JWT)

**Files:**
- Create: `src/app/identity/auth.py`
- Test: `tests/identity/test_auth.py` (create `tests/identity/__init__.py`)

- [ ] **Step 1: Write the failing test**

```python
# tests/identity/test_auth.py
import pytest

from app.identity.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip():
    h = hash_password("hunter2!")
    assert h != "hunter2!"
    assert verify_password("hunter2!", h)
    assert not verify_password("wrong", h)


def test_jwt_roundtrip():
    token = create_access_token(restaurant_id=7)
    assert decode_access_token(token) == 7


def test_jwt_garbage_rejected():
    with pytest.raises(ValueError):
        decode_access_token("not.a.token")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/identity/test_auth.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/app/identity/auth.py
from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from app.config import get_settings

_pwd = CryptContext(schemes=["argon2"], deprecated="auto")
_ALGO = "HS256"


def hash_password(plain: str) -> str:
    return _pwd.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd.verify(plain, hashed)


def create_access_token(restaurant_id: int) -> str:
    s = get_settings()
    payload = {
        "sub": str(restaurant_id),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=s.jwt_ttl_minutes),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=_ALGO)


def decode_access_token(token: str) -> int:
    s = get_settings()
    try:
        payload = jwt.decode(token, s.jwt_secret, algorithms=[_ALGO])
    except jwt.PyJWTError as exc:
        raise ValueError("invalid token") from exc
    return int(payload["sub"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/identity/test_auth.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/identity/auth.py tests/identity
git commit -m "feat: argon2 password hashing and JWT auth"
```

---

### Task 9: Signup + login endpoints, tenant dependency

**Files:**
- Create: `src/app/identity/schemas.py`, `src/app/identity/router.py`, `src/app/identity/deps.py`
- Modify: `src/app/main.py`
- Test: `tests/identity/test_signup_login.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/identity/test_signup_login.py
SIGNUP = {
    "name": "Biryani House",
    "phone": "+971501234567",
    "password": "hunter2!",
    "lat": 25.2048,
    "lng": 55.2708,
}


async def test_signup_creates_restaurant_with_default_settings(client):
    resp = await client.post("/api/v1/auth/signup", json=SIGNUP)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Biryani House"
    assert body["settings"]["max_radius_km"] == 10
    assert "password" not in body and "password_hash" not in body


async def test_signup_duplicate_phone_409(client):
    await client.post("/api/v1/auth/signup", json=SIGNUP)
    resp = await client.post("/api/v1/auth/signup", json=SIGNUP)
    assert resp.status_code == 409


async def test_login_returns_token_and_me_works(client):
    await client.post("/api/v1/auth/signup", json=SIGNUP)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"phone": "+971501234567", "password": "hunter2!"},
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]

    me = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["name"] == "Biryani House"


async def test_login_wrong_password_401(client):
    await client.post("/api/v1/auth/signup", json=SIGNUP)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"phone": "+971501234567", "password": "nope"},
    )
    assert resp.status_code == 401


async def test_me_without_token_401(client):
    resp = await client.get("/api/v1/me")
    assert resp.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/identity/test_signup_login.py -v`
Expected: FAIL — 404s (routes missing)

- [ ] **Step 3: Write schemas**

```python
# src/app/identity/schemas.py
from pydantic import BaseModel, ConfigDict, Field


class SignupIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: str = Field(min_length=7, max_length=32)
    password: str = Field(min_length=8)
    lat: float
    lng: float


class LoginIn(BaseModel):
    phone: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RestaurantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone: str
    lat: float
    lng: float
    settings: dict
```

- [ ] **Step 4: Write tenant dependency**

```python
# src/app/identity/deps.py
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.auth import decode_access_token
from app.identity.models import Restaurant

_bearer = HTTPBearer(auto_error=False)


async def current_restaurant(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> Restaurant:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing token")
    try:
        restaurant_id = decode_access_token(creds.credentials)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
    restaurant = await session.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown restaurant")
    return restaurant
```

- [ ] **Step 5: Write router**

```python
# src/app/identity/router.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.db import get_session
from app.identity.auth import create_access_token, hash_password, verify_password
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.identity.schemas import LoginIn, RestaurantOut, SignupIn, TokenOut

router = APIRouter(prefix="/api/v1", tags=["identity"])


@router.post("/auth/signup", response_model=RestaurantOut, status_code=201)
async def signup(body: SignupIn, session: AsyncSession = Depends(get_session)):
    existing = await session.scalar(
        select(Restaurant).where(Restaurant.phone == body.phone)
    )
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "phone already registered")
    restaurant = Restaurant(
        name=body.name,
        phone=body.phone,
        password_hash=hash_password(body.password),
        lat=body.lat,
        lng=body.lng,
    )
    session.add(restaurant)
    await session.flush()
    await record_audit(
        session,
        actor="manager",
        restaurant_id=restaurant.id,
        entity="restaurant",
        entity_id=str(restaurant.id),
        action="signup",
        after={"name": body.name, "phone": body.phone},
    )
    await session.commit()
    return restaurant


@router.post("/auth/login", response_model=TokenOut)
async def login(body: LoginIn, session: AsyncSession = Depends(get_session)):
    restaurant = await session.scalar(
        select(Restaurant).where(Restaurant.phone == body.phone)
    )
    if restaurant is None or not verify_password(body.password, restaurant.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad credentials")
    return TokenOut(access_token=create_access_token(restaurant.id))


@router.get("/me", response_model=RestaurantOut)
async def me(restaurant: Restaurant = Depends(current_restaurant)):
    return restaurant
```

- [ ] **Step 6: Mount router in `src/app/main.py`**

```python
# src/app/main.py
from fastapi import FastAPI

from app.identity.router import router as identity_router


def create_app() -> FastAPI:
    app = FastAPI(title="Restaurant WhatsApp Platform")
    app.include_router(identity_router)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
```

- [ ] **Step 7: Run tests**

Run: `.venv/bin/pytest tests/identity -v`
Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add src/app/identity src/app/main.py tests/identity
git commit -m "feat: restaurant signup, login, authenticated /me"
```

---

### Task 10: LLM extractor port + Fake

**Files:**
- Create: `src/app/llm/__init__.py`, `src/app/llm/port.py`, `src/app/llm/fake.py`, `src/app/llm/factory.py`
- Test: `tests/llm/test_fake.py` (create `tests/llm/__init__.py`)

- [ ] **Step 1: Write the failing test**

```python
# tests/llm/test_fake.py
from app.llm.fake import FakeExtractor
from app.llm.port import DishDraft, UploadedFile


async def test_fake_extractor_returns_drafts():
    fake = FakeExtractor()
    files = [UploadedFile(filename="menu.jpg", content=b"\xff\xd8", mime="image/jpeg")]
    drafts = await fake.extract_menu(files)
    assert len(drafts) >= 2
    assert all(isinstance(d, DishDraft) for d in drafts)
    assert drafts[0].dish_number == 110
    assert drafts[0].name == "Chicken Biryani"


async def test_fake_extractor_canned_override():
    canned = [DishDraft(dish_number=1, name="Tea", price_aed="2.00")]
    fake = FakeExtractor(canned=canned)
    drafts = await fake.extract_menu([])
    assert drafts == canned
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/llm/test_fake.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/app/llm/port.py
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel


@dataclass
class UploadedFile:
    filename: str
    content: bytes
    mime: str


class DishDraft(BaseModel):
    dish_number: int | None = None
    name: str
    price_aed: Decimal | None = None
    category: str | None = None
    description: str | None = None


class MenuExtractor(Protocol):
    async def extract_menu(self, files: list[UploadedFile]) -> list[DishDraft]: ...
```

```python
# src/app/llm/fake.py
from app.llm.port import DishDraft, UploadedFile

_DEFAULT = [
    DishDraft(
        dish_number=110, name="Chicken Biryani", price_aed="22.00",
        category="Rice", description="Fragrant basmati rice with spiced chicken",
    ),
    DishDraft(
        dish_number=111, name="Special Chicken Biryani", price_aed="28.00",
        category="Rice", description="Premium cut chicken, saffron rice",
    ),
    DishDraft(
        dish_number=201, name="Mutton Karahi", price_aed="35.00",
        category="Curries", description=None,
    ),
]


class FakeExtractor:
    def __init__(self, canned: list[DishDraft] | None = None):
        self._canned = canned

    async def extract_menu(self, files: list[UploadedFile]) -> list[DishDraft]:
        return list(self._canned) if self._canned is not None else list(_DEFAULT)
```

```python
# src/app/llm/factory.py
from app.config import get_settings
from app.llm.fake import FakeExtractor
from app.llm.port import MenuExtractor


def get_menu_extractor() -> MenuExtractor:
    settings = get_settings()
    if settings.llm_provider == "claude":
        from app.llm.claude import ClaudeExtractor

        return ClaudeExtractor()
    return FakeExtractor()
```

```python
# src/app/llm/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/llm/test_fake.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/llm tests/llm
git commit -m "feat: menu extractor port with fake provider"
```

---

### Task 11: ClaudeExtractor (vision)

**Files:**
- Create: `src/app/llm/claude.py`
- Test: `tests/llm/test_claude.py`

- [ ] **Step 1: Write the failing test** (mocks the anthropic client — no network)

```python
# tests/llm/test_claude.py
import json
from unittest.mock import AsyncMock, MagicMock

from app.llm.claude import ClaudeExtractor
from app.llm.port import UploadedFile

RAW = {
    "dishes": [
        {"dish_number": 110, "name": "Chicken Biryani", "price_aed": "22.00",
         "category": "Rice", "description": "Spiced rice"},
        {"dish_number": None, "name": "Mystery Dish", "price_aed": None,
         "category": None, "description": None},
    ]
}


async def test_claude_extractor_parses_tool_response():
    block = MagicMock()
    block.type = "tool_use"
    block.input = RAW
    response = MagicMock()
    response.content = [block]

    extractor = ClaudeExtractor()
    extractor._client = MagicMock()
    extractor._client.messages.create = AsyncMock(return_value=response)

    files = [UploadedFile(filename="m.jpg", content=b"\xff\xd8\xff", mime="image/jpeg")]
    drafts = await extractor.extract_menu(files)

    assert len(drafts) == 2
    assert drafts[0].dish_number == 110
    assert str(drafts[0].price_aed) == "22.00"
    assert drafts[1].dish_number is None  # flagged for manual entry downstream

    call = extractor._client.messages.create.call_args
    sent = json.dumps(call.kwargs)
    assert "base64" in sent  # image attached
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/llm/test_claude.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/app/llm/claude.py
import base64

from anthropic import AsyncAnthropic

from app.config import get_settings
from app.llm.port import DishDraft, UploadedFile

_TOOL = {
    "name": "submit_menu",
    "description": "Submit every dish extracted from the menu images/PDF.",
    "input_schema": {
        "type": "object",
        "properties": {
            "dishes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "dish_number": {"type": ["integer", "null"]},
                        "name": {"type": "string"},
                        "price_aed": {"type": ["string", "null"]},
                        "category": {"type": ["string", "null"]},
                        "description": {"type": ["string", "null"]},
                    },
                    "required": ["name"],
                },
            }
        },
        "required": ["dishes"],
    },
}

_PROMPT = (
    "Extract EVERY dish from this restaurant menu. For each dish capture: "
    "dish_number (the printed item number — null ONLY if truly absent), name, "
    "price_aed as a decimal string, category (menu section heading), and "
    "description if printed. Do not invent dishes, numbers, or prices. "
    "Preserve original spelling of names."
)


class ClaudeExtractor:
    def __init__(self) -> None:
        settings = get_settings()
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.claude_model

    async def extract_menu(self, files: list[UploadedFile]) -> list[DishDraft]:
        content: list[dict] = []
        for f in files:
            if f.mime == "application/pdf":
                content.append({
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": base64.b64encode(f.content).decode(),
                    },
                })
            else:
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": f.mime,
                        "data": base64.b64encode(f.content).decode(),
                    },
                })
        content.append({"type": "text", "text": _PROMPT})

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=8192,
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "submit_menu"},
            messages=[{"role": "user", "content": content}],
        )
        for block in response.content:
            if block.type == "tool_use":
                return [DishDraft(**d) for d in block.input["dishes"]]
        raise RuntimeError("Claude returned no tool_use block")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/llm/test_claude.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/llm/claude.py tests/llm/test_claude.py
git commit -m "feat: Claude vision menu extractor with forced tool output"
```

---

### Task 12: Menu models

**Files:**
- Create: `src/app/menu/__init__.py`, `src/app/menu/models.py`
- Modify: `alembic/env.py`, `tests/conftest.py` (imports)

- [ ] **Step 1: Write implementation**

```python
# src/app/menu/models.py
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TimestampMixin


class Menu(Base, TimestampMixin):
    __tablename__ = "menus"
    __table_args__ = (UniqueConstraint("restaurant_id", "version"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="pending_confirmation")
    # pending_confirmation | active | superseded
    source_files: Mapped[list] = mapped_column(JSONB, default=list)

    dishes: Mapped[list["Dish"]] = relationship(
        back_populates="menu", cascade="all, delete-orphan", lazy="selectin"
    )


class Dish(Base, TimestampMixin):
    __tablename__ = "dishes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    menu_id: Mapped[int] = mapped_column(ForeignKey("menus.id"), index=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    dish_number: Mapped[int | None] = mapped_column(Integer)  # null = extraction gap, must fix before activate
    name: Mapped[str] = mapped_column(String(255))
    price_aed: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    category: Mapped[str | None] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(String(2000))
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
```

```python
# src/app/menu/__init__.py
```

- [ ] **Step 2: Register imports** — append to `alembic/env.py` and `tests/conftest.py` import block:

```python
import app.menu.models  # noqa: F401
```

- [ ] **Step 3: Generate + apply migration**

```bash
.venv/bin/alembic revision --autogenerate -m "menus_dishes"
.venv/bin/alembic upgrade head
```
Expected: `menus`, `dishes` tables exist.

- [ ] **Step 4: Commit**

```bash
git add src/app/menu alembic/versions alembic/env.py tests/conftest.py
git commit -m "feat: menu and dish models with versioning"
```

---

### Task 13: Menu upload endpoint (extraction → drafts)

**Files:**
- Create: `src/app/menu/schemas.py`, `src/app/menu/service.py`, `src/app/menu/router.py`
- Modify: `src/app/main.py`, `tests/conftest.py`
- Test: `tests/menu/test_upload.py` (create `tests/menu/__init__.py`)

- [ ] **Step 1: Add extractor override + auth helper to `tests/conftest.py`**

```python
# append to tests/conftest.py
from app.llm.factory import get_menu_extractor
from app.llm.fake import FakeExtractor


@pytest.fixture
async def client(engine, db_session):  # replaces previous client fixture
    app = create_app()

    async def _override_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_menu_extractor] = lambda: FakeExtractor()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


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
```

(`get_menu_extractor` must be used as a FastAPI dependency in the router for this override to work — Step 4 does that.)

- [ ] **Step 2: Write the failing test**

```python
# tests/menu/test_upload.py
async def test_upload_menu_returns_drafts(client, auth_headers):
    files = [("files", ("menu.jpg", b"\xff\xd8\xff fake", "image/jpeg"))]
    resp = await client.post("/api/v1/menus", files=files, headers=auth_headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "pending_confirmation"
    assert body["version"] == 1
    numbers = [d["dish_number"] for d in body["dishes"]]
    assert 110 in numbers and 111 in numbers


async def test_upload_requires_auth(client):
    files = [("files", ("menu.jpg", b"x", "image/jpeg"))]
    resp = await client.post("/api/v1/menus", files=files)
    assert resp.status_code == 401


async def test_second_upload_increments_version(client, auth_headers):
    files = [("files", ("menu.jpg", b"\xff\xd8", "image/jpeg"))]
    await client.post("/api/v1/menus", files=files, headers=auth_headers)
    resp = await client.post("/api/v1/menus", files=files, headers=auth_headers)
    assert resp.json()["version"] == 2
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/menu/test_upload.py -v`
Expected: FAIL — 404 (route missing)

- [ ] **Step 4: Write schemas, service, router**

```python
# src/app/menu/schemas.py
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class DishOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dish_number: int | None
    name: str
    price_aed: Decimal | None
    category: str | None
    description: str | None
    is_available: bool


class MenuOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version: int
    status: str
    dishes: list[DishOut]


class DishIn(BaseModel):
    dish_number: int
    name: str
    price_aed: Decimal
    category: str | None = None
    description: str | None = None


class DishPatch(BaseModel):
    dish_number: int | None = None
    name: str | None = None
    price_aed: Decimal | None = None
    category: str | None = None
    description: str | None = None
```

```python
# src/app/menu/service.py
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.llm.port import DishDraft, MenuExtractor, UploadedFile
from app.menu.models import Dish, Menu


async def next_version(session: AsyncSession, restaurant_id: int) -> int:
    current = await session.scalar(
        select(func.max(Menu.version)).where(Menu.restaurant_id == restaurant_id)
    )
    return (current or 0) + 1


async def create_menu_from_upload(
    session: AsyncSession,
    *,
    restaurant_id: int,
    files: list[UploadedFile],
    extractor: MenuExtractor,
) -> Menu:
    drafts: list[DishDraft] = await extractor.extract_menu(files)
    menu = Menu(
        restaurant_id=restaurant_id,
        version=await next_version(session, restaurant_id),
        status="pending_confirmation",
        source_files=[{"filename": f.filename, "mime": f.mime} for f in files],
    )
    session.add(menu)
    await session.flush()
    for d in drafts:
        session.add(
            Dish(
                menu_id=menu.id,
                restaurant_id=restaurant_id,
                dish_number=d.dish_number,
                name=d.name,
                price_aed=d.price_aed,
                category=d.category,
                description=d.description,
            )
        )
    await record_audit(
        session,
        actor="manager",
        restaurant_id=restaurant_id,
        entity="menu",
        entity_id=str(menu.id),
        action="uploaded",
        after={"version": menu.version, "dish_count": len(drafts)},
    )
    await session.commit()
    await session.refresh(menu)
    return menu


async def get_active_menu(session: AsyncSession, restaurant_id: int) -> Menu | None:
    return await session.scalar(
        select(Menu).where(Menu.restaurant_id == restaurant_id, Menu.status == "active")
    )
```

```python
# src/app/menu/router.py
from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.llm.factory import get_menu_extractor
from app.llm.port import MenuExtractor, UploadedFile
from app.menu import service
from app.menu.models import Menu
from app.menu.schemas import MenuOut

router = APIRouter(prefix="/api/v1", tags=["menu"])


async def _load_menu(
    menu_id: int,
    restaurant: Restaurant,
    session: AsyncSession,
) -> Menu:
    menu = await session.get(Menu, menu_id)
    if menu is None or menu.restaurant_id != restaurant.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "menu not found")
    return menu


@router.post("/menus", response_model=MenuOut, status_code=201)
async def upload_menu(
    files: list[UploadFile],
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
    extractor: MenuExtractor = Depends(get_menu_extractor),
):
    uploaded = [
        UploadedFile(
            filename=f.filename or "file",
            content=await f.read(),
            mime=f.content_type or "application/octet-stream",
        )
        for f in files
    ]
    return await service.create_menu_from_upload(
        session, restaurant_id=restaurant.id, files=uploaded, extractor=extractor
    )


@router.get("/menus/{menu_id}", response_model=MenuOut)
async def get_menu(
    menu_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await _load_menu(menu_id, restaurant, session)
```

- [ ] **Step 5: Mount in `src/app/main.py`** — add:

```python
from app.menu.router import router as menu_router
# inside create_app(), after identity_router:
    app.include_router(menu_router)
```

- [ ] **Step 6: Run tests**

Run: `.venv/bin/pytest tests/menu/test_upload.py -v`
Expected: 3 PASS

- [ ] **Step 7: Commit**

```bash
git add src/app/menu src/app/main.py tests/menu tests/conftest.py
git commit -m "feat: menu upload with AI extraction to draft dishes"
```

---

### Task 14: Manager edit endpoints (add / patch / delete dish)

**Files:**
- Modify: `src/app/menu/router.py`
- Test: `tests/menu/test_edit.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/menu/test_edit.py
async def _upload(client, auth_headers):
    files = [("files", ("menu.jpg", b"\xff\xd8", "image/jpeg"))]
    resp = await client.post("/api/v1/menus", files=files, headers=auth_headers)
    return resp.json()


async def test_add_dish(client, auth_headers):
    menu = await _upload(client, auth_headers)
    resp = await client.post(
        f"/api/v1/menus/{menu['id']}/dishes",
        json={"dish_number": 301, "name": "Falooda", "price_aed": "12.00",
              "category": "Desserts"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["dish_number"] == 301


async def test_patch_dish_price_and_name(client, auth_headers):
    menu = await _upload(client, auth_headers)
    dish = menu["dishes"][0]
    resp = await client.patch(
        f"/api/v1/menus/{menu['id']}/dishes/{dish['id']}",
        json={"price_aed": "24.00", "name": "Chicken Biryani (Large)"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["price_aed"] == "24.00"
    assert resp.json()["name"] == "Chicken Biryani (Large)"


async def test_delete_dish(client, auth_headers):
    menu = await _upload(client, auth_headers)
    dish = menu["dishes"][0]
    resp = await client.delete(
        f"/api/v1/menus/{menu['id']}/dishes/{dish['id']}", headers=auth_headers
    )
    assert resp.status_code == 204
    menu_after = (
        await client.get(f"/api/v1/menus/{menu['id']}", headers=auth_headers)
    ).json()
    assert dish["id"] not in [d["id"] for d in menu_after["dishes"]]


async def test_duplicate_dish_number_409(client, auth_headers):
    menu = await _upload(client, auth_headers)
    resp = await client.post(
        f"/api/v1/menus/{menu['id']}/dishes",
        json={"dish_number": 110, "name": "Clone", "price_aed": "9.00"},
        headers=auth_headers,
    )
    assert resp.status_code == 409
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/menu/test_edit.py -v`
Expected: FAIL — 404/405

- [ ] **Step 3: Add endpoints to `src/app/menu/router.py`**

```python
# append to src/app/menu/router.py
from sqlalchemy import select

from app.audit import record_audit
from app.menu.models import Dish
from app.menu.schemas import DishIn, DishOut, DishPatch


@router.post("/menus/{menu_id}/dishes", response_model=DishOut, status_code=201)
async def add_dish(
    menu_id: int,
    body: DishIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    menu = await _load_menu(menu_id, restaurant, session)
    dup = await session.scalar(
        select(Dish).where(Dish.menu_id == menu.id, Dish.dish_number == body.dish_number)
    )
    if dup:
        raise HTTPException(status.HTTP_409_CONFLICT, "dish number already in menu")
    dish = Dish(menu_id=menu.id, restaurant_id=restaurant.id, **body.model_dump())
    session.add(dish)
    await record_audit(
        session, actor="manager", restaurant_id=restaurant.id, entity="dish",
        entity_id="new", action="added", after=body.model_dump(mode="json"),
    )
    await session.commit()
    await session.refresh(dish)
    return dish


@router.patch("/menus/{menu_id}/dishes/{dish_id}", response_model=DishOut)
async def patch_dish(
    menu_id: int,
    dish_id: int,
    body: DishPatch,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    menu = await _load_menu(menu_id, restaurant, session)
    dish = await session.get(Dish, dish_id)
    if dish is None or dish.menu_id != menu.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dish not found")
    changes = body.model_dump(exclude_unset=True)
    if "dish_number" in changes:
        dup = await session.scalar(
            select(Dish).where(
                Dish.menu_id == menu.id,
                Dish.dish_number == changes["dish_number"],
                Dish.id != dish.id,
            )
        )
        if dup:
            raise HTTPException(status.HTTP_409_CONFLICT, "dish number already in menu")
    before = {k: str(getattr(dish, k)) for k in changes}
    for key, value in changes.items():
        setattr(dish, key, value)
    await record_audit(
        session, actor="manager", restaurant_id=restaurant.id, entity="dish",
        entity_id=str(dish.id), action="edited", before=before,
        after={k: str(v) for k, v in changes.items()},
    )
    await session.commit()
    await session.refresh(dish)
    return dish


@router.delete("/menus/{menu_id}/dishes/{dish_id}", status_code=204)
async def delete_dish(
    menu_id: int,
    dish_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    menu = await _load_menu(menu_id, restaurant, session)
    dish = await session.get(Dish, dish_id)
    if dish is None or dish.menu_id != menu.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dish not found")
    await record_audit(
        session, actor="manager", restaurant_id=restaurant.id, entity="dish",
        entity_id=str(dish.id), action="removed",
        before={"dish_number": dish.dish_number, "name": dish.name},
    )
    await session.delete(dish)
    await session.commit()
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/menu/test_edit.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/menu/router.py tests/menu/test_edit.py
git commit -m "feat: manager dish add/edit/delete with audit trail"
```

---

### Task 15: Menu activation

**Files:**
- Modify: `src/app/menu/service.py`, `src/app/menu/router.py`
- Test: `tests/menu/test_activate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/menu/test_activate.py
async def _upload(client, auth_headers):
    files = [("files", ("menu.jpg", b"\xff\xd8", "image/jpeg"))]
    return (await client.post("/api/v1/menus", files=files, headers=auth_headers)).json()


async def test_activate_menu(client, auth_headers):
    menu = await _upload(client, auth_headers)
    resp = await client.post(
        f"/api/v1/menus/{menu['id']}/activate", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"


async def test_activate_supersedes_previous(client, auth_headers):
    m1 = await _upload(client, auth_headers)
    await client.post(f"/api/v1/menus/{m1['id']}/activate", headers=auth_headers)
    m2 = await _upload(client, auth_headers)
    await client.post(f"/api/v1/menus/{m2['id']}/activate", headers=auth_headers)

    m1_after = (
        await client.get(f"/api/v1/menus/{m1['id']}", headers=auth_headers)
    ).json()
    assert m1_after["status"] == "superseded"


async def test_activate_blocked_when_dish_missing_number(client, auth_headers):
    menu = await _upload(client, auth_headers)
    dish = menu["dishes"][0]
    # simulate extraction gap: null the number via direct patch is disallowed by schema,
    # so add a dish without number through the service path is impossible —
    # instead upload with canned fake that includes a null number
    # (covered in service-level test below)


async def test_activate_blocked_when_missing_price(client, auth_headers, db_session):
    from app.menu.models import Dish, Menu

    menu = await _upload(client, auth_headers)
    # null a price directly in DB to simulate extraction gap
    dish_id = menu["dishes"][0]["id"]
    dish = await db_session.get(Dish, dish_id)
    dish.price_aed = None
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/menus/{menu['id']}/activate", headers=auth_headers
    )
    assert resp.status_code == 422
    assert "price" in resp.json()["detail"].lower() or "incomplete" in resp.json()["detail"].lower()
```

Delete the empty `test_activate_blocked_when_dish_missing_number` stub before committing — the price test covers the incomplete-dish gate, and number-gaps go through the same gate (single validation: every dish needs number AND price).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/menu/test_activate.py -v`
Expected: FAIL — 404

- [ ] **Step 3: Add to `src/app/menu/service.py`**

```python
# append to src/app/menu/service.py
class MenuIncompleteError(Exception):
    pass


async def activate_menu(session: AsyncSession, menu: Menu) -> Menu:
    incomplete = [
        d for d in menu.dishes if d.dish_number is None or d.price_aed is None
    ]
    if incomplete:
        names = ", ".join(d.name for d in incomplete[:5])
        raise MenuIncompleteError(
            f"incomplete dishes (need number and price): {names}"
        )
    previous = await get_active_menu(session, menu.restaurant_id)
    if previous and previous.id != menu.id:
        previous.status = "superseded"
    menu.status = "active"
    await record_audit(
        session, actor="manager", restaurant_id=menu.restaurant_id, entity="menu",
        entity_id=str(menu.id), action="activated",
        after={"version": menu.version},
    )
    await session.commit()
    await session.refresh(menu)
    return menu
```

- [ ] **Step 4: Add endpoint to `src/app/menu/router.py`**

```python
# append to src/app/menu/router.py
from app.menu.service import MenuIncompleteError


@router.post("/menus/{menu_id}/activate", response_model=MenuOut)
async def activate_menu(
    menu_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    menu = await _load_menu(menu_id, restaurant, session)
    try:
        return await service.activate_menu(session, menu)
    except MenuIncompleteError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/pytest tests/menu/test_activate.py -v`
Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add src/app/menu tests/menu/test_activate.py
git commit -m "feat: menu activation with completeness gate and supersede"
```

---

### Task 16: Re-upload price diff

**Files:**
- Create: `src/app/menu/diff.py`
- Modify: `src/app/menu/router.py`, `src/app/menu/schemas.py`
- Test: `tests/menu/test_diff.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/menu/test_diff.py
from decimal import Decimal

from app.llm.port import DishDraft
from app.menu.diff import diff_menus
from app.menu.models import Dish


def _dish(number, name, price):
    return Dish(dish_number=number, name=name, price_aed=Decimal(price))


def _draft(number, name, price):
    return DishDraft(dish_number=number, name=name, price_aed=Decimal(price))


def test_price_change_detected_by_number_and_name():
    old = [_dish(110, "Chicken Biryani", "22.00")]
    new = [_draft(110, "Chicken Biryani", "25.00")]
    report = diff_menus(old, new)
    assert report.price_changes == [
        {"dish_number": 110, "name": "Chicken Biryani",
         "old_price": Decimal("22.00"), "new_price": Decimal("25.00")}
    ]


def test_added_and_removed():
    old = [_dish(110, "Chicken Biryani", "22.00")]
    new = [_draft(201, "Mutton Karahi", "35.00")]
    report = diff_menus(old, new)
    assert report.added[0].name == "Mutton Karahi"
    assert report.removed[0]["name"] == "Chicken Biryani"


def test_same_number_different_name_flagged():
    old = [_dish(110, "Chicken Biryani", "22.00")]
    new = [_draft(110, "Beef Biryani", "22.00")]
    report = diff_menus(old, new)
    assert report.conflicts == [
        {"dish_number": 110, "old_name": "Chicken Biryani", "new_name": "Beef Biryani"}
    ]


def test_unchanged_not_reported():
    old = [_dish(110, "Chicken Biryani", "22.00")]
    new = [_draft(110, "Chicken Biryani", "22.00")]
    report = diff_menus(old, new)
    assert not report.price_changes and not report.added
    assert not report.removed and not report.conflicts
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/menu/test_diff.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/app/menu/diff.py
from dataclasses import dataclass, field
from decimal import Decimal

from app.llm.port import DishDraft
from app.menu.models import Dish


def _norm(name: str) -> str:
    return " ".join(name.lower().split())


@dataclass
class DiffReport:
    price_changes: list[dict] = field(default_factory=list)
    added: list[DishDraft] = field(default_factory=list)
    removed: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)


def diff_menus(old_dishes: list[Dish], new_drafts: list[DishDraft]) -> DiffReport:
    report = DiffReport()
    old_by_number = {d.dish_number: d for d in old_dishes}
    matched_old_ids: set[int | None] = set()

    for draft in new_drafts:
        old = old_by_number.get(draft.dish_number)
        if old is None:
            report.added.append(draft)
            continue
        matched_old_ids.add(old.dish_number)
        if _norm(old.name) != _norm(draft.name):
            report.conflicts.append({
                "dish_number": old.dish_number,
                "old_name": old.name,
                "new_name": draft.name,
            })
        elif (
            draft.price_aed is not None
            and Decimal(old.price_aed) != Decimal(draft.price_aed)
        ):
            report.price_changes.append({
                "dish_number": old.dish_number,
                "name": old.name,
                "old_price": Decimal(old.price_aed),
                "new_price": Decimal(draft.price_aed),
            })

    for d in old_dishes:
        if d.dish_number not in matched_old_ids:
            report.removed.append({"dish_number": d.dish_number, "name": d.name})
    return report
```

- [ ] **Step 4: Run unit tests**

Run: `.venv/bin/pytest tests/menu/test_diff.py -v`
Expected: 4 PASS

- [ ] **Step 5: Surface diff in upload response.** Add to `src/app/menu/schemas.py`:

```python
# append to src/app/menu/schemas.py
class DiffOut(BaseModel):
    price_changes: list[dict]
    added: list[dict]
    removed: list[dict]
    conflicts: list[dict]


class MenuWithDiffOut(MenuOut):
    diff_vs_active: DiffOut | None = None
```

Modify `upload_menu` in `src/app/menu/router.py` — change `response_model=MenuOut` to `response_model=MenuWithDiffOut` and after creating the menu compute diff vs active:

```python
# replace upload_menu body's return with:
    menu = await service.create_menu_from_upload(
        session, restaurant_id=restaurant.id, files=uploaded, extractor=extractor
    )
    active = await service.get_active_menu(session, restaurant.id)
    out = MenuWithDiffOut.model_validate(menu)
    if active is not None:
        report = diff_menus(active.dishes, [
            DishDraft(
                dish_number=d.dish_number, name=d.name, price_aed=d.price_aed,
                category=d.category, description=d.description,
            )
            for d in menu.dishes
        ])
        out.diff_vs_active = DiffOut(
            price_changes=[
                {**c, "old_price": str(c["old_price"]), "new_price": str(c["new_price"])}
                for c in report.price_changes
            ],
            added=[d.model_dump(mode="json") for d in report.added],
            removed=report.removed,
            conflicts=report.conflicts,
        )
    return out
```

With imports at top of router: `from app.llm.port import DishDraft` (extend existing import), `from app.menu.diff import diff_menus`, `from app.menu.schemas import DiffOut, MenuWithDiffOut`.

- [ ] **Step 6: Add integration test to `tests/menu/test_diff.py`**

```python
# append to tests/menu/test_diff.py
async def test_reupload_reports_diff_vs_active(client, auth_headers):
    files = [("files", ("menu.jpg", b"\xff\xd8", "image/jpeg"))]
    m1 = (await client.post("/api/v1/menus", files=files, headers=auth_headers)).json()
    await client.post(f"/api/v1/menus/{m1['id']}/activate", headers=auth_headers)

    # bump a price on active menu so re-upload (same fake drafts) shows a change
    dish = m1["dishes"][0]
    await client.patch(
        f"/api/v1/menus/{m1['id']}/dishes/{dish['id']}",
        json={"price_aed": "19.00"}, headers=auth_headers,
    )

    m2 = (await client.post("/api/v1/menus", files=files, headers=auth_headers)).json()
    changes = m2["diff_vs_active"]["price_changes"]
    assert changes == [{
        "dish_number": 110, "name": "Chicken Biryani",
        "old_price": "19.00", "new_price": "22.00",
    }]
```

- [ ] **Step 7: Run all menu tests**

Run: `.venv/bin/pytest tests/menu -v`
Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add src/app/menu tests/menu/test_diff.py
git commit -m "feat: re-upload diff by dish number+name with price-change report"
```

---

### Task 17: Dish availability toggle

**Files:**
- Modify: `src/app/menu/router.py`
- Test: `tests/menu/test_edit.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# append to tests/menu/test_edit.py
async def test_toggle_availability(client, auth_headers):
    menu = await _upload(client, auth_headers)
    await client.post(f"/api/v1/menus/{menu['id']}/activate", headers=auth_headers)
    dish = menu["dishes"][0]

    resp = await client.patch(
        f"/api/v1/dishes/{dish['id']}/availability",
        json={"is_available": False}, headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["is_available"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/menu/test_edit.py::test_toggle_availability -v`
Expected: FAIL — 404

- [ ] **Step 3: Add endpoint to `src/app/menu/router.py`**

```python
# append to src/app/menu/router.py
from pydantic import BaseModel


class AvailabilityIn(BaseModel):
    is_available: bool


@router.patch("/dishes/{dish_id}/availability", response_model=DishOut)
async def toggle_availability(
    dish_id: int,
    body: AvailabilityIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    dish = await session.get(Dish, dish_id)
    if dish is None or dish.restaurant_id != restaurant.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dish not found")
    before = {"is_available": dish.is_available}
    dish.is_available = body.is_available
    await record_audit(
        session, actor="manager", restaurant_id=restaurant.id, entity="dish",
        entity_id=str(dish.id), action="availability_toggled",
        before=before, after={"is_available": body.is_available},
    )
    await session.commit()
    await session.refresh(dish)
    return dish
```

(Effect is immediate: customer-facing menu rendering in Phase 3 filters `is_available == True` from the active menu — no caching layer to invalidate.)

- [ ] **Step 4: Run test**

Run: `.venv/bin/pytest tests/menu/test_edit.py::test_toggle_availability -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/menu/router.py tests/menu/test_edit.py
git commit -m "feat: instant dish availability toggle"
```

---

### Task 18: Riders + delivery settings endpoints

**Files:**
- Modify: `src/app/identity/router.py`, `src/app/identity/schemas.py`
- Test: `tests/identity/test_riders.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/identity/test_riders.py
async def test_create_and_list_riders(client, auth_headers):
    resp = await client.post(
        "/api/v1/riders",
        json={"name": "Ahmed", "phone": "+971509998888"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "available"

    listing = await client.get("/api/v1/riders", headers=auth_headers)
    assert [r["name"] for r in listing.json()] == ["Ahmed"]


async def test_deactivate_rider(client, auth_headers):
    rider = (
        await client.post(
            "/api/v1/riders",
            json={"name": "Ahmed", "phone": "+971509998888"},
            headers=auth_headers,
        )
    ).json()
    resp = await client.patch(
        f"/api/v1/riders/{rider['id']}",
        json={"status": "deactivated"}, headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "deactivated"


async def test_update_delivery_settings(client, auth_headers):
    resp = await client.patch(
        "/api/v1/settings",
        json={"max_orders_per_batch": 4},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["settings"]["max_orders_per_batch"] == 4
    # untouched keys preserved
    assert resp.json()["settings"]["max_radius_km"] == 10


async def test_invalid_rider_status_422(client, auth_headers):
    rider = (
        await client.post(
            "/api/v1/riders",
            json={"name": "Ahmed", "phone": "+971509998888"},
            headers=auth_headers,
        )
    ).json()
    resp = await client.patch(
        f"/api/v1/riders/{rider['id']}",
        json={"status": "vanished"}, headers=auth_headers,
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/identity/test_riders.py -v`
Expected: FAIL — 404

- [ ] **Step 3: Add schemas to `src/app/identity/schemas.py`**

```python
# append to src/app/identity/schemas.py
from typing import Literal


class RiderIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: str = Field(min_length=7, max_length=32)


class RiderPatch(BaseModel):
    status: Literal["available", "on_delivery", "off_shift", "deactivated"]


class RiderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone: str
    status: str


class SettingsPatch(BaseModel):
    max_orders_per_batch: int | None = Field(default=None, ge=1, le=6)
    max_items_per_order: int | None = Field(default=None, ge=1, le=100)
    delivery_fee_tiers: list[dict] | None = None
```

- [ ] **Step 4: Add endpoints to `src/app/identity/router.py`**

```python
# append to src/app/identity/router.py
from sqlalchemy.orm.attributes import flag_modified

from app.identity.models import Rider
from app.identity.schemas import RiderIn, RiderOut, RiderPatch, SettingsPatch


@router.post("/riders", response_model=RiderOut, status_code=201)
async def create_rider(
    body: RiderIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rider = Rider(restaurant_id=restaurant.id, name=body.name, phone=body.phone)
    session.add(rider)
    await session.flush()
    await record_audit(
        session, actor="manager", restaurant_id=restaurant.id, entity="rider",
        entity_id=str(rider.id), action="created", after=body.model_dump(),
    )
    await session.commit()
    await session.refresh(rider)
    return rider


@router.get("/riders", response_model=list[RiderOut])
async def list_riders(
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = await session.scalars(
        select(Rider).where(Rider.restaurant_id == restaurant.id).order_by(Rider.id)
    )
    return list(rows)


@router.patch("/riders/{rider_id}", response_model=RiderOut)
async def patch_rider(
    rider_id: int,
    body: RiderPatch,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rider = await session.get(Rider, rider_id)
    if rider is None or rider.restaurant_id != restaurant.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "rider not found")
    before = {"status": rider.status}
    rider.status = body.status
    await record_audit(
        session, actor="manager", restaurant_id=restaurant.id, entity="rider",
        entity_id=str(rider.id), action="status_changed",
        before=before, after={"status": body.status},
    )
    await session.commit()
    await session.refresh(rider)
    return rider


@router.patch("/settings", response_model=RestaurantOut)
async def patch_settings(
    body: SettingsPatch,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    before = {k: restaurant.settings.get(k) for k in changes}
    restaurant.settings = {**restaurant.settings, **changes}
    flag_modified(restaurant, "settings")
    await record_audit(
        session, actor="manager", restaurant_id=restaurant.id, entity="restaurant",
        entity_id=str(restaurant.id), action="settings_changed",
        before=before, after=changes,
    )
    await session.commit()
    await session.refresh(restaurant)
    return restaurant
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/pytest tests/identity/test_riders.py -v`
Expected: 4 PASS

- [ ] **Step 6: Commit**

```bash
git add src/app/identity tests/identity/test_riders.py
git commit -m "feat: rider management and delivery settings"
```

---

### Task 19: Full suite + lint gate

- [ ] **Step 1: Run everything**

Run: `.venv/bin/pytest -v`
Expected: ALL PASS (≈30 tests)

- [ ] **Step 2: Lint**

Run: `.venv/bin/ruff check src apps tests`
Expected: clean (fix anything it flags)

- [ ] **Step 3: Boot the real server as smoke test**

```bash
.venv/bin/uvicorn app.main:app --port 8000 &
sleep 2
curl -s localhost:8000/health
kill %1
```
Expected: `{"status":"ok"}`

- [ ] **Step 4: Commit any lint fixes**

```bash
git add -A && git commit -m "chore: lint fixes" || echo "nothing to fix"
```

---

## Post-phase

Phase 0+1 done = restaurant can sign up, log in, upload menu files, get AI-extracted draft dishes, edit/confirm/activate menu, see price-diffs on re-upload, toggle availability instantly, register riders, tune delivery settings. Everything audited, everything tested.

Next plan: **Phase 2 — WhatsApp core** (adapter Mock+Cloud, webhook pipeline, outbox worker, conversation engine, web simulator). Written after this plan executes, so it builds on real code.
