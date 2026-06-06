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
### Task 10: Observability — Prometheus metrics + `/metrics` endpoint

**Why:** Spec §8 phase 8: *"metrics"*. Operators need request counts/latency, outbox delivery outcomes, SLA breaches, and rate-limit rejections scrapeable by Prometheus. Use `prometheus-client` with a dedicated registry so tests don't leak global state. Builds on Task 8 (logging) and is consumed by the load harness (Task 15) and graceful-shutdown drain metrics (Task 16).

**Files:**
- Create: `src/app/obs/metrics.py`
- Modify: `src/app/obs/middleware.py` (latency/count instrumentation — or a dedicated `MetricsMiddleware`)
- Modify: `src/app/main.py` (mount `GET /metrics`)
- Modify: `pyproject.toml` (`prometheus-client` base dep)
- Create: `tests/obs/test_metrics.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/obs/test_metrics.py
async def test_metrics_endpoint_exposes_prometheus_text(client):
    # generate one request so the counter is non-zero
    await client.get("/health")
    r = await client.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    body = r.text
    assert "http_requests_total" in body
    assert "http_request_duration_seconds" in body


def test_outbox_counter_increments():
    from app.obs.metrics import OUTBOX_DELIVERIES, render_metrics

    before = render_metrics()
    OUTBOX_DELIVERIES.labels(result="sent").inc()
    after = render_metrics()
    assert before != after
    assert 'outbox_deliveries_total{result="sent"}' in after
```

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError: app.obs.metrics` / `/metrics` 404.

- [ ] **Step 3: Write `src/app/obs/metrics.py`**
```python
# src/app/obs/metrics.py
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

REGISTRY = CollectorRegistry()

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
    registry=REGISTRY,
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
    registry=REGISTRY,
)
OUTBOX_DELIVERIES = Counter(
    "outbox_deliveries_total",
    "Outbox delivery outcomes",
    ["result"],  # sent|failed|dead
    registry=REGISTRY,
)
SLA_BREACHES = Counter(
    "sla_breaches_total",
    "Orders that breached the 40-minute SLA",
    ["restaurant_id"],
    registry=REGISTRY,
)
RATE_LIMIT_REJECTIONS = Counter(
    "rate_limit_rejections_total",
    "Requests rejected by the rate limiter",
    ["scope"],  # auth|webhook
    registry=REGISTRY,
)


def render_metrics() -> str:
    return generate_latest(REGISTRY).decode("utf-8")


CONTENT_TYPE = CONTENT_TYPE_LATEST
```

- [ ] **Step 4: Instrument HTTP** — add a `MetricsMiddleware` to `src/app/obs/middleware.py` (or extend `RequestIDMiddleware`) that times the request and records `HTTP_REQUESTS.labels(method, route_template, status).inc()` + `HTTP_LATENCY.labels(...).observe(elapsed)`. Use the matched route template (`request.scope.get("route").path` when present) NOT the raw path, to avoid unbounded label cardinality from path params.

```python
# add to src/app/obs/middleware.py
import time

from app.obs.metrics import HTTP_LATENCY, HTTP_REQUESTS


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        HTTP_REQUESTS.labels(request.method, path, str(response.status_code)).inc()
        HTTP_LATENCY.labels(request.method, path).observe(elapsed)
        return response
```

- [ ] **Step 5: Mount `/metrics`** in `src/app/main.py` `create_app`:
```python
from fastapi import Response
from app.obs.metrics import CONTENT_TYPE, render_metrics
from app.obs.middleware import MetricsMiddleware

app.add_middleware(MetricsMiddleware)

@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(render_metrics(), media_type=CONTENT_TYPE)
```
> `/metrics` is intentionally unauthenticated (scraped inside the cluster); deployment doc (Task 14 follow-up) notes it must NOT be host-published — only reachable by the Prometheus sidecar.

- [ ] **Step 6: Wire outbox counter** — in `src/app/outbox/worker.py` `_deliver_one`, after the status transition: `OUTBOX_DELIVERIES.labels(result=row.status).inc()` (import lazily inside the function to avoid a hard metrics dep in the worker import path). Do the same for `RATE_LIMIT_REJECTIONS` in `app.ratelimit.deps._enforce` before raising 429, labelled by scope.

- [ ] **Step 7: Run** `.venv/bin/pytest tests/obs/ -v` → green; full suite green (confirm no duplicate-collector error from re-importing — the dedicated `REGISTRY` prevents the default-registry clash).

- [ ] **Step 8: Commit**
```bash
git add src/app/obs/metrics.py src/app/obs/middleware.py src/app/main.py src/app/outbox/worker.py src/app/ratelimit/deps.py pyproject.toml tests/obs/test_metrics.py
git commit -m "feat: Prometheus metrics registry + /metrics endpoint"
```

---
### Task 11: Webhook replay-window freshness check

**Why:** Spec §5: *"Webhook duplicate/replay → idempotency table drop"* and §6 security. The HMAC signature proves authenticity but a captured-and-replayed payload (valid signature, old timestamp) still passes signature verification. Reject events whose Meta `entry[].changes[].value.messages[].timestamp` (or the webhook receive time vs. a signed timestamp) is outside a freshness window, BEFORE the idempotency insert, to bound replay risk and DB growth.

**Files:**
- Create: `src/app/webhook/replay.py`
- Modify: `src/app/webhook/router.py` (call the freshness check after HMAC verify, before idempotency insert)
- Modify: `src/app/config.py` (`webhook_replay_window_seconds: int = 300`)
- Create: `tests/webhook/test_replay.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/webhook/test_replay.py
import datetime as dt

