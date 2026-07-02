from sqlalchemy import select

from app.outbox.models import OutboxMessage
from app.outbox.service import enqueue_message
from app.whatsapp.port import OutboundMessageType


async def test_enqueue_writes_pending_row(db_session, restaurant):
    await enqueue_message(
        db_session,
        restaurant_id=restaurant.id,
        to_phone="+971509876543",
        msg_type=OutboundMessageType.TEXT,
        payload={"body": "Your order is confirmed."},
        idempotency_key="conv-1-greeting",
    )
    await db_session.commit()

    row = (await db_session.execute(select(OutboxMessage))).scalar_one()
    assert row.status == "pending"
    assert row.to_phone == "+971509876543"
    assert row.payload["body"] == "Your order is confirmed."
    assert row.idempotency_key == "conv-1-greeting"
    assert row.attempts == 0


async def test_enqueue_duplicate_idempotency_key_is_idempotent(db_session, restaurant):
    """Re-enqueuing the same idempotency_key must NOT raise or duplicate — it
    returns the existing row. (Prod loop: the 30s dispatch sweep re-enqueued the
    same SLA-breach alert within one time bucket; a blind insert raised
    IntegrityError and crashed dispatch, rolling back the whole run.)"""
    first = await enqueue_message(
        db_session,
        restaurant_id=restaurant.id,
        to_phone="+971509876543",
        msg_type=OutboundMessageType.TEXT,
        payload={"body": "Hello"},
        idempotency_key="dup-key-1",
    )
    await db_session.commit()

    second = await enqueue_message(
        db_session,
        restaurant_id=restaurant.id,
        to_phone="+971509876543",
        msg_type=OutboundMessageType.TEXT,
        payload={"body": "Hello again"},
        idempotency_key="dup-key-1",
    )
    await db_session.commit()

    assert second.id == first.id  # same row, not a duplicate
    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    assert len(rows) == 1
    assert rows[0].payload["body"] == "Hello"  # first write wins, unchanged
