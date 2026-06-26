"""Manager-dashboard API for WhatsApp conversations.

Backs the React Conversations screen (frontend/src/screens/ConversationsScreen):
list conversations, fetch one conversation's messages, toggle manual takeover,
and send a manager-authored message to the customer. Tenant-scoped to the
logged-in restaurant.
"""
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.conversation import service
from app.conversation.schemas import (
    DashboardConversationOut,
    DashboardMessageOut,
    SendMessageIn,
    TakeoverIn,
)
from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


async def _dispatch_outbox(session: AsyncSession, outbox_ids: list[int]) -> None:
    """Deliver freshly-committed outbox rows — synchronously in-request when no
    Celery worker runs (APP_OUTBOX_SYNC_DELIVERY, e.g. Render free tier), else
    hand off to the outbox queue. Mirrors the webhook reply path."""
    if not outbox_ids:
        return
    if get_settings().outbox_sync_delivery:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.outbox.worker import _deliver_one
        from app.whatsapp.factory import get_whatsapp_provider

        provider = get_whatsapp_provider()
        factory = async_sessionmaker(
            bind=session.bind,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        for oid in outbox_ids:
            await _deliver_one(oid, provider=provider, session_factory=factory)
    else:
        from app.outbox.worker import deliver_outbox_message

        for oid in outbox_ids:
            deliver_outbox_message.apply_async(args=[oid], queue="outbox")


@router.post("/cart-tick")
async def abandoned_cart_tick(
    x_tick_secret: str | None = Header(default=None),
) -> dict:
    """Heartbeat for the abandoned-cart sweep — called by an external cron job
    (Render has no working Celery beat), NOT a manager.

    Guarded by the ``X-Tick-Secret`` header matching ``APP_MARKETING_TICK_SECRET``
    (same secret as the marketing tick, so one cron credential covers both).
    Runs across ALL tenants: each enabled restaurant's stale draft carts are
    nudged (once) or auto-cleared, with the nudge delivered synchronously inside
    ``_run_sweep``. The cron hits one URL for the whole platform."""
    secret = get_settings().marketing_tick_secret.get_secret_value()
    if not secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "tick not configured")
    if x_tick_secret != secret:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid tick secret")

    from app.conversation.worker import _run_sweep

    nudged = await _run_sweep()
    return {"nudged": nudged}


@router.get("", response_model=list[DashboardConversationOut])
async def list_conversations(
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> list[DashboardConversationOut]:
    rows = await service.list_dashboard_conversations(session, restaurant_id=restaurant.id)
    return [DashboardConversationOut(**row) for row in rows]


@router.get("/{conversation_id}/messages", response_model=list[DashboardMessageOut])
async def list_messages(
    conversation_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> list[DashboardMessageOut]:
    messages = await service.get_dashboard_messages(
        session, restaurant_id=restaurant.id, conversation_id=conversation_id
    )
    if messages is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    return [
        DashboardMessageOut(
            id=m.id,
            direction=m.direction,
            type=m.type,
            payload=service.message_view_payload(m),
            ts=m.ts,
        )
        for m in messages
    ]


@router.post("/{conversation_id}/takeover", status_code=status.HTTP_204_NO_CONTENT)
async def toggle_takeover(
    conversation_id: int,
    body: TakeoverIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> None:
    ok = await service.set_manual_takeover(
        session,
        conversation_id=conversation_id,
        taken_over_by=restaurant.id,
        active=body.active,
        restaurant_id=restaurant.id,
    )
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    await session.commit()


@router.post("/{conversation_id}/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_conversation(
    conversation_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> None:
    ok = await service.reset_conversation_state(
        session,
        conversation_id=conversation_id,
        restaurant_id=restaurant.id,
    )
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    await session.commit()


@router.post(
    "/{conversation_id}/messages",
    response_model=DashboardMessageOut,
    status_code=status.HTTP_201_CREATED,
)
async def send_message(
    conversation_id: int,
    body: SendMessageIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> DashboardMessageOut:
    result = await service.send_manual_message(
        session,
        restaurant_id=restaurant.id,
        conversation_id=conversation_id,
        text=body.text,
    )
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    msg, outbox_id = result
    out = DashboardMessageOut(
        id=msg.id,
        direction=msg.direction,
        type=msg.type,
        payload=service.message_view_payload(msg),
        ts=msg.ts,
    )
    await session.commit()
    await _dispatch_outbox(session, [outbox_id])
    return out