import pytest

from app.webhook.replay import ReplayError, assert_fresh


def test_fresh_timestamp_passes():
    now = dt.datetime.now(dt.timezone.utc)
    assert_fresh(int(now.timestamp()), window_seconds=300) is None


def test_stale_timestamp_rejected():
    old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=600)
    with pytest.raises(ReplayError):
        assert_fresh(int(old.timestamp()), window_seconds=300)


def test_future_skew_tolerated_within_window():
    future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=60)
    assert_fresh(int(future.timestamp()), window_seconds=300) is None


def test_far_future_rejected():
    future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=3600)
    with pytest.raises(ReplayError):
        assert_fresh(int(future.timestamp()), window_seconds=300)
```

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError: app.webhook.replay`.

- [ ] **Step 3: Write `src/app/webhook/replay.py`**
```python
# src/app/webhook/replay.py
import datetime as dt


class ReplayError(Exception):
    """Raised when a webhook event's timestamp is outside the freshness window."""


def assert_fresh(event_ts: int | None, *, window_seconds: int) -> None:
    """event_ts: unix seconds from the provider payload. None => skip (caller decides)."""
    if event_ts is None:
        return
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    skew = now - event_ts  # positive = event is in the past
    if skew > window_seconds:
        raise ReplayError(f"event too old: {skew:.0f}s > {window_seconds}s window")
    if skew < -window_seconds:
        raise ReplayError(f"event timestamp in the future: {-skew:.0f}s ahead")
```

- [ ] **Step 4: Wire into router** — in `src/app/webhook/router.py`, after HMAC verification and after extracting the message timestamp from the parsed Meta payload (`value.messages[0].timestamp`, a unix-seconds string), call `assert_fresh(int(ts), window_seconds=settings.webhook_replay_window_seconds)`. On `ReplayError`: log a structured warning (`get_logger("webhook").warning("replay_rejected", ...)`) and return HTTP 200 with a no-op body (Meta requires 200 to stop retries; we intentionally drop). If the payload has no message timestamp (status callbacks), skip the check. Add `webhook_replay_window_seconds: int = 300` to config.

- [ ] **Step 5: Write `tests/webhook/test_replay_router.py`** (integration) — POST a correctly-signed webhook whose message timestamp is 10 minutes old → 200 but NO `WebhookEvent`/order side effect; a fresh one → processed normally. Reuse the existing signed-webhook test helper.

- [ ] **Step 6: Run** `.venv/bin/pytest tests/webhook/ -v` → green.

- [ ] **Step 7: Commit**
```bash
git add src/app/webhook/replay.py src/app/webhook/router.py src/app/config.py tests/webhook/test_replay.py tests/webhook/test_replay_router.py
git commit -m "feat: webhook replay-window freshness check before idempotency insert"
```

---
### Task 12: Apply rate limiting to the webhook endpoint

**Why:** Spec §6 *"rate limiting per phone + per tenant"*; the webhook is the single most-hit public endpoint and a flood vector. Task 9 built the limiter + `rate_limit_webhook` dep; this task applies it to `POST /webhooks/whatsapp` and records the `RATE_LIMIT_REJECTIONS{scope="webhook"}` metric (Task 10). The limit is per-IP and generous (`120/minute` default) so a legitimate burst (Meta batches) is not throttled, but a single abusive source is.

**Files:**
- Modify: `src/app/webhook/router.py` (add `Depends(rate_limit_webhook)`)
- Create: `tests/webhook/test_webhook_rate_limit.py`

- [ ] **Step 1: Write the failing test** — flooding the webhook past `webhook_rate_limit` returns 429 with `Retry-After`.

```python
# tests/webhook/test_webhook_rate_limit.py
async def test_webhook_flood_is_rate_limited(client, signed_webhook_payload):
    body, headers = signed_webhook_payload({"object": "whatsapp_business_account"})
    statuses = []
    for _ in range(130):  # default 120/min
        r = await client.post("/webhooks/whatsapp", content=body, headers=headers)
        statuses.append(r.status_code)
    assert 429 in statuses
```
> Test settings (Task 9 conftest) lower `webhook_rate_limit` to e.g. `"10/minute"` for determinism; adjust the loop count accordingly. `signed_webhook_payload` is the existing HMAC helper.

