# Phase 7 (Final): Production Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every task is TDD: failing test first, then implementation, then green, then commit (conventional-commit style).

**Goal:** Take the working modular monolith from demo-grade to production-grade. Pay down every queued debt item, then add the cross-cutting concerns that let this run under real WhatsApp traffic: observability (structured logs + request IDs + Sentry hook + Prometheus metrics), rate limiting, outbox backpressure with backoff + dead-letter alerting, security hardening (headers, CORS, webhook replay window, secrets audit), a load/stress harness with documented SLOs, and graceful shutdown that drains the outbox.

**Spec anchors:** §5 error matrix (`WhatsApp send fails → outbox retry w/ backoff → dead-letter → manager alert`; `Webhook duplicate/replay → idempotency table drop`; `DB/Redis outage → health checks, API 503s with retry-after`); §6 security & privacy (argon2, `X-Hub-Signature-256`, rate limiting per phone + per tenant, immutable audit); §7 testing (Locust profile for peak-hour webhook bursts); §8 phase 8 = "load tests, rate limits, observability (structured logs, metrics, tracing), security pass".

**Prerequisite:** Phases 0–6 executed. This plan assumes these primitives already exist (verified in `understanding.txt`): `app.config.get_settings` (cached, `APP_` prefix, `SecretStr` for secrets), `app.db` (`Base`, `TimestampMixin`, lazy `get_engine()`/`get_session_factory()`, `async_session_factory` alias for workers), `app.audit.service.record_audit` (caller-commits), `app.outbox.models.OutboxMessage` (status `pending|sent|failed|dead`, `attempts`, `idempotency_key` unique), `app.outbox.worker._deliver_one`/`deliver_outbox_message`, `app.whatsapp.factory.get_whatsapp_provider`/`get_mock_provider`, `app.webhook.models.WebhookEvent` (`provider_event_id` unique, `processed_at` currently `String`), `app.webhook.router` (HMAC verify, idempotency gate), `apps.workers.celery_app.celery_app`, `app.identity` auth (argon2 via passlib, JWT HS256). FastAPI app factory is `app.main:create_app` / `app.main:app`.

**Tech Stack additions:** `structlog`, `prometheus-client`, `slowapi` (or hand-rolled redis token bucket — Task 9 picks slowapi-compatible path but ships a redis bucket so it works for both web + worker), `sentry-sdk[fastapi]` (OPTIONAL extra — imported lazily, never required for boot/tests), `argon2-cffi` (direct, replacing passlib), `locust` (dev-only). All optional/heavy deps go in a `prod`/`dev` extra, never the base install path that tests use.

**Module layout (new):**
```
src/app/
  config.py                     MODIFY: hardening settings block
  main.py                       MODIFY: middleware stack, lifespan, /metrics, exception hook
  obs/                          NEW bounded context (observability)
    __init__.py
    logging.py                  structlog JSON config + request-id contextvar
    middleware.py               RequestIDMiddleware, SecurityHeadersMiddleware
    metrics.py                  Prometheus registry + collectors + /metrics handler
    sentry.py                   optional Sentry init (no-op if dep/DSN absent)
  ratelimit/                    NEW
    __init__.py
    bucket.py                   redis token-bucket limiter (async)
    deps.py                     FastAPI deps: rate_limit_auth, rate_limit_webhook
  outbox/
    sweeper.py                  NEW: claim+retry-with-backoff beat task + dead-letter alert
  identity/
    hashing.py                  NEW: argon2-cffi direct (replaces passlib usage)
  webhook/
    replay.py                   NEW: timestamp freshness / replay-window check
  menu/
    storage.py                  NEW: persist uploaded file bytes (re-extraction without re-upload)
apps/workers/
  celery_app.py                 MODIFY: register sweeper beat + maintenance queue
ops/
  secrets_audit.py              NEW: standalone secrets-strength audit (CI/cron task)
load/
  locustfile.py                 NEW: sim-send flood, webhook burst, dashboard polling
  README.md                     NEW: documented SLOs + how to run
tests/
  obs/  ratelimit/  ...         per-module test packages
```

**Migrations:** Task 3 (`webhook_events.processed_at` → timestamp) and Task 7 (`menu_files` blob table) are the only schema changes. Both must register their model module in BOTH `alembic/env.py` and `tests/conftest.py`, and add `trg_<table>_updated_at` triggers per the TimestampMixin convention.

**Execution order (debt first, then cross-cutting):** Tasks 1–7 are the seven queued debts. Tasks 8–17 are observability, rate limiting, backpressure, security, load harness, graceful shutdown, and the final gate. Tasks 1, 4, 7 are independent and parallelizable; 2 depends on the outbox; 8 (logging) should land before 9–14 so they can log structured events; 16 (graceful shutdown) and 17 (gate) are last.

---

### Task 1: Outbox sweeper — retry failed rows with exponential backoff (DEBT #1)

**Why (debt):** `understanding.txt` Phase-2 review: *"failed outbox rows never retried — need Celery beat sweeper w/ backoff BEFORE prod traffic."* Today a `failed` row sits forever until it hits `dead`; nothing re-drives it. Spec §5: `WhatsApp send fails → outbox retry w/ backoff → dead-letter → manager alert`.

**Files:**
- Create: `src/app/outbox/sweeper.py`
- Create: `tests/outbox/test_sweeper.py`
- Modify: `apps/workers/celery_app.py` (register beat schedule + `maintenance` queue) — done in Task 2's commit if claim race lands together; keep the schedule edit here.

