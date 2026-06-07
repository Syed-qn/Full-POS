"""Tests for the outbox orphan-recovery sweeper (sweep_failed_outbox beat task)."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.outbox.models import OutboxMessage
from app.outbox.worker import _sweep_stale_pending
from app.whatsapp.port import OutboundMessageType


async def _seed_stale_pending(session, restaurant_id, *, minutes_ago: int = 10) -> OutboxMessage:
    """Seed an outbox row with status=pending and force updated_at to be old."""
    row = OutboxMessage(
        restaurant_id=restaurant_id,
        to_phone="+971509999001",
        payload={"type": str(OutboundMessageType.TEXT), "body": "stale message"},
        idempotency_key=f"sweeper-test-stale-{minutes_ago}",
        status="pending",
        attempts=0,
    )
    session.add(row)
    await session.flush()

    # Force updated_at to a past timestamp so the sweeper sees it as stale.
    # TimestampMixin stores naive UTC, so we pass a naive datetime here.
    old_ts = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).replace(tzinfo=None)
    await session.execute(
        text("UPDATE outbox_messages SET updated_at = :ts WHERE id = :id"),
        {"ts": old_ts, "id": row.id},
    )
    await session.commit()
    await session.refresh(row)
    return row


async def test_sweep_finds_stale_pending_row(db_session, restaurant):
    """Sweeper re-dispatches a pending row whose updated_at is older than 5 minutes."""
    row = await _seed_stale_pending(db_session, restaurant.id, minutes_ago=10)
    assert row.status == "pending"

    factory = async_sessionmaker(
        bind=db_session.bind,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    dispatched_ids: list[int] = []

    # Patch deliver_outbox_message.apply_async to capture calls without real Celery.
    with patch("app.outbox.worker.deliver_outbox_message") as mock_task:
        mock_task.apply_async = lambda args: dispatched_ids.extend(args)
        stale_ids = await _sweep_stale_pending(factory)

    assert row.id in stale_ids, f"Expected row {row.id} in stale_ids, got {stale_ids}"


async def test_sweep_skips_fresh_pending_row(db_session, restaurant):
    """Sweeper ignores a pending row updated less than 5 minutes ago."""
    row = OutboxMessage(
        restaurant_id=restaurant.id,
        to_phone="+971509999002",
        payload={"type": str(OutboundMessageType.TEXT), "body": "fresh message"},
        idempotency_key="sweeper-test-fresh",
        status="pending",
        attempts=0,
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)

    factory = async_sessionmaker(
        bind=db_session.bind,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    with patch("app.outbox.worker.deliver_outbox_message"):
        stale_ids = await _sweep_stale_pending(factory)

    assert row.id not in stale_ids


async def test_sweep_skips_sent_row(db_session, restaurant):
    """Sweeper ignores rows that are already terminal (sent/dead)."""
    row = await _seed_stale_pending(db_session, restaurant.id, minutes_ago=10)
    # Manually mark sent
    await db_session.execute(
        text("UPDATE outbox_messages SET status = 'sent' WHERE id = :id"), {"id": row.id}
    )
    await db_session.commit()

    factory = async_sessionmaker(
        bind=db_session.bind,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    with patch("app.outbox.worker.deliver_outbox_message"):
        stale_ids = await _sweep_stale_pending(factory)

    assert row.id not in stale_ids


async def test_sweep_skips_exhausted_attempts_row(db_session, restaurant):
    """Sweeper ignores stale pending rows that have reached max attempts."""
    row = await _seed_stale_pending(db_session, restaurant.id, minutes_ago=10)
    # Set attempts to _MAX_ATTEMPTS (3)
    await db_session.execute(
        text("UPDATE outbox_messages SET attempts = 3 WHERE id = :id"), {"id": row.id}
    )
    await db_session.commit()

    factory = async_sessionmaker(
        bind=db_session.bind,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    with patch("app.outbox.worker.deliver_outbox_message"):
        stale_ids = await _sweep_stale_pending(factory)

    assert row.id not in stale_ids