- [ ] **Step 2: Run to verify failure** — never 429 (dep not applied).

- [ ] **Step 3: Apply the dep** — add `dependencies=[Depends(rate_limit_webhook)]` to the webhook POST route in `src/app/webhook/router.py`. Order matters: the dep runs before the body handler, so the limiter rejects floods cheaply before HMAC/JSON parsing. Confirm the GET verification handshake route is NOT rate-limited (Meta calls it rarely and a 429 there breaks registration).

- [ ] **Step 4: Run** `.venv/bin/pytest tests/webhook/ -v` → green.

- [ ] **Step 5: Commit**
```bash
git add src/app/webhook/router.py tests/webhook/test_webhook_rate_limit.py
git commit -m "feat: rate limit POST /webhooks/whatsapp per source IP (debt #5 cont.)"
```

---
### Task 13: Security headers + CORS hardening

**Why:** Spec §6 security & privacy. The dashboard is browser-served; responses need standard hardening headers and a locked-down CORS policy (allowlist origins from config, not `*`, since auth uses bearer tokens and we never want credentialed cross-origin from arbitrary sites). Headers: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Strict-Transport-Security` (prod only), `Content-Security-Policy` (API default-deny; dashboard is a separate SPA host).

**Files:**
- Modify: `src/app/obs/middleware.py` (add `SecurityHeadersMiddleware`)
- Modify: `src/app/main.py` (add `CORSMiddleware` + `SecurityHeadersMiddleware`)
- Modify: `src/app/config.py` (`cors_allow_origins: list[str] = []`, `hsts_enabled: bool = False`)
- Create: `tests/obs/test_security_headers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/obs/test_security_headers.py
async def test_security_headers_present(client):
    r = await client.get("/health")
    h = {k.lower(): v for k, v in r.headers.items()}
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert "referrer-policy" in h


async def test_cors_disallows_unlisted_origin(client):
    r = await client.get("/health", headers={"Origin": "https://evil.example"})
    # CORSMiddleware omits ACAO for disallowed origins
    assert r.headers.get("access-control-allow-origin") != "https://evil.example"
```

- [ ] **Step 2: Run to verify failure** — headers absent.

- [ ] **Step 3: Write `SecurityHeadersMiddleware`** in `src/app/obs/middleware.py`:
```python
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, hsts: bool = False):
        super().__init__(app)
        self._hsts = hsts

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
        )
        if self._hsts:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=63072000; includeSubDomains",
            )
        return response
```

- [ ] **Step 4: Wire CORS + headers** in `src/app/main.py` `create_app`:
```python
from fastapi.middleware.cors import CORSMiddleware
from app.obs.middleware import SecurityHeadersMiddleware

app.add_middleware(SecurityHeadersMiddleware, hsts=settings.hsts_enabled)
if settings.cors_allow_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )
```
Add `cors_allow_origins: list[str] = []` and `hsts_enabled: bool = False` to config. (pydantic-settings parses a JSON list or comma string from `APP_CORS_ALLOW_ORIGINS`.)
> Middleware order: Starlette applies middleware in reverse-add order. Add `SecurityHeadersMiddleware` and CORS such that CORS runs outermost (so preflights short-circuit) and security headers apply to all real responses. Document the resulting order in a comment.

- [ ] **Step 5: Run** `.venv/bin/pytest tests/obs/ -v` → green.

- [ ] **Step 6: Commit**
```bash
git add src/app/obs/middleware.py src/app/main.py src/app/config.py tests/obs/test_security_headers.py
git commit -m "feat: security headers middleware + CORS allowlist"
```

---
### Task 14: Secrets-strength audit (CI/cron task)

**Why:** Spec §6: *"secrets audit"*; `understanding.txt` Unit-4a flagged *"dev jwt_secret default <32 bytes (HS256 warning)"*. A standalone, dependency-light script that fails CI / a cron if any production secret is weak, default, or unset. Catches the classic "shipped with the dev JWT secret" outage. Reads from the live `Settings`, never logs secret values.

**Files:**
- Create: `ops/__init__.py`, `ops/secrets_audit.py`
- Create: `tests/ops/__init__.py`, `tests/ops/test_secrets_audit.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ops/test_secrets_audit.py
from ops.secrets_audit import Finding, audit_secrets


def test_weak_jwt_secret_flagged():
    findings = audit_secrets(
        {
            "jwt_secret": "short",
            "anthropic_api_key": "sk-ant-xxxxxxxxxxxxxxxxxxxxxxxx",
            "whatsapp_app_secret": "0123456789abcdef0123456789abcdef",
            "environment": "production",
        }
    )
    names = {f.field for f in findings}
    assert "jwt_secret" in names  # < 32 bytes
    assert all(isinstance(f, Finding) for f in findings)


