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


async def test_deliver_one_24h_window_marks_dead_with_reason(db_session, restaurant):
    """Meta error 131047 (re-engagement / 24h window closed) is permanent for this
    message — retrying can never succeed. Mark dead immediately with a queryable
    fail_reason instead of burning retries and hiding the loss."""
    import httpx

    row = await _seed_outbox(db_session, restaurant.id)
    factory = async_sessionmaker(
        bind=db_session.bind, expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    provider = MockProvider()

    async def _window_closed(msg, **kwargs):
        request = httpx.Request("POST", "https://graph.facebook.com/v20.0/x/messages")
        response = httpx.Response(
            400,
            request=request,
            json={"error": {"code": 131047, "message": "Re-engagement message",
                            "error_data": {"details": "24h customer service window expired"}}},
        )
        raise httpx.HTTPStatusError("400", request=request, response=response)

    provider.send = _window_closed

    await _deliver_one(row.id, provider=provider, session_factory=factory)

    updated = await db_session.get(OutboxMessage, row.id)
    await db_session.refresh(updated)
    assert updated.status == "dead"
    assert updated.payload.get("fail_reason") == "24h_window"