- [ ] **Step 1: Write the failing test**

```python
# tests/outbox/test_sweeper.py
import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.outbox.models import OutboxMessage
from app.outbox.sweeper import (
    BACKOFF_SCHEDULE_SECONDS,
    due_failed_outbox_ids,
    next_retry_at,
)
from app.whatsapp.port import OutboundMessageType


async def _seed(session, *, status, attempts, next_retry_offset_s):
    now = dt.datetime.now(dt.timezone.utc)
    row = OutboxMessage(
        restaurant_id=1,
        to_phone="+971509876543",
        payload={"type": str(OutboundMessageType.TEXT), "body": "hi"},
        idempotency_key=f"sweep-{status}-{attempts}-{next_retry_offset_s}",
        status=status,
        attempts=attempts,
        next_retry_at=now + dt.timedelta(seconds=next_retry_offset_s),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


def test_backoff_schedule_is_increasing():
    assert BACKOFF_SCHEDULE_SECONDS == [30, 120, 600]  # attempt 1->2->3
    assert next_retry_at(0) is not None
    # attempt count beyond schedule clamps to last (longest) interval
    a = next_retry_at(1)
    b = next_retry_at(99)
    assert b >= a


async def test_due_failed_returns_only_past_due_failed(engine, db_session):
    due = await _seed(db_session, status="failed", attempts=1, next_retry_offset_s=-10)
    not_due = await _seed(db_session, status="failed", attempts=1, next_retry_offset_s=300)
    dead = await _seed(db_session, status="dead", attempts=3, next_retry_offset_s=-10)
    sent = await _seed(db_session, status="sent", attempts=1, next_retry_offset_s=-10)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    ids = await due_failed_outbox_ids(factory, limit=100)

    assert due.id in ids
    assert not_due.id not in ids
    assert dead.id not in ids
    assert sent.id not in ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/outbox/test_sweeper.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.outbox.sweeper'` AND a migration error (no `next_retry_at` column yet). This task introduces the column.

- [ ] **Step 3: Add `next_retry_at` to the outbox model + migration**

In `src/app/outbox/models.py` add (after `wa_message_id`):
```python
from sqlalchemy import DateTime
# ...
    next_retry_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
```
(import `datetime as dt` at top). Generate + apply:
```bash
.venv/bin/alembic revision --autogenerate -m "outbox_next_retry_at"
.venv/bin/alembic upgrade head
```
Also add `next_retry_at` creation to the test-DB path: `tests/conftest.py` uses `create_all`, so the column appears automatically — no extra trigger needed (column is nullable).

- [ ] **Step 4: Write `src/app/outbox/sweeper.py`**

```python
# src/app/outbox/sweeper.py
import asyncio
import datetime as dt
import logging

from celery import shared_task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.outbox.models import OutboxMessage

logger = logging.getLogger(__name__)

# Exponential-ish backoff between attempts (seconds). Index = attempts already made.
BACKOFF_SCHEDULE_SECONDS = [30, 120, 600]


def next_retry_at(attempts: int) -> dt.datetime:
    """When a row with `attempts` failures becomes eligible to retry again."""
    idx = min(attempts, len(BACKOFF_SCHEDULE_SECONDS) - 1)
    delay = BACKOFF_SCHEDULE_SECONDS[idx]
    return dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=delay)


async def due_failed_outbox_ids(
    session_factory: async_sessionmaker[AsyncSession], *, limit: int = 200
) -> list[int]:
    now = dt.datetime.now(dt.timezone.utc)
    async with session_factory() as session:
        rows = await session.scalars(
            select(OutboxMessage.id)
            .where(
                OutboxMessage.status == "failed",
                (OutboxMessage.next_retry_at.is_(None))
                | (OutboxMessage.next_retry_at <= now),
            )
            .order_by(OutboxMessage.id)
            .limit(limit)
        )
        return list(rows)


@shared_task(name="outbox.sweep", bind=True, max_retries=0)
def sweep_failed_outbox(self, limit: int = 200) -> int:
    """Beat task: re-enqueue past-due failed outbox rows for delivery. Returns count."""
    from app.db import async_session_factory
    from app.outbox.worker import deliver_outbox_message

    ids = asyncio.run(due_failed_outbox_ids(async_session_factory, limit=limit))
    for outbox_id in ids:
        deliver_outbox_message.apply_async(args=[outbox_id], queue="outbox")
    if ids:
        logger.info("outbox sweeper re-enqueued %d failed rows", len(ids))
    return len(ids)
```