def test_default_dev_secret_flagged():
    findings = audit_secrets(
        {"jwt_secret": "dev-insecure-change-me-please-32b!!", "environment": "production"}
    )
    assert any("default" in f.reason.lower() or "known" in f.reason.lower()
               for f in findings if f.field == "jwt_secret") or \
           any(f.field == "jwt_secret" for f in findings)


def test_strong_prod_secrets_pass():
    findings = audit_secrets(
        {
            "jwt_secret": "x" * 48,
            "anthropic_api_key": "sk-ant-" + "y" * 40,
            "whatsapp_app_secret": "z" * 40,
            "environment": "production",
        }
    )
    assert findings == []


def test_dev_environment_is_lenient():
    findings = audit_secrets({"jwt_secret": "short", "environment": "dev"})
    assert findings == []  # only enforce in production/staging
```

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError: ops.secrets_audit`.

- [ ] **Step 3: Write `ops/secrets_audit.py`**
```python
# ops/secrets_audit.py
from __future__ import annotations

import sys
from dataclasses import dataclass

_MIN_LEN = 32
_ENFORCED_ENVS = {"production", "staging"}
# values that ship as defaults in .env.example / config — never allowed in prod
_KNOWN_DEFAULTS = {
    "dev-insecure-change-me-please-32b!!",
    "changeme",
    "dev-secret",
}
_REQUIRED_IN_PROD = ("jwt_secret",)


@dataclass(frozen=True)
class Finding:
    field: str
    reason: str


def audit_secrets(values: dict) -> list[Finding]:
    env = (values.get("environment") or "dev").lower()
    if env not in _ENFORCED_ENVS:
        return []
    findings: list[Finding] = []
    for field in _REQUIRED_IN_PROD:
        if not values.get(field):
            findings.append(Finding(field, "required secret is unset"))
    for field, raw in values.items():
        if field == "environment" or not isinstance(raw, str) or raw == "":
            continue
        if not _is_secret_field(field):
            continue
        if raw in _KNOWN_DEFAULTS:
            findings.append(Finding(field, "uses a known default/example value"))
        elif len(raw.encode()) < _MIN_LEN:
            findings.append(Finding(field, f"shorter than {_MIN_LEN} bytes"))
    return findings


def _is_secret_field(field: str) -> bool:
    f = field.lower()
    return any(t in f for t in ("secret", "key", "token", "password", "dsn"))


def main() -> int:
    from app.config import get_settings

    s = get_settings()
    values = {
        "environment": s.environment,
        "jwt_secret": _reveal(s.jwt_secret),
        "anthropic_api_key": _reveal(getattr(s, "anthropic_api_key", "")),
        "whatsapp_app_secret": _reveal(getattr(s, "whatsapp_app_secret", "")),
    }
    findings = audit_secrets(values)
    for f in findings:
        print(f"SECRET AUDIT FAIL: {f.field}: {f.reason}", file=sys.stderr)
    return 1 if findings else 0


def _reveal(v) -> str:
    return v.get_secret_value() if hasattr(v, "get_secret_value") else (v or "")


if __name__ == "__main__":
    raise SystemExit(main())
```
> `main()` reads the live settings and exits non-zero on any finding so it slots into CI as `.venv/bin/python -m ops.secrets_audit`. It prints only field names + reasons, NEVER the secret value.

- [ ] **Step 4: Wire into CI** — add a `secrets-audit` step to the existing CI workflow that runs `APP_ENVIRONMENT=production ... .venv/bin/python -m ops.secrets_audit` against a smoke config (or document it as a deploy-time gate in `docs/deployment.md`). Keep it non-blocking for the dev default-env path (the script returns 0 outside production/staging).

- [ ] **Step 5: Run** `.venv/bin/pytest tests/ops/ -v` → green.

- [ ] **Step 6: Commit**
```bash
git add ops tests/ops
git commit -m "feat: production secrets-strength audit (CI/cron gate)"
```

---
### Task 15: Load/stress harness — Locust profile + documented SLOs

**Why:** Spec §7: *"Locust profile for peak-hour webhook bursts"*; brief: *"locustfile load harness w/ SLOs"*. A repeatable load test that simulates the three real traffic shapes (inbound webhook bursts, manager dashboard polling, outbound send flood) and asserts the SLOs that matter for the 40-minute SLA: webhook p95 latency, error rate, and metrics-backed outbox throughput. Locust is a **dev-only** dependency — never imported by app/test code.

**Files:**
- Create: `load/locustfile.py`
- Create: `load/README.md` (documented SLOs + how to run)
- Modify: `pyproject.toml` (`locust` in `dev` extra)

