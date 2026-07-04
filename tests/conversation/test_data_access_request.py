"""UAE PDPL data-subject-access handler — deterministic, LLM-free, any phase.

Prod regression: "Tell me my data as per local gov rules I want to know what
information you store about me" hit the LLM path and died with a canned error.
PDPL (Federal Decree-Law No. 45 of 2021) access requests must be answered
deterministically with the stored-data categories and the customer's rights.
"""
from sqlalchemy import select

from app.conversation.engine import _is_data_access_request, handle_inbound
from app.conversation.models import Conversation
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType

_PHONE = "+971501119777"
_REST_PHONE = "+97141234567"


def _msg(text: str, wa_id: str) -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id, from_phone=_PHONE, type=MessageType.TEXT,
        payload={"text": text}, restaurant_phone=_REST_PHONE, timestamp=1717660800,
    )


async def _latest_body(db_session) -> str:
    row = (await db_session.execute(
        select(OutboxMessage).order_by(OutboxMessage.id.desc())
    )).scalars().first()
    return row.payload.get("body", "") if row else ""


# ── detection unit tests ──────────────────────────────────────────────────

def test_detects_prod_message():
    assert _is_data_access_request(
        "Tell me my data as per local gov rules I want to know what "
        "information you store about me"
    )


def test_detects_common_phrasings():
    for text in (
        "what information do you store about me",
        "what do you know about me",
        "show me my personal data",
        "delete my data",
        "remove my information please",
        "what's your privacy policy",
        "I want my info deleted as per PDPL",
        "gdpr request",
        "right to be forgotten",
    ):
        assert _is_data_access_request(text), text


def test_ignores_ordering_messages():
    for text in (
        "what's in my cart",
        "do you have chicken biriyani",
        "save my address",
        "1 chicken soup",
        "done",
        "show me the menu",
        "use my usual order",
        "deliver to my location",
    ):
        assert not _is_data_access_request(text), text


# ── E2E through handle_inbound ────────────────────────────────────────────

async def test_data_access_request_gets_pdpl_reply(db_session, restaurant):
    await handle_inbound(
        db_session,
        _msg(
            "Tell me my data as per local gov rules I want to know what "
            "information you store about me",
            "wamid.pdpl1",
        ),
        restaurant_id=restaurant.id,
    )
    await db_session.commit()

    body = await _latest_body(db_session)
    low = body.lower()
    assert "phone" in low
    assert "address" in low
    assert "order history" in low
    assert "delet" in low  # deletion right / how to delete
    assert "pdpl" in low or "data protection" in low
    # COD platform — must reassure no card data stored.
    assert "card" in low


async def test_data_access_mid_ordering_does_not_touch_state(db_session, restaurant):
    await handle_inbound(db_session, _msg("hi", "wamid.pdpl2"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = (await db_session.execute(
        select(Conversation).where(Conversation.phone == _PHONE)
    )).scalar_one()
    state_before = dict(conv.state or {})

    await handle_inbound(
        db_session, _msg("what data do you have about me", "wamid.pdpl3"),
        restaurant_id=restaurant.id,
    )
    await db_session.commit()

    body = await _latest_body(db_session)
    assert "order history" in body.lower()
    await db_session.refresh(conv)
    assert dict(conv.state or {}) == state_before