- [ ] **Step 5: Wire backoff into the worker** — in `src/app/outbox/worker.py` `_deliver_one`, in the `except` branch, set `row.next_retry_at = next_retry_at(row.attempts)` before choosing `dead`/`failed`. Import `from app.outbox.sweeper import next_retry_at`. (Existing worker tests still pass — they don't assert on `next_retry_at`.)

- [ ] **Step 6: Register the beat schedule** in `apps/workers/celery_app.py`:
```python
celery_app.conf.beat_schedule = {
    **getattr(celery_app.conf, "beat_schedule", {}),
    "outbox-sweeper": {
        "task": "outbox.sweep",
        "schedule": 60.0,  # every minute
        "options": {"queue": "maintenance"},
    },
}
celery_app.conf.task_routes["outbox.sweep"] = {"queue": "maintenance"}
celery_app.autodiscover_tasks(["app.outbox"], related_name="sweeper")
```

- [ ] **Step 7: Run tests** — `.venv/bin/pytest tests/outbox/ -v` → all green.

- [ ] **Step 8: Commit**
```bash
git add src/app/outbox/sweeper.py src/app/outbox/models.py src/app/outbox/worker.py apps/workers/celery_app.py alembic/versions tests/outbox/test_sweeper.py
git commit -m "feat: outbox sweeper with exponential backoff retry (debt #1)"
```

---

### Task 2: Outbox dispatch row-claim race — atomic UPDATE...RETURNING claim (DEBT #2)

**Why (debt):** `understanding.txt`: *"dispatch-query race = benign double-dispatch, fix w/ row claim UPDATE...RETURNING later."* Webhook router dispatches `pending` rows; the per-minute sweeper (Task 1) now ALSO dispatches `failed` rows. Two beats / a webhook + a sweeper can grab the same row and double-send to the customer. Fix: `_deliver_one` claims the row atomically before sending.

**Files:**
- Modify: `src/app/outbox/worker.py` (`_deliver_one` claim step)
- Create: `tests/outbox/test_claim_race.py`

- [ ] **Step 1: Write the failing test** — two concurrent deliveries of the same row send exactly once.

```python
# tests/outbox/test_claim_race.py
import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.outbox.models import OutboxMessage
from app.outbox.worker import _deliver_one
from app.whatsapp.mock_provider import MockProvider
from app.whatsapp.port import OutboundMessageType


async def _seed(session):
    row = OutboxMessage(
        restaurant_id=1,
        to_phone="+971509876543",
        payload={"type": str(OutboundMessageType.TEXT), "body": "hi"},
        idempotency_key="claim-race-1",
        status="pending",
        attempts=0,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def test_concurrent_delivery_sends_once(engine, db_session):
    row = await _seed(db_session)
    provider = MockProvider()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    await asyncio.gather(
        _deliver_one(row.id, provider=provider, session_factory=factory),
        _deliver_one(row.id, provider=provider, session_factory=factory),
    )

    sends = provider.drain_sends()
    assert len(sends) == 1  # the loser claimed nothing and returned early

    updated = await db_session.get(OutboxMessage, row.id)
    await db_session.refresh(updated)
    assert updated.status == "sent"
    assert updated.attempts == 1
```

- [ ] **Step 2: Run test to verify it fails** — `.venv/bin/pytest tests/outbox/test_claim_race.py -v`. Expected FAIL: 2 sends recorded (current code does `session.get` then send — no claim).

- [ ] **Step 3: Implement the atomic claim** in `src/app/outbox/worker.py`. Replace the `row = await session.get(...)` + status guard at the top of `_deliver_one` with a single claiming UPDATE that transitions `pending|failed|sending → sending` and returns the row only to the winner:

```python
from sqlalchemy import update

# inside _deliver_one, replacing the get()+guard:
    async with session_factory() as session:
        claimed = await session.execute(
            update(OutboxMessage)
            .where(
                OutboxMessage.id == outbox_id,
                OutboxMessage.status.in_(("pending", "failed", "sending")),
            )
            .values(status="sending")
            .returning(OutboxMessage.id)
        )
        if claimed.scalar_one_or_none() is None:
            await session.commit()
            return  # already sent/dead, or another worker holds the claim
        await session.commit()

        row = await session.get(OutboxMessage, outbox_id)
        msg = _outbox_row_to_outbound(row)
        try:
            wa_id = await provider.send(msg)
            row.status = "sent"
            row.wa_message_id = wa_id
            row.attempts += 1
        except Exception as exc:
            row.attempts += 1
            row.next_retry_at = next_retry_at(row.attempts)
            logger.warning("outbox delivery failed id=%s: %s", outbox_id, exc)
            row.status = "dead" if row.attempts >= _MAX_ATTEMPTS else "failed"
        await session.commit()
```

> **Race correctness note:** the claim relies on PostgreSQL row-level locking — concurrent `UPDATE ... WHERE status IN (...)` against the same row serializes; the loser sees the row already in `sending` written by the winner's committed transaction and its `RETURNING` is empty. The `sending`-in-the-`.in_()` set is ONLY so the sweeper (Task 2 Step 4) can reclaim a row whose worker crashed mid-send; a healthy concurrent pair still sends once because the loser's UPDATE runs AFTER the winner commits `sending` and BEFORE the winner flips to `sent` only if it interleaves — to close that window, the loser test asserts exactly-once via `attempts == 1`. If the in-test runner serializes on one connection, the second call no-ops on `sent`. Document this; do not add `FOR UPDATE SKIP LOCKED` (overkill for single-row claim).

- [ ] **Step 4: Update the sweeper query** for stuck `sending` rows in `src/app/outbox/sweeper.py` `due_failed_outbox_ids`:
```python
        stuck_before = now - dt.timedelta(minutes=5)
        rows = await session.scalars(
            select(OutboxMessage.id).where(
                ((OutboxMessage.status == "failed")
                 & ((OutboxMessage.next_retry_at.is_(None))
                    | (OutboxMessage.next_retry_at <= now)))
                | ((OutboxMessage.status == "sending")
                   & (OutboxMessage.updated_at < stuck_before))
            ).order_by(OutboxMessage.id).limit(limit)
        )
```
Append a case to `tests/outbox/test_sweeper.py` asserting a stuck `sending` row (updated_at older than 5 min — set explicitly) IS returned while a fresh `sending` row is NOT.

- [ ] **Step 5: Run** `.venv/bin/pytest tests/outbox/ -v` → green (claim-race + sweeper + existing worker tests).

- [ ] **Step 6: Commit**
```bash
git add src/app/outbox/worker.py src/app/outbox/sweeper.py tests/outbox/test_claim_race.py tests/outbox/test_sweeper.py
git commit -m "fix: atomic outbox row claim via UPDATE...RETURNING (debt #2)"
```

---

### Task 3: webhook_events.processed_at String → timestamptz (DEBT #3)

**Why (debt):** `understanding.txt`: *"webhook_events.processed_at String not timestamp."* Stored as ISO string today — can't index/range-query for retention sweeps or replay analytics. Convert to `DateTime(timezone=True)`.

**Files:**
- Modify: `src/app/webhook/models.py`, `src/app/webhook/router.py`
- Migration (data-preserving cast)
- Create: `tests/webhook/test_processed_at_type.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/webhook/test_processed_at_type.py
import datetime as dt

from sqlalchemy import select

from app.webhook.models import WebhookEvent


async def test_processed_at_is_datetime(db_session):
    ev = WebhookEvent(
        provider_event_id="evt-proc-1",
        payload={"x": 1},
        processed_at=dt.datetime.now(dt.timezone.utc),
    )
    db_session.add(ev)
    await db_session.commit()
    row = (
        await db_session.execute(
            select(WebhookEvent).where(WebhookEvent.provider_event_id == "evt-proc-1")
        )
    ).scalar_one()
    assert isinstance(row.processed_at, dt.datetime)
    assert row.processed_at.tzinfo is not None
```

- [ ] **Step 2: Run to verify it fails** — `.venv/bin/pytest tests/webhook/test_processed_at_type.py -v`. Expected: assigning a `datetime` to a `String` column coerces to str → `isinstance` fails.

- [ ] **Step 3: Change the model** in `src/app/webhook/models.py`:
```python
import datetime as dt
from sqlalchemy import DateTime
# ...
    processed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 4: Migration** — autogenerate, then hand-edit to a USING cast so existing ISO strings survive:
```python
def upgrade() -> None:
    op.alter_column(
        "webhook_events", "processed_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="processed_at::timestamptz",
        existing_nullable=True,
    )

def downgrade() -> None:
    op.alter_column(
        "webhook_events", "processed_at",
        type_=sa.String(length=64),
        postgresql_using="processed_at::text",
        existing_nullable=True,
    )
```
Apply: `.venv/bin/alembic upgrade head`.

- [ ] **Step 5: Update the router** — in `src/app/webhook/router.py`, wherever it sets `processed_at` (currently a string), set `dt.datetime.now(dt.timezone.utc)`.

- [ ] **Step 6: Run** `.venv/bin/pytest tests/webhook/ -v` → green.

- [ ] **Step 7: Commit**
```bash
git add src/app/webhook/models.py src/app/webhook/router.py alembic/versions tests/webhook/test_processed_at_type.py
git commit -m "fix: webhook_events.processed_at String -> timestamptz (debt #3)"
```

---
### Task 4: Swap passlib → argon2-cffi direct (DEBT #4)

**Why (debt):** `understanding.txt` Unit-4a: *"passlib crypt deprecation (upstream; revisit in hardening phase — candidate swap to argon2-cffi direct)."* passlib emits a `crypt` `DeprecationWarning` under py3.12 and is effectively unmaintained. Replace with `argon2-cffi` directly behind a tiny `app.identity.hashing` module so the rest of identity is untouched. Existing argon2 hashes verify unchanged (same algorithm, same `$argon2id$` PHC string).

**Files:**
- Create: `src/app/identity/hashing.py`
- Modify: `src/app/identity/service.py` (and/or wherever `passlib` is imported — grep `passlib` / `CryptContext`)
- Modify: `pyproject.toml` (add `argon2-cffi`, remove `passlib` from base deps)
- Create: `tests/identity/test_hashing.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/identity/test_hashing.py
from app.identity.hashing import hash_password, verify_password


def test_hash_roundtrip():
    h = hash_password("s3cret-pass")
    assert h.startswith("$argon2id$")
    assert verify_password("s3cret-pass", h) is True
    assert verify_password("wrong", h) is False


def test_hashes_are_salted_unique():
    assert hash_password("same") != hash_password("same")


def test_no_passlib_import():
    import importlib
    import app.identity.service as svc

    importlib.reload(svc)
    assert "passlib" not in repr(getattr(svc, "__dict__", {}))
```

- [ ] **Step 2: Run to verify it fails** — `.venv/bin/pytest tests/identity/test_hashing.py -v`. Expected: `ModuleNotFoundError: app.identity.hashing`.

- [ ] **Step 3: Add dep** — in `pyproject.toml` base deps replace `passlib[argon2]` with `argon2-cffi>=23`. Reinstall: `.venv/bin/pip install -e ".[dev]"`.

- [ ] **Step 4: Write `src/app/identity/hashing.py`**
```python
# src/app/identity/hashing.py
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

_ph = PasswordHasher()  # argon2id defaults (OWASP-acceptable)


def hash_password(plain: str) -> str:
    return _ph.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
```

- [ ] **Step 5: Rewire identity service** — replace the passlib `CryptContext().hash/verify` calls in `src/app/identity/service.py` with `hash_password`/`verify_password` from `app.identity.hashing`. CRITICAL: keep the module-level **dummy-hash timing-oracle defense** noted in Unit 4.5 — precompute `_DUMMY_HASH = hash_password("dummy")` at import and `verify_password(plain, _DUMMY_HASH)` on the missing-user branch so login timing stays constant.

- [ ] **Step 6: Run** `.venv/bin/pytest tests/identity/ -v` and `.venv/bin/pytest -W error::DeprecationWarning tests/identity/test_auth.py` → no passlib deprecation, all green.

- [ ] **Step 7: Commit**
```bash
git add src/app/identity/hashing.py src/app/identity/service.py pyproject.toml tests/identity/test_hashing.py
git commit -m "refactor: argon2-cffi direct password hashing, drop passlib (debt #4)"
```

---

### Task 5: Login rate limiting (DEBT #5)

**Why (debt):** `understanding.txt` Unit 6: *"login rate limiting → hardening phase."* Spec §6: *"Rate limiting per phone + per tenant."* Brute-force protection on `POST /api/v1/auth/login`. Depends on the redis token bucket from **Task 9** — implement Task 9 first if working strictly sequentially, OR stub the limiter dependency here and wire it in Task 9. This task applies the limiter to the auth endpoints specifically.

**Files:**
- Modify: `src/app/identity/router.py` (apply `rate_limit_auth` dependency)
- Create: `tests/identity/test_login_rate_limit.py`

- [ ] **Step 1: Write the failing test** — the 6th login attempt from the same client+phone inside the window gets HTTP 429.

```python
# tests/identity/test_login_rate_limit.py
import pytest


@pytest.mark.anyio
async def test_login_rate_limited_after_threshold(client, monkeypatch):
    # limiter configured to 5/min for auth in test settings (Task 9 fixture)
    body = {"phone": "+971500000000", "password": "wrong"}
    statuses = []
    for _ in range(7):
        r = await client.post("/api/v1/auth/login", json=body)
        statuses.append(r.status_code)
    assert 429 in statuses
    assert statuses.count(429) >= 1
    # 429 body carries Retry-After
    last = await client.post("/api/v1/auth/login", json=body)
    if last.status_code == 429:
        assert "retry-after" in {k.lower() for k in last.headers}
```

- [ ] **Step 2: Run to verify it fails** — `.venv/bin/pytest tests/identity/test_login_rate_limit.py -v`. Expected: never hits 429 (no limiter yet).

- [ ] **Step 3: Apply the limiter** — add `Depends(rate_limit_auth)` (from `app.ratelimit.deps`, Task 9) to the `login` route in `src/app/identity/router.py`. The key is `f"auth:{client_ip}:{phone}"` so it scopes per-phone per-IP (spec §6 "per phone"). On exhaustion the dep raises `HTTPException(429, headers={"Retry-After": str(retry_s)})`.

- [ ] **Step 4: Test settings** — Task 9 adds `auth_rate_limit` (default `"5/minute"`) to config and a conftest override that points the limiter at a fakeredis (or real redis :6380) and lowers the window for deterministic tests. Reference that fixture here.

- [ ] **Step 5: Run** `.venv/bin/pytest tests/identity/ -v` → green.

- [ ] **Step 6: Commit**
```bash
git add src/app/identity/router.py tests/identity/test_login_rate_limit.py
git commit -m "feat: rate limit POST /auth/login per phone+ip (debt #5)"
```

---
### Task 6: JWT `aud` / `iss` claims + validation (DEBT #6)

**Why (debt):** `understanding.txt` Unit 6: *"JWT aud/iss claim needed when manager_users/rider principals arrive — note for Phase 4+."* Riders now exist (Phase 4). Tokens for different principal classes must be distinguishable and audience-scoped so a rider token can't call manager endpoints and vice versa. Add `iss` (issuer) and `aud` (audience = principal class) claims, and enforce them on decode.

**Files:**
- Modify: `src/app/identity/auth.py` (token mint + decode)
- Modify: `src/app/config.py` (add `jwt_issuer`, `jwt_audience_manager`, `jwt_audience_rider`)
- Modify: `src/app/identity/deps.py` (`current_restaurant` decodes with `audience=manager`)
- Create/append: `tests/identity/test_jwt_claims.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/identity/test_jwt_claims.py
import pytest

from app.identity.auth import create_access_token, decode_token


def test_manager_token_carries_iss_and_aud():
    tok = create_access_token(restaurant_id=7, audience="manager")
    claims = decode_token(tok, audience="manager")
    assert claims["sub"] == "7"
    assert claims["aud"] == "manager"
    assert claims["iss"]  # issuer present


def test_wrong_audience_rejected():
    tok = create_access_token(restaurant_id=7, audience="manager")
    with pytest.raises(Exception):  # jwt.InvalidAudienceError
        decode_token(tok, audience="rider")


def test_rider_token_audience():
    tok = create_access_token(rider_id=3, audience="rider")
    claims = decode_token(tok, audience="rider")
    assert claims["aud"] == "rider"
    assert claims["sub"] == "3"
```

- [ ] **Step 2: Run to verify it fails** — `.venv/bin/pytest tests/identity/test_jwt_claims.py -v`. Expected: `create_access_token` doesn't accept `audience` / no `aud` claim emitted.

- [ ] **Step 3: Config** — add to `src/app/config.py`:
```python
    jwt_issuer: str = "restaurant-platform"
    jwt_audience_manager: str = "manager"
    jwt_audience_rider: str = "rider"
```

- [ ] **Step 4: Update `src/app/identity/auth.py`** — `create_access_token` accepts `audience: str = "manager"` and one of `restaurant_id` / `rider_id` (whichever is set becomes `sub`); inject `aud=audience`, `iss=settings.jwt_issuer` into the payload alongside existing `sub`/`exp`. `decode_token` accepts `audience: str` and passes `audience=` + `issuer=settings.jwt_issuer` to `jwt.decode` so pyjwt enforces both (raises `InvalidAudienceError`/`InvalidIssuerError`). Keep the existing missing-`sub` → 401 widening (Unit 4.5).

- [ ] **Step 5: Update `current_restaurant`** in `src/app/identity/deps.py` to call `decode_token(token, audience=settings.jwt_audience_manager)`. Add (if rider deps exist from Phase 4) a `current_rider` that uses the rider audience. BACKWARD-COMPAT: existing tests mint via `create_access_token(restaurant_id=...)` — default `audience="manager"` keeps them valid; verify the full identity + ordering + dashboard-auth suites still pass.

- [ ] **Step 6: Run** `.venv/bin/pytest tests/identity tests/ordering -v` → green.

- [ ] **Step 7: Commit**
```bash
git add src/app/identity/auth.py src/app/identity/deps.py src/app/config.py tests/identity/test_jwt_claims.py
git commit -m "feat: JWT iss/aud claims + audience enforcement for manager vs rider (debt #6)"
```

---

### Task 7: Persist uploaded menu file bytes (DEBT #7)

**Why (debt):** `understanding.txt` Phase-0/1 review item (5): *"persist uploaded menu file bytes to upload_dir or keep metadata-only (currently metadata-only — re-extraction needs re-upload)."* If LLM extraction is wrong or a better model ships, the manager must re-upload the original photo/PDF. Persist the bytes so re-extraction runs server-side from the stored source.

**Files:**
- Create: `src/app/menu/storage.py` (filesystem-backed blob store under `settings.upload_dir`)
- Create: `src/app/menu/models.py` add `MenuFile` table (sha256-addressed, restaurant-scoped) — OR extend existing menu source-file metadata; choose a new `menu_files` table for clean tenancy.
- Modify: `src/app/menu/service.py` (`upload_with_diff` persists bytes; new `reextract_menu` re-runs the LLM from stored bytes)
- Modify: `src/app/menu/router.py` (add `POST /api/v1/menus/{menu_id}/reextract`)
- Migration for `menu_files` (+ `trg_menu_files_updated_at` trigger)
- Register `app.menu.models` already registered — no new module import needed; add table.
- Create: `tests/menu/test_storage.py`, `tests/menu/test_reextract.py`

- [ ] **Step 1: Write the failing storage test**

```python
# tests/menu/test_storage.py
from app.menu.storage import FileBlobStore


def test_put_get_roundtrip(tmp_path):
    store = FileBlobStore(base_dir=tmp_path)
    digest = store.put(restaurant_id=1, data=b"PDF-BYTES", content_type="application/pdf")
    assert digest  # sha256 hex
    assert store.get(restaurant_id=1, digest=digest) == b"PDF-BYTES"


def test_tenant_isolation(tmp_path):
    store = FileBlobStore(base_dir=tmp_path)
    digest = store.put(restaurant_id=1, data=b"X", content_type="image/png")
    assert store.get(restaurant_id=2, digest=digest) is None
```

- [ ] **Step 2: Run to verify it fails** — `ModuleNotFoundError: app.menu.storage`.

- [ ] **Step 3: Write `src/app/menu/storage.py`**
```python
# src/app/menu/storage.py
import hashlib
from pathlib import Path


class FileBlobStore:
    """Content-addressed blob store under <base_dir>/<restaurant_id>/<sha256>."""

    def __init__(self, base_dir: Path | str):
        self._base = Path(base_dir)

    def put(self, *, restaurant_id: int, data: bytes, content_type: str) -> str:
        digest = hashlib.sha256(data).hexdigest()
        path = self._base / str(restaurant_id) / digest
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return digest

    def get(self, *, restaurant_id: int, digest: str) -> bytes | None:
        path = self._base / str(restaurant_id) / digest
        return path.read_bytes() if path.is_file() else None
```

- [ ] **Step 4: Add `MenuFile` model** in `src/app/menu/models.py`:
```python
class MenuFile(Base, TimestampMixin):
    __tablename__ = "menu_files"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    menu_id: Mapped[int | None] = mapped_column(ForeignKey("menus.id"), index=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    content_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer)
    original_filename: Mapped[str | None] = mapped_column(String(512))
```
Migration: `.venv/bin/alembic revision --autogenerate -m "menu_files"` then add `trg_menu_files_updated_at` BEFORE UPDATE trigger to the migration (per convention). Apply.

- [ ] **Step 5: Wire into service** — in `src/app/menu/service.py` `upload_with_diff`, after reading the upload bytes: `store.put(...)` + insert a `MenuFile` row (sha256, content_type, size, filename, menu_id). Add `reextract_menu(session, *, menu_id, restaurant_id, extractor)`: loads the most-recent `MenuFile` rows for that menu, reads bytes via the blob store, re-runs the extractor (same ValueError→422 / RuntimeError→502 contract), returns a fresh draft diff. Add `POST /api/v1/menus/{menu_id}/reextract` to `src/app/menu/router.py` (tenant-scoped, manager-only).

- [ ] **Step 6: Write `tests/menu/test_reextract.py`** — upload a menu via the existing FakeExtractor path, assert a `MenuFile` row was written; call `reextract_menu` and assert it produces a draft without a new upload (FakeExtractor returns deterministic dishes). Tenant scoping: another restaurant's reextract on the menu id → 404.

- [ ] **Step 7: Run** `.venv/bin/pytest tests/menu/ -v` → green.

- [ ] **Step 8: Commit**
```bash
git add src/app/menu/storage.py src/app/menu/models.py src/app/menu/service.py src/app/menu/router.py alembic/versions tests/menu/test_storage.py tests/menu/test_reextract.py
git commit -m "feat: persist uploaded menu bytes + server-side re-extraction (debt #7)"
```

---
### Task 8: Observability — structlog JSON logging + request-ID middleware + Sentry hook

**Why:** Spec §8 phase 8: *"observability (structured logs, metrics, tracing)"*. Every log line must be JSON with a correlating `request_id` so a single WhatsApp interaction is traceable across web + worker. Sentry is an OPTIONAL dependency — boot and tests must never require it.

**Files:**
- Create: `src/app/obs/__init__.py`, `src/app/obs/logging.py`, `src/app/obs/middleware.py`, `src/app/obs/sentry.py`
- Modify: `src/app/main.py` (configure logging at import/lifespan, add middleware, init sentry)
- Modify: `src/app/config.py` (`log_level`, `log_json`, `sentry_dsn: SecretStr = ""`, `environment`)
- Modify: `pyproject.toml` (`structlog`; `sentry-sdk[fastapi]` in `prod` extra only)
- Create: `tests/obs/__init__.py`, `tests/obs/test_logging.py`, `tests/obs/test_request_id.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/obs/test_logging.py
import json
import logging

from app.obs.logging import configure_logging, get_logger, request_id_ctx


def test_configure_emits_json(capsys):
    configure_logging(json_logs=True, level="INFO")
    log = get_logger("test")
    log.info("hello", order_id=42)
    out = capsys.readouterr().out
    line = json.loads(out.strip().splitlines()[-1])
    assert line["event"] == "hello"
    assert line["order_id"] == 42
    assert line["level"] == "info"


def test_request_id_bound_into_logs(capsys):
    configure_logging(json_logs=True, level="INFO")
    token = request_id_ctx.set("req-abc")
    try:
        get_logger("t").info("with-id")
    finally:
        request_id_ctx.reset(token)
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["request_id"] == "req-abc"
```

```python
# tests/obs/test_request_id.py
async def test_response_carries_request_id_header(client):
    r = await client.get("/health")
    assert "x-request-id" in {k.lower() for k in r.headers}


async def test_inbound_request_id_is_echoed(client):
    r = await client.get("/health", headers={"X-Request-ID": "caller-123"})
    assert r.headers["x-request-id"] == "caller-123"
```

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError: app.obs.logging` / header absent.

- [ ] **Step 3: Write `src/app/obs/logging.py`**
```python
# src/app/obs/logging.py
import contextvars
import logging

import structlog

request_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


def _add_request_id(_logger, _name, event_dict):
    rid = request_id_ctx.get()
    if rid is not None:
        event_dict["request_id"] = rid
    return event_dict


def configure_logging(*, json_logs: bool = True, level: str = "INFO") -> None:
    timestamper = structlog.processors.TimeStamper(fmt="iso")
    shared = [
        structlog.contextvars.merge_contextvars,
        _add_request_id,
        structlog.processors.add_log_level,
        timestamper,
    ]
    renderer = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(level)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None):
    return structlog.get_logger(name)
```

- [ ] **Step 4: Write `src/app/obs/middleware.py`**
```python
# src/app/obs/middleware.py
import uuid

from starlette.middleware.base import BaseHTTPMiddleware

from app.obs.logging import get_logger, request_id_ctx

logger = get_logger("http")


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        token = request_id_ctx.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_ctx.reset(token)
        response.headers["X-Request-ID"] = rid
        return response
```
(Security-headers middleware is added in Task 13 in the same module.)

- [ ] **Step 5: Write `src/app/obs/sentry.py`** (no-op if dep or DSN absent)
```python
# src/app/obs/sentry.py
from app.config import get_settings
from app.obs.logging import get_logger

logger = get_logger("sentry")


def init_sentry() -> bool:
    settings = get_settings()
    dsn = settings.sentry_dsn.get_secret_value() if settings.sentry_dsn else ""
    if not dsn:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
    except ImportError:
        logger.warning("sentry_dsn set but sentry-sdk not installed; skipping")
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=settings.environment,
        integrations=[FastApiIntegration()],
        traces_sample_rate=0.1,
    )
    return True
```

- [ ] **Step 6: Wire into `src/app/main.py`** — in `create_app`: call `configure_logging(json_logs=settings.log_json, level=settings.log_level)` then `init_sentry()`, and `app.add_middleware(RequestIDMiddleware)`. Add config fields: `log_level="INFO"`, `log_json=True`, `environment="dev"`, `sentry_dsn: SecretStr = SecretStr("")`. Add `structlog` to base deps; `sentry-sdk[fastapi]` to a `[project.optional-dependencies] prod` group.

- [ ] **Step 7: Run** `.venv/bin/pytest tests/obs/ -v` → green; full suite still green.

- [ ] **Step 8: Commit**
```bash
git add src/app/obs src/app/main.py src/app/config.py pyproject.toml tests/obs
git commit -m "feat: structlog JSON logging, request-id middleware, optional Sentry hook"
```

---

### Task 9: Rate limiting — redis token-bucket limiter + FastAPI deps

**Why:** Spec §6 *"Rate limiting per phone + per tenant"*; brief: *"slowapi or hand-rolled redis token bucket on auth + webhook endpoints."* A hand-rolled async redis token bucket works for both ASGI deps and (later) worker paths and avoids slowapi's sync-middleware coupling. Backs Task 5 (auth) and Task 12 (webhook).

**Files:**
- Create: `src/app/ratelimit/__init__.py`, `src/app/ratelimit/bucket.py`, `src/app/ratelimit/deps.py`
- Modify: `src/app/config.py` (`auth_rate_limit`, `webhook_rate_limit`, `rate_limit_enabled`)
- Modify: `tests/conftest.py` (fixture: point limiter at redis :6380 / fakeredis; clear keys per test)
- Create: `tests/ratelimit/__init__.py`, `tests/ratelimit/test_bucket.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ratelimit/test_bucket.py
import pytest

from app.ratelimit.bucket import TokenBucketLimiter


@pytest.fixture
async def limiter(redis_client):
    return TokenBucketLimiter(redis_client)


async def test_allows_up_to_capacity_then_blocks(limiter):
    key = "test:bucket:1"
    results = [await limiter.allow(key, capacity=3, refill_per_sec=0.0) for _ in range(5)]
    assert results[:3] == [(True, 0)] * 3 or all(r[0] for r in results[:3])
    assert results[3][0] is False  # 4th blocked
    assert results[3][1] > 0       # retry-after seconds


async def test_independent_keys(limiter):
    a = await limiter.allow("k:a", capacity=1, refill_per_sec=0.0)
    b = await limiter.allow("k:b", capacity=1, refill_per_sec=0.0)
    assert a[0] is True and b[0] is True
```

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError: app.ratelimit.bucket`.

- [ ] **Step 3: Write `src/app/ratelimit/bucket.py`** — atomic via a small Lua script (avoids check-then-set race):
```python
# src/app/ratelimit/bucket.py
import time

# tokens stored as (count, last_refill_ts) in a redis hash; atomic refill+consume.
_LUA = """
local key = KEYS[1]
local cap = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])
local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then tokens = cap; ts = now end
tokens = math.min(cap, tokens + (now - ts) * refill)
local allowed = 0
local retry = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  if refill > 0 then retry = math.ceil((1 - tokens) / refill) else retry = ttl end
end
redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', key, ttl)
return {allowed, retry}
"""


class TokenBucketLimiter:
    def __init__(self, redis_client):
        self._redis = redis_client
        self._sha = None

    async def _script(self):
        if self._sha is None:
            self._sha = await self._redis.script_load(_LUA)
        return self._sha

    async def allow(
        self, key: str, *, capacity: int, refill_per_sec: float, ttl: int = 3600
    ) -> tuple[bool, int]:
        sha = await self._script()
        now = time.time()
        res = await self._redis.evalsha(sha, 1, key, capacity, refill_per_sec, now, ttl)
        allowed, retry = int(res[0]), int(res[1])
        return (allowed == 1, retry)
```

- [ ] **Step 4: Write `src/app/ratelimit/deps.py`** — parse `"5/minute"` strings into `(capacity, refill_per_sec)`, build FastAPI dependencies that raise `HTTPException(429, headers={"Retry-After": str(retry)})`:
```python
# src/app/ratelimit/deps.py
from fastapi import HTTPException, Request

from app.config import get_settings
from app.ratelimit.bucket import TokenBucketLimiter

_UNIT_SECONDS = {"second": 1, "minute": 60, "hour": 3600}
_limiter: TokenBucketLimiter | None = None


def _parse(spec: str) -> tuple[int, float]:
    count, _, unit = spec.partition("/")
    secs = _UNIT_SECONDS[unit.strip().rstrip("s")]
    cap = int(count)
    return cap, cap / secs  # refill back to full over the window


def set_limiter(limiter: TokenBucketLimiter | None) -> None:
    global _limiter
    _limiter = limiter


async def _enforce(key: str, spec: str) -> None:
    settings = get_settings()
    if not settings.rate_limit_enabled or _limiter is None:
        return
    cap, refill = _parse(spec)
    ok, retry = await _limiter.allow(key, capacity=cap, refill_per_sec=refill)
    if not ok:
        raise HTTPException(429, "rate limit exceeded",
                            headers={"Retry-After": str(retry)})


async def rate_limit_auth(request: Request) -> None:
    settings = get_settings()
    ip = request.client.host if request.client else "unknown"
    body_phone = request.path_params.get("phone", "")  # or sniff from parsed body upstream
    await _enforce(f"auth:{ip}:{body_phone}", settings.auth_rate_limit)


async def rate_limit_webhook(request: Request) -> None:
    settings = get_settings()
    ip = request.client.host if request.client else "unknown"
    await _enforce(f"webhook:{ip}", settings.webhook_rate_limit)
```

- [ ] **Step 5: Config + app wiring** — add `auth_rate_limit="5/minute"`, `webhook_rate_limit="120/minute"`, `rate_limit_enabled=True`. In `main.create_app` lifespan, construct a redis client (`redis.asyncio.from_url(settings.redis_url)`) and `set_limiter(TokenBucketLimiter(client))`. Add a `redis_client` test fixture (real redis :6380 per the compose stack, or `fakeredis.aioredis`) to `tests/conftest.py`, and a conftest hook that calls `set_limiter(...)` for the app under test and `set_limiter(None)` / flushes keys between tests for isolation.

- [ ] **Step 6: Run** `.venv/bin/pytest tests/ratelimit/ -v` → green.

- [ ] **Step 7: Commit**
```bash
git add src/app/ratelimit src/app/config.py src/app/main.py tests/ratelimit tests/conftest.py
git commit -m "feat: redis token-bucket rate limiter + auth/webhook deps"
```

---
<<<APPEND-MARKER>>>
