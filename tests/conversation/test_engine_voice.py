"""Voice-note (speech-to-text) pipeline: a WhatsApp audio message is downloaded,
transcribed, and then processed exactly like a typed message."""
from decimal import Decimal

from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.outbox.models import OutboxMessage
from app.whatsapp.factory import get_mock_provider
from app.whatsapp.port import InboundMessage, MessageType


def _msg(text: str, wa_id: str = "wamid.v0") -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id, from_phone="+971501110001", type=MessageType.TEXT,
        payload={"text": text}, restaurant_phone="+97141234567", timestamp=1717660800,
    )


def _audio_msg(audio_id: str, wa_id: str) -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id, from_phone="+971501110001", type=MessageType.AUDIO,
        payload={"audio_id": audio_id, "mime": "audio/ogg", "voice": True},
        restaurant_phone="+97141234567", timestamp=1717660900,
    )


async def _seed_menu(db_session, restaurant_id):
    from app.menu.models import Dish, Menu

    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=110,
        name="Chicken Biryani", price_aed=Decimal("22.00"),
        category="Rice", is_available=True, name_normalized="chicken biryani",
    ))
    await db_session.commit()


async def test_voice_note_transcribed_and_added_to_order(db_session, restaurant):
    """An audio message is downloaded + transcribed ('chicken biryani') and flows
    through the normal ordering path, adding the dish — one tap fewer than typing."""
    await _seed_menu(db_session, restaurant.id)
    # Register the fake voice-note bytes; FakeTranscriber decodes UTF-8 audio back
    # to text, so this is the spoken order.
    get_mock_provider().set_media("media-voice-1", b"chicken biryani")

    await handle_inbound(db_session, _msg("hi", "wamid.vg"), restaurant_id=restaurant.id)
    await db_session.commit()

    await handle_inbound(
        db_session, _audio_msg("media-voice-1", "wamid.va1"), restaurant_id=restaurant.id
    )
    await db_session.commit()

    from app.ordering.models import OrderItem
    items = (await db_session.execute(select(OrderItem))).scalars().all()
    assert len(items) == 1
    assert items[0].dish_number == 110

    # The inbound was recorded as an audio message (audit), not text.
    from app.conversation.models import Message
    audio_rows = (await db_session.execute(
        select(Message).where(Message.wa_message_id == "wamid.va1")
    )).scalars().all()
    assert audio_rows and audio_rows[0].type == "audio"


async def test_unintelligible_voice_note_asks_to_retry(db_session, restaurant, monkeypatch):
    """Empty/garbled transcription → polite 'couldn't catch that' reply, no order."""
    await _seed_menu(db_session, restaurant.id)
    get_mock_provider().set_media("media-voice-2", b"chicken biryani")

    class _Empty:
        async def transcribe(self, audio, *, mime="audio/ogg", language=None):
            return ""

    import app.speech.factory as factory
    monkeypatch.setattr(factory, "get_transcriber", lambda: _Empty())

    await handle_inbound(db_session, _msg("hi", "wamid.vg2"), restaurant_id=restaurant.id)
    await db_session.commit()
    await handle_inbound(
        db_session, _audio_msg("media-voice-2", "wamid.va2"), restaurant_id=restaurant.id
    )
    await db_session.commit()

    rows = (await db_session.execute(
        select(OutboxMessage).order_by(OutboxMessage.id)
    )).scalars().all()
    assert "couldn't catch that" in rows[-1].payload["body"].lower()

    from app.ordering.models import OrderItem
    items = (await db_session.execute(select(OrderItem))).scalars().all()
    assert items == []