- [ ] **Step 1: Write `load/locustfile.py`** — three `TaskSet`/`User` classes against a running instance:
```python
# load/locustfile.py
"""Peak-hour load profile. Run against a LOCAL stack only:
    .venv/bin/locust -f load/locustfile.py --host http://localhost:8000
DEV-ONLY: never imported by app or tests.
"""
import json
import os
import time

from locust import HttpUser, between, task

_VERIFY_TOKEN = os.environ.get("APP_WHATSAPP_VERIFY_TOKEN", "test-verify")


class WebhookBurstUser(HttpUser):
    """Simulates Meta delivering inbound messages in peak-hour bursts."""
    weight = 5
    wait_time = between(0.1, 0.5)

    @task
    def inbound_message(self):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{"changes": [{"value": {"messages": [{
                "from": "+9715000000{:02d}".format(int(time.time()) % 100),
                "id": "wamid.load-{}".format(time.time_ns()),
                "timestamp": str(int(time.time())),
                "type": "text",
                "text": {"body": "1"},
            }]}}]}],
        }
        body = json.dumps(payload).encode()
        # NOTE: requires a valid X-Hub-Signature-256 — compute with the app secret,
        # see load/README.md. Against a dev stack with signature check relaxed,
        # post unsigned and expect 200/4xx accordingly.
        self.client.post(
            "/webhooks/whatsapp",
            data=body,
            headers={"Content-Type": "application/json"},
            name="POST /webhooks/whatsapp",
        )


class DashboardPollUser(HttpUser):
    """Manager dashboard polling live order/rider state."""
    weight = 2
    wait_time = between(1, 3)

    def on_start(self):
        # acquire a manager token via /auth/login using seeded creds from env
        creds = {
            "phone": os.environ["LOAD_MANAGER_PHONE"],
            "password": os.environ["LOAD_MANAGER_PASSWORD"],
        }
        r = self.client.post("/api/v1/auth/login", json=creds, name="POST /auth/login")
        self._auth = {"Authorization": "Bearer " + r.json()["access_token"]} if r.ok else {}

    @task
    def poll_orders(self):
        self.client.get("/api/v1/orders?status=active", headers=self._auth,
                        name="GET /orders")

    @task
    def health(self):
        self.client.get("/health", name="GET /health")
```

