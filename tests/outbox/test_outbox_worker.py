from sqlalchemy.ext.asyncio import async_sessionmaker

from app.outbox.models import OutboxMessage
from app.outbox.worker import _deliver_one
from app.whatsapp.mock_provider import MockProvider
from app.whatsapp.port import OutboundMessageType


async def _seed_outbox(session, restaurant_id, *, status="pending", attempts=0) -> OutboxMessage:
    row = OutboxMessage(
        restaurant_id=restaurant_id,
        to_phone="+971509876543",
        payload={"type": str(OutboundMessageType.TEXT), "body": "Hello"},
        idempotency_key=f"worker-test-{status}-{attempts}",
        status=status,
        attempts=attempts,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def test_deliver_one_sends_and_marks_sent(db_session, restaurant):
    row = await _seed_outbox(db_session, restaurant.id)
    provider = MockProvider()
    factory = async_sessionmaker(
        bind=db_session.bind, expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    await _deliver_one(row.id, provider=provider, session_factory=factory)

    sends = provider.drain_sends()
    assert len(sends) == 1
    assert sends[0].to_phone == "+971509876543"

    updated = await db_session.get(OutboxMessage, row.id)
    await db_session.refresh(updated)
    assert updated.status == "sent"
    assert updated.attempts == 1
    assert updated.wa_message_id is not None


async def test_deliver_one_marks_failed_on_send_error(db_session, restaurant):
    row = await _seed_outbox(db_session, restaurant.id)
    factory = async_sessionmaker(
        bind=db_session.bind, expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    failing_provider = MockProvider()

    async def _bad_send(msg):
        raise RuntimeError("network error")

    failing_provider.send = _bad_send

    await _deliver_one(row.id, provider=failing_provider, session_factory=factory)

    updated = await db_session.get(OutboxMessage, row.id)
    await db_session.refresh(updated)
    assert updated.status == "failed"
    assert updated.attempts == 1


async def test_deliver_one_marks_dead_after_3_failures(db_session, restaurant):
    row = await _seed_outbox(db_session, restaurant.id, status="failed", attempts=2)
    factory = async_sessionmaker(
        bind=db_session.bind, expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    failing_provider = MockProvider()

    async def _bad_send(msg):
        raise RuntimeError("still broken")

    failing_provider.send = _bad_send

    await _deliver_one(row.id, provider=failing_provider, session_factory=factory)

    updated = await db_session.get(OutboxMessage, row.id)
    await db_session.refresh(updated)
    assert updated.status == "dead"
