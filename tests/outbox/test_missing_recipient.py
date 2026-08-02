"""A restaurant with no WhatsApp number must not lose dispatch entirely.

``outbox_messages.to_phone`` is NOT NULL. The dispatch sweep addresses its
manager alerts to ``restaurant.phone``, which is empty until a WhatsApp number is
connected, so the INSERT raised NotNullViolationError. That poisoned the session
and aborted the whole sweep: seen live on restaurant 3, every 45 seconds, no
rider assigned to anything, because an advisory SLA alert could not be queued.
"""

import pytest
from sqlalchemy import func, select

from app.outbox.models import OutboxMessage
from app.outbox.service import enqueue_message
from app.whatsapp.port import OutboundMessageType


async def _outbox_count(db_session, restaurant_id: int) -> int:
    return await db_session.scalar(
        select(func.count())
        .select_from(OutboxMessage)
        .where(OutboxMessage.restaurant_id == restaurant_id)
    )


@pytest.mark.anyio
@pytest.mark.parametrize("phone", [None, "", "   "])
async def test_no_recipient_is_skipped_not_raised(db_session, restaurant, phone):
    before = await _outbox_count(db_session, restaurant.id)

    row = await enqueue_message(
        db_session,
        restaurant_id=restaurant.id,
        to_phone=phone,
        msg_type=OutboundMessageType.TEXT,
        payload={"body": "SLA breach alert"},
        idempotency_key=f"no-phone-{phone!r}",
    )

    assert row is None
    # The session must still be usable — that is the whole point.
    await db_session.flush()
    assert await _outbox_count(db_session, restaurant.id) == before


@pytest.mark.anyio
async def test_a_real_number_still_enqueues(db_session, restaurant):
    row = await enqueue_message(
        db_session,
        restaurant_id=restaurant.id,
        to_phone="+971500000123",
        msg_type=OutboundMessageType.TEXT,
        payload={"body": "SLA breach alert"},
        idempotency_key="has-phone-1",
        mirror_rider_conversation=False,
        mirror_customer_conversation=False,
    )
    assert row is not None
    await db_session.flush()
    assert row.to_phone == "+971500000123"