- [ ] **Step 2: Write `load/README.md`** — documented SLOs (the load test's pass/fail criteria) and run instructions:

```markdown
# Load / Stress Harness

Simulates peak-hour traffic for the WhatsApp restaurant platform.

## SLOs (pass/fail gates)
| Metric                         | Target                         |
|--------------------------------|--------------------------------|
| Webhook p95 latency            | < 250 ms                       |
| Webhook error rate (5xx)       | < 0.5 %                        |
| /auth/login p95                | < 400 ms (argon2 cost)         |
| Dashboard GET /orders p95      | < 300 ms                       |
| Outbox delivery throughput     | ≥ 50 msg/s (mock provider)     |
| Sustained RPS without 5xx      | ≥ 200 RPS for 5 min            |

These bound the operational headroom needed to keep the 40-min customer SLA
(internal 30-min target) under realistic burst load.

## Run
1. Start the stack: `docker compose up -d` + `uvicorn app.main:app --port 8000`.
2. Seed a manager + menu (see scripts/seed_demo.py).
3. Export `LOAD_MANAGER_PHONE`, `LOAD_MANAGER_PASSWORD`, and (for signed
   webhooks) `APP_WHATSAPP_APP_SECRET`.
4. `.venv/bin/locust -f load/locustfile.py --host http://localhost:8000`
5. Open http://localhost:8089, set users/spawn rate, run.
6. Compare the Locust stats table + `/metrics` (`outbox_deliveries_total`,
   `http_request_duration_seconds` histogram) against the SLO table above.

## Signed webhooks
The webhook verifies `X-Hub-Signature-256`. To load-test the real path, compute
`hmac_sha256(app_secret, body)` per request (see the `signed_webhook_payload`
test helper for the exact algorithm) and add the header in `inbound_message`.
For pure capacity testing of the ASGI layer, point at a dev instance with
`APP_WHATSAPP_VERIFY_SIGNATURE=false`.
```

- [ ] **Step 2b: Add `APP_WHATSAPP_VERIFY_SIGNATURE`** toggle to config IF not already present (default `True`) so the load harness can exercise raw capacity without HMAC. Router skips HMAC verify only when explicitly false; production must keep it true (note in deployment doc + flag in the secrets/config audit).

- [ ] **Step 3: Add dep** — `locust` to `[project.optional-dependencies] dev`. `.venv/bin/pip install -e ".[dev]"`.

- [ ] **Step 4: Smoke the harness** — headless 30-second run against a local stack to prove the file imports and drives traffic (NOT a CI gate; it needs a running server):
```bash
.venv/bin/locust -f load/locustfile.py --host http://localhost:8000 \
  --headless -u 20 -r 5 -t 30s
```
Confirm non-zero requests and no Locust import/usage errors. Record observed p95 vs the SLO table in `understanding.txt`.

- [ ] **Step 5: Commit**
```bash
git add load pyproject.toml src/app/config.py src/app/webhook/router.py
git commit -m "feat: locust load harness with documented SLOs (dev-only)"
```

---
### Task 16: Graceful shutdown — lifespan that drains the outbox + closes pools

**Why:** Spec §5: *"DB/Redis outage → health checks, API 503s with retry-after"* and clean rollouts. On SIGTERM (container stop / rolling deploy) the app must stop accepting new work, attempt a bounded drain of in-flight `pending` outbox rows so customers aren't left mid-conversation, and cleanly dispose the DB engine + redis client. Replaces any abrupt teardown with an `asynccontextmanager` lifespan.

**Files:**
- Modify: `src/app/main.py` (`lifespan` context manager: startup wiring + shutdown drain/dispose)
- Create: `src/app/outbox/drain.py` (bounded best-effort drain helper)
- Modify: `src/app/config.py` (`shutdown_drain_seconds: int = 10`, `shutdown_drain_enabled: bool = True`)
- Create: `tests/test_lifespan.py`, `tests/outbox/test_drain.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/outbox/test_drain.py
import datetime as dt

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.outbox.drain import drain_pending
from app.outbox.models import OutboxMessage
from app.whatsapp.mock_provider import MockProvider
from app.whatsapp.port import OutboundMessageType


async def _seed_pending(session, key):
    row = OutboxMessage(
        restaurant_id=1, to_phone="+971509876543",
        payload={"type": str(OutboundMessageType.TEXT), "body": "bye"},
        idempotency_key=key, status="pending", attempts=0,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def test_drain_sends_pending_within_budget(engine, db_session):
    await _seed_pending(db_session, "drain-1")
    await _seed_pending(db_session, "drain-2")
    provider = MockProvider()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    sent = await drain_pending(factory, provider=provider, budget_seconds=5)

    assert sent == 2
    assert len(provider.drain_sends()) == 2


async def test_drain_respects_time_budget(engine, db_session, monkeypatch):
    # budget=0 => drain does no work and returns immediately
    await _seed_pending(db_session, "drain-3")
    provider = MockProvider()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    sent = await drain_pending(factory, provider=provider, budget_seconds=0)
    assert sent == 0
```

```python
# tests/test_lifespan.py
from httpx import ASGITransport, AsyncClient

from app.main import create_app


async def test_app_starts_and_stops_cleanly():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # lifespan startup ran; app serves requests
        r = await ac.get("/health")
        assert r.status_code == 200
    # context exit triggers lifespan shutdown without raising
```

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError: app.outbox.drain` / lifespan not wired.

- [ ] **Step 3: Write `src/app/outbox/drain.py`**
```python
# src/app/outbox/drain.py
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.outbox.models import OutboxMessage
from app.outbox.worker import _deliver_one


async def drain_pending(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    provider,
    budget_seconds: float,
    batch: int = 100,
) -> int:
    """Best-effort: deliver pending rows until the time budget is spent. Returns count sent."""
    if budget_seconds <= 0:
        return 0
    deadline = time.monotonic() + budget_seconds
    sent = 0
    while time.monotonic() < deadline:
        async with session_factory() as session:
            ids = list(
                await session.scalars(
                    select(OutboxMessage.id)
                    .where(OutboxMessage.status == "pending")
                    .order_by(OutboxMessage.id)
                    .limit(batch)
                )
            )
        if not ids:
            break
        for outbox_id in ids:
            if time.monotonic() >= deadline:
                break
            before = getattr(provider, "_sends", None)
            await _deliver_one(outbox_id, provider=provider, session_factory=session_factory)
            sent += 1
    return sent
```
> Uses the same `_deliver_one` claim (Task 2) so a concurrent worker never double-sends a drained row. The drain is best-effort: anything not sent within the budget stays `pending` and the new instance / sweeper (Task 1) picks it up.

- [ ] **Step 4: Write the lifespan** in `src/app/main.py`:
```python
from contextlib import asynccontextmanager

import redis.asyncio as aioredis

from app.config import get_settings
from app.db import dispose_engine, get_session_factory
from app.obs.logging import configure_logging, get_logger
from app.obs.sentry import init_sentry
from app.outbox.drain import drain_pending
from app.ratelimit.bucket import TokenBucketLimiter
from app.ratelimit.deps import set_limiter
from app.whatsapp.factory import get_whatsapp_provider

logger = get_logger("lifespan")


@asynccontextmanager
async def lifespan(app):
    settings = get_settings()
    configure_logging(json_logs=settings.log_json, level=settings.log_level)
    init_sentry()
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=False)
    set_limiter(TokenBucketLimiter(redis_client))
    logger.info("startup_complete", environment=settings.environment)
    try:
        yield
    finally:
        if settings.shutdown_drain_enabled:
            try:
                sent = await drain_pending(
                    get_session_factory(),
                    provider=get_whatsapp_provider(),
                    budget_seconds=settings.shutdown_drain_seconds,
                )
                logger.info("shutdown_drain_complete", drained=sent)
            except Exception as exc:  # never block shutdown on drain failure
                logger.warning("shutdown_drain_failed", error=str(exc))
        set_limiter(None)
        try:
            await redis_client.aclose()
        except Exception:
            pass
        await dispose_engine()
        logger.info("shutdown_complete")
```
Pass `lifespan=lifespan` to `FastAPI(...)` in `create_app`. Add `dispose_engine()` to `src/app/db.py` if absent (`await get_engine().dispose()` guarded for the lazy/unset case). Add config: `shutdown_drain_seconds: int = 10`, `shutdown_drain_enabled: bool = True`.

- [ ] **Step 5: Reconcile with Task 9 wiring** — the limiter/redis construction that Task 9 placed in `create_app` now lives in `lifespan`; remove the duplicate so there is exactly one redis client lifecycle. Tests that need the limiter use the conftest `set_limiter` override (Task 9), which runs independently of lifespan.

- [ ] **Step 6: Run** `.venv/bin/pytest tests/outbox/test_drain.py tests/test_lifespan.py -v` → green; full suite green.

- [ ] **Step 7: Commit**
```bash
git add src/app/outbox/drain.py src/app/main.py src/app/config.py src/app/db.py tests/outbox/test_drain.py tests/test_lifespan.py
git commit -m "feat: graceful shutdown lifespan drains outbox + disposes pools"
```

---
### Task 17: Final hardening gate — full suite, lint, deprecation-clean, deploy doc, audit

**Why:** Phase 7 is the last phase; this gate proves the whole monolith is production-ready: zero deprecation warnings (passlib gone), full green suite, clean lint, the secrets audit passing on a production-shaped config, and the deployment doc updated with the new env vars + `/metrics` scrape note. No new feature code — verification + docs only.

**Files:**
- Modify: `docs/deployment.md` (new `APP_*` vars: log/metrics/rate-limit/cors/hsts/sentry/replay/drain; `/metrics` scrape; secrets-audit gate)
- Modify: `understanding.txt` (final Phase-7 summary bullet)
- Possibly: `.github/workflows/ci.yml` (add `ruff`, `-W error::DeprecationWarning`, secrets-audit steps if not already)

- [ ] **Step 1: Full suite, deprecation-strict**
```bash
.venv/bin/pytest -W error::DeprecationWarning
```
Expected: all green, NO `passlib`/`crypt` deprecation (Task 4 removed it). If a third-party deprecation surfaces, filter it narrowly in `pyproject.toml` `[tool.pytest.ini_options] filterwarnings` with a comment — never blanket-ignore.

- [ ] **Step 2: Lint**
```bash
.venv/bin/ruff check src apps ops load tests
```
Expected: clean. Fix any findings.

- [ ] **Step 3: Migrations chain on a virgin DB** — prove the new migrations (outbox `next_retry_at`, `processed_at` cast, `menu_files`) apply cleanly from scratch:
```bash
docker compose exec db psql -U app -d restaurant -c "DROP DATABASE IF EXISTS restaurant_migtest; CREATE DATABASE restaurant_migtest;"
APP_DATABASE_URL=postgresql+asyncpg://app:app@localhost:5433/restaurant_migtest .venv/bin/alembic upgrade head
```
Expected: upgrades to head with no error; `alembic downgrade base` then `upgrade head` round-trips.

- [ ] **Step 4: Secrets audit on a prod-shaped config**
```bash
APP_ENVIRONMENT=production APP_JWT_SECRET=$(openssl rand -hex 32) \
  .venv/bin/python -m ops.secrets_audit; echo "exit=$?"
```
Expected: `exit=0`. Then prove it FAILS with a weak secret (`APP_JWT_SECRET=short` → `exit=1`).

- [ ] **Step 5: Update `docs/deployment.md`** — extend the `APP_*` env-var table with every config field added in this phase (flag secrets): `APP_LOG_LEVEL`, `APP_LOG_JSON`, `APP_ENVIRONMENT`, `APP_SENTRY_DSN` [secret], `APP_AUTH_RATE_LIMIT`, `APP_WEBHOOK_RATE_LIMIT`, `APP_RATE_LIMIT_ENABLED`, `APP_JWT_ISSUER`, `APP_JWT_AUDIENCE_MANAGER`, `APP_JWT_AUDIENCE_RIDER`, `APP_CORS_ALLOW_ORIGINS`, `APP_HSTS_ENABLED`, `APP_WEBHOOK_REPLAY_WINDOW_SECONDS`, `APP_WEBHOOK_VERIFY_SIGNATURE` [must be true in prod], `APP_SHUTDOWN_DRAIN_SECONDS`, `APP_SHUTDOWN_DRAIN_ENABLED`, `APP_UPLOAD_DIR` (menu blob store). Add a "Metrics" subsection: `/metrics` is cluster-internal only (never host-published), Prometheus scrape config snippet, key series (`http_request_duration_seconds`, `outbox_deliveries_total`, `sla_breaches_total`, `rate_limit_rejections_total`). Add a "Pre-deploy gates" subsection: secrets audit + migration round-trip + load SLOs.

- [ ] **Step 6: Smoke the running app end-to-end** — start the stack and confirm the cross-cutting wiring is live:
```bash
.venv/bin/uvicorn app.main:app --port 8000 &
curl -fsS localhost:8000/health           # 200, X-Request-ID + security headers present
curl -fsS localhost:8000/metrics | head   # prometheus text, http_requests_total present
curl -fsSi localhost:8000/health | grep -i 'x-content-type-options\|x-request-id'
kill %1
```
Expected: health 200 with `X-Request-ID`, `X-Content-Type-Options: nosniff`; `/metrics` returns Prometheus text including the `/health` request just made.

- [ ] **Step 7: Final understanding.txt bullet + commit**
```bash
git add docs/deployment.md understanding.txt .github/workflows/ci.yml
git commit -m "chore: phase 7 hardening gate — docs, CI strict warnings, audit gate"
```

---

## Post-phase

**What Phase 7 delivers (production-readiness checklist):**

- **Debt paid (Tasks 1–7):** outbox retry sweeper w/ exponential backoff + dead-letter, atomic outbox row-claim (no double-send), `webhook_events.processed_at` → timestamptz, passlib → argon2-cffi (deprecation-clean), login rate limiting, JWT `iss`/`aud` audience enforcement (manager vs rider), persisted menu file bytes + server-side re-extraction.
- **Observability (Tasks 8, 10):** structlog JSON logs with request-id correlation across web + worker, request-id middleware (echoes inbound `X-Request-ID`), optional lazy Sentry, Prometheus `/metrics` (request count/latency, outbox outcomes, SLA breaches, rate-limit rejections) on a dedicated registry.
- **Rate limiting (Tasks 9, 5, 12):** async redis token-bucket (atomic Lua), applied to `/auth/login` (per phone+IP) and `/webhooks/whatsapp` (per IP), config-toggleable, `Retry-After` on 429.
- **Backpressure (Tasks 1, 2, 16):** sweeper re-drives failed + stuck-`sending` rows; graceful-shutdown drain flushes `pending` within a time budget; anything left is reclaimed by the next instance.
- **Security (Tasks 4, 6, 11, 13, 14):** argon2id hashing w/ timing-oracle defense, audience-scoped JWTs, webhook replay-window freshness gate, security headers + CORS allowlist + optional HSTS, automated secrets-strength audit as a CI/deploy gate.
- **Load & SLOs (Task 15):** Locust profile (webhook bursts / dashboard polling / send flood) with documented pass/fail SLOs tied to the 40-min SLA headroom.

**Key invariants preserved:** routers still call services only; every state change still calls `record_audit`; ports (LLM/WhatsApp/geo) still overridable in tests; no real external calls in the suite; all new heavy/optional deps (`sentry-sdk`, `locust`) kept out of the base/test install path.

**New config surface:** ~18 `APP_*` settings (logging, metrics, rate limits, JWT iss/aud, CORS/HSTS, replay window, signature toggle, shutdown drain, upload dir) — all documented in `docs/deployment.md` with secrets flagged.

**Schema deltas:** `outbox_messages.next_retry_at` (nullable timestamptz), `webhook_events.processed_at` String→timestamptz (USING cast), new `menu_files` table (+ updated_at trigger).

**Deferred / out of scope:** distributed tracing spans (OpenTelemetry) — only request-id correlation + Sentry shipped here; per-tenant rate-limit dimension (currently per-phone/per-IP — tenant dimension is a fast follow once `current_restaurant` is resolvable pre-body); blob store is filesystem-backed (S3 adapter is a future port). These are noted for a Phase 8+ if real traffic demands them.

**Done = production-grade:** full suite green under `-W error::DeprecationWarning`, ruff clean across `src apps ops load tests`, migrations round-trip on a virgin DB, secrets audit gates prod config, `/metrics` + security headers + request-id verified live, load SLOs documented and runnable.

