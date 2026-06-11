import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, model_validator
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
    return _HTML_PATH.read_text(encoding="utf-8")


class ButtonReplyIn(BaseModel):
    id: str
    title: str


class LocationIn(BaseModel):
    latitude: float
    longitude: float


class SimulatorSendIn(BaseModel):
    from_phone: str
    restaurant_phone: str
    text: str | None = None
    button_reply: ButtonReplyIn | None = None
    location: LocationIn | None = None

    @model_validator(mode="after")
    def _exactly_one_payload(self) -> "SimulatorSendIn":
        provided = [
            field
            for field, value in (
                ("text", self.text),
                ("button_reply", self.button_reply),
                ("location", self.location),
            )
            if value is not None
        ]
        if len(provided) != 1:
            raise ValueError(
                "exactly one of text, button_reply, location must be provided"
            )
        return self

    def to_inbound(self, *, wa_message_id: str) -> InboundMessage:
        if self.button_reply is not None:
            mtype = MessageType.BUTTON_REPLY
            payload = {"id": self.button_reply.id, "title": self.button_reply.title}
        elif self.location is not None:
            mtype = MessageType.LOCATION
            payload = {
                "latitude": self.location.latitude,
                "longitude": self.location.longitude,
            }
        else:
            mtype = MessageType.TEXT
            payload = {"text": self.text}
        return InboundMessage(
            wa_message_id=wa_message_id,
            from_phone=self.from_phone,
            type=mtype,
            payload=payload,
            restaurant_phone=self.restaurant_phone,
            timestamp=0,
        )


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
    inbound = body.to_inbound(wa_message_id=wa_id)
    session.add(
        WebhookEvent(
            provider_event_id=wa_id,
            payload={"simulator": True, "type": str(inbound.type), **inbound.payload},
            processed_at=None,
        )
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
async def simulator_messages(phone: str | None = None) -> list[dict]:
    """Return and clear MockProvider send log. If `phone` supplied, return only messages to that phone."""
    provider = get_mock_provider()
    sends = provider.drain_sends_for(phone) if phone else provider.drain_sends()
    return [
        {
            "to": s.to_phone,
            "type": str(s.type),
            "payload": s.payload,
            "wa_message_id": s.wa_message_id,
        }
        for s in sends
    ]


@router.get("/rider", response_class=HTMLResponse)
async def simulator_rider_index() -> str:
    return (Path(__file__).parent / "static" / "rider.html").read_text(encoding="utf-8")
