"""A failed send must record WHY.

Prod (La Cafe, 7 Aug 2026): the WhatsApp catalogue card failed for every customer
who said "hi". The row read ``status='failed'`` and nothing else — Meta had told us
the reason and we threw it away, so diagnosing it meant replaying Graph calls by
hand. The cause turned out to be one line in the error body we never stored.

Also covers the sibling defect the same incident exposed: ``failed`` rows are
invisible to the sweeper, which only ever looked at ``pending``. A row that failed
once with attempts below the cap was stranded forever — 8 of them, the oldest from
30 July, none ever retried.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.outbox.models import OutboxMessage
from app.outbox.worker import _deliver_one, _sweep_stale_pending
from app.whatsapp.port import OutboundMessageType


def _factory(db_session):
    return async_sessionmaker(
        bind=db_session.bind,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )


async def _seed(db_session, restaurant_id, *, key: str, status: str = "pending",
                attempts: int = 0, minutes_ago: int | None = None) -> OutboxMessage:
    row = OutboxMessage(
        restaurant_id=restaurant_id,
        to_phone="+971509999501",
        payload={"type": str(OutboundMessageType.TEXT), "body": "hello"},
        idempotency_key=key,
        status=status,
        attempts=attempts,
    )
    db_session.add(row)
    await db_session.flush()
    if minutes_ago is not None:
        old = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).replace(tzinfo=None)
        await db_session.execute(
            text("UPDATE outbox_messages SET updated_at = :ts WHERE id = :id"),
            {"ts": old, "id": row.id},
        )
    await db_session.commit()
    await db_session.refresh(row)
    return row


class _Boom:
    """A provider whose send fails the way Meta's API does."""

    def __init__(self, exc):
        self._exc = exc

    async def send(self, msg, *, phone_number_id=None, access_token=None):
        raise self._exc


def _meta_error(code: int, message: str) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://graph.facebook.com/v21.0/1/messages")
    response = httpx.Response(
        400, json={"error": {"code": code, "message": message}}, request=request
    )
    return httpx.HTTPStatusError(message, request=request, response=response)


async def test_failed_send_records_the_reason(db_session, restaurant):
    """A retryable failure stores Meta's message so the row explains itself.

    131000 is a generic send failure — transient, unlike 131009 (wrong catalog) or
    131047 (window closed), which are permanent and handled separately below."""
    row = await _seed(db_session, restaurant.id, key="lasterr-retryable")
    exc = _meta_error(131000, "Something went wrong")

    await _deliver_one(row.id, provider=_Boom(exc), session_factory=_factory(db_session))
    await db_session.refresh(row)

    assert row.status == "failed"
    assert row.last_error, "the failure reason must be persisted, not just logged"
    assert "131000" in row.last_error
    assert "Something went wrong" in row.last_error


async def test_permanently_dead_send_records_the_reason(db_session, restaurant):
    """A permanent Meta rejection keeps its reason too, not only the fail_reason tag."""
    row = await _seed(db_session, restaurant.id, key="lasterr-permanent")
    exc = _meta_error(131047, "Re-engagement message")

    await _deliver_one(row.id, provider=_Boom(exc), session_factory=_factory(db_session))
    await db_session.refresh(row)

    assert row.status == "dead"
    assert row.payload.get("fail_reason") == "24h_window"
    assert "131047" in (row.last_error or "")


async def test_success_clears_a_previous_error(db_session, restaurant):
    """A row that fails then succeeds must not keep showing the stale error."""
    row = await _seed(db_session, restaurant.id, key="lasterr-cleared")
    await db_session.execute(
        text("UPDATE outbox_messages SET last_error = 'old failure' WHERE id = :id"),
        {"id": row.id},
    )
    await db_session.commit()

    class _Ok:
        async def send(self, msg, *, phone_number_id=None, access_token=None):
            return "wamid.OK"

    await _deliver_one(row.id, provider=_Ok(), session_factory=_factory(db_session))
    await db_session.refresh(row)

    assert row.status == "sent"
    assert row.last_error is None


async def test_error_text_is_bounded(db_session, restaurant):
    """A huge error body must not bloat the row."""
    row = await _seed(db_session, restaurant.id, key="lasterr-bounded")
    exc = _meta_error(131009, "x" * 5000)

    await _deliver_one(row.id, provider=_Boom(exc), session_factory=_factory(db_session))
    await db_session.refresh(row)

    assert row.last_error is not None
    assert len(row.last_error) <= 512


async def test_sweeper_retries_a_stale_failed_row(db_session, restaurant):
    """``failed`` rows under the attempt cap are orphans too — the sweeper must
    pick them up. Before this, only ``pending`` was ever recovered."""
    row = await _seed(
        db_session, restaurant.id, key="lasterr-sweep-failed",
        status="failed", attempts=1, minutes_ago=10,
    )

    with patch("app.outbox.worker.deliver_outbox_message"):
        stale_ids = await _sweep_stale_pending(_factory(db_session))

    assert row.id in stale_ids


async def test_sweeper_still_skips_exhausted_failed_row(db_session, restaurant):
    """A failed row that burned its attempts stays dead — no infinite retrying."""
    row = await _seed(
        db_session, restaurant.id, key="lasterr-sweep-exhausted",
        status="failed", attempts=3, minutes_ago=10,
    )

    with patch("app.outbox.worker.deliver_outbox_message"):
        stale_ids = await _sweep_stale_pending(_factory(db_session))

    assert row.id not in stale_ids
