"""Phase 7 Task 2 — atomic outbox row-claim race.

Two concurrent claims over the same pending rows must return DISJOINT id sets
(no row dispatched twice), and the worker must deliver a row already in the
'dispatching' claimed state.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.outbox.models import OutboxMessage
from app.outbox.worker import _deliver_one, claim_pending_outbox_ids
from app.whatsapp.mock_provider import MockProvider
from app.whatsapp.port import OutboundMessageType


async def _seed_outbox(session, restaurant_id, *, key, status="pending") -> OutboxMessage:
    row = OutboxMessage(
        restaurant_id=restaurant_id,
        to_phone="+971509876543",
        payload={"type": str(OutboundMessageType.TEXT), "body": "Hello"},
        idempotency_key=key,
        status=status,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def test_concurrent_claims_return_disjoint_ids(db_session, restaurant):
    """Two claims over the same pending set never overlap; total claimed == seeded."""
    seeded = [
        await _seed_outbox(db_session, restaurant.id, key=f"claim-race-{i}")
        for i in range(5)
    ]
    seeded_ids = {r.id for r in seeded}

    first = await claim_pending_outbox_ids(
        db_session, to_phone="+971509876543", restaurant_id=restaurant.id
    )
    second = await claim_pending_outbox_ids(
        db_session, to_phone="+971509876543", restaurant_id=restaurant.id
    )

    assert set(first).isdisjoint(set(second))
    assert set(first) | set(second) == seeded_ids
    # First claim wins everything; second sees them already in 'dispatching'.
    assert set(first) == seeded_ids
    assert second == []

    # Every claimed row is now in 'dispatching', not 'pending'.
    statuses = (
        await db_session.execute(
            select(OutboxMessage.status).where(OutboxMessage.id.in_(seeded_ids))
        )
    ).scalars().all()
    assert all(s == "dispatching" for s in statuses)


async def test_worker_delivers_dispatching_row(db_session, restaurant):
    """A row already claimed ('dispatching') is delivered and marked sent."""
    row = await _seed_outbox(
        db_session, restaurant.id, key="claim-dispatching-1", status="dispatching"
    )
    provider = MockProvider()
    factory = async_sessionmaker(
        bind=db_session.bind,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    await _deliver_one(row.id, provider=provider, session_factory=factory)

    sends = provider.drain_sends()
    assert len(sends) == 1

    updated = await db_session.get(OutboxMessage, row.id)
    await db_session.refresh(updated)
    assert updated.status == "sent"
    assert updated.attempts == 1
