import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.conversation.engine import handle_inbound
from app.db import get_session
from app.identity.models import Restaurant
from app.outbox.models import OutboxMessage
from app.outbox.worker import _deliver_one
from app.webhook.models import WebhookEvent
from app.whatsapp.factory import get_mock_provider
from app.whatsapp.port import InboundMessage, MessageType

router = APIRouter(prefix="/simulator", tags=["simulator"])

_HTML_PATH = Path(__file__).parent / "static" / "index.html"


@router.get("/", response_class=HTMLResponse)
async def simulator_index() -> str:
    return _HTML_PATH.read_text()


class SimulatorSendIn(BaseModel):
    from_phone: str
    restaurant_phone: str
    text: str


@router.post("/send")
async def simulator_send(
    body: SimulatorSendIn,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Inject a fake inbound text message through the full pipeline."""
    restaurant = await session.scalar(
        select(Restaurant).where(Restaurant.phone == body.restaurant_phone)
    )
    if restaurant is None:
        raise HTTPException(404, f"no restaurant with phone {body.restaurant_phone}")

    wa_id = f"sim-wamid-{uuid.uuid4().hex[:12]}"
    session.add(
        WebhookEvent(
            provider_event_id=wa_id,
            payload={"simulator": True, "text": body.text},
            processed_at=None,
        )
    )

    inbound = InboundMessage(
        wa_message_id=wa_id,
        from_phone=body.from_phone,
        type=MessageType.TEXT,
        payload={"text": body.text},
        restaurant_phone=body.restaurant_phone,
        timestamp=0,
    )
    await handle_inbound(session, inbound, restaurant_id=restaurant.id)
    await session.commit()

    # Synchronous delivery via MockProvider (simulator = immediate)
    pending = (
        await session.execute(
            select(OutboxMessage).where(
                OutboxMessage.status == "pending",
                OutboxMessage.to_phone == body.from_phone,
                OutboxMessage.restaurant_id == restaurant.id,
            )
        )
    ).scalars().all()

    provider = get_mock_provider()

    # Deliver on the SAME connection the request used. Opening a fresh
    # connection (async_session_factory) cannot see rows committed within an
    # outer test transaction (savepoint isolation), and is also an unnecessary
    # extra connection for the synchronous simulator path. Bind a sessionmaker
    # to this session's connection so _deliver_one reuses it.
    session_factory = async_sessionmaker(
        bind=session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    for row in pending:
        await _deliver_one(row.id, provider=provider, session_factory=session_factory)

    return {"status": "ok", "wa_message_id": wa_id}


@router.get("/messages")
async def simulator_messages() -> list[dict]:
    """Return and clear the MockProvider send log for the simulator UI."""
    provider = get_mock_provider()
    sends = provider.drain_sends()
    return [
        {
            "to": s.to_phone,
            "type": str(s.type),
            "payload": s.payload,
            "wa_message_id": s.wa_message_id,
        }
        for s in sends
    ]
