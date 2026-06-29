"""Inbound images, PDFs, and other WhatsApp attachments in manager Chats."""

from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.conversation.models import Message
from app.whatsapp.factory import get_mock_provider
from app.whatsapp.port import InboundMessage, MessageType


async def test_image_inbound_persisted_for_dashboard(db_session, restaurant):
    get_mock_provider().set_media("img-menu-1", b"\xff\xd8\xffimage-bytes")
    inbound = InboundMessage(
        wa_message_id="wamid.img1",
        from_phone="+971501110001",
        type=MessageType.IMAGE,
        payload={
            "image_id": "img-menu-1",
            "mime": "image/jpeg",
            "caption": "here is the menu",
        },
        restaurant_phone=restaurant.phone,
        timestamp=1_700_000_200,
    )
    await handle_inbound(db_session, inbound, restaurant_id=restaurant.id)
    await db_session.commit()

    msg = await db_session.scalar(
        select(Message).where(Message.wa_message_id == "wamid.img1")
    )
    assert msg is not None
    assert msg.type == "image"
    assert msg.media_data == b"\xff\xd8\xffimage-bytes"
    assert msg.payload["text"] == "here is the menu"


async def test_document_inbound_persisted_for_dashboard(db_session, restaurant):
    pdf = b"%PDF-1.4 test"
    get_mock_provider().set_media("doc-1", pdf)
    inbound = InboundMessage(
        wa_message_id="wamid.doc1",
        from_phone="+971501110002",
        type=MessageType.DOCUMENT,
        payload={
            "document_id": "doc-1",
            "mime": "application/pdf",
            "filename": "invoice.pdf",
        },
        restaurant_phone=restaurant.phone,
        timestamp=1_700_000_300,
    )
    await handle_inbound(db_session, inbound, restaurant_id=restaurant.id)
    await db_session.commit()

    msg = await db_session.scalar(
        select(Message).where(Message.wa_message_id == "wamid.doc1")
    )
    assert msg is not None
    assert msg.type == "document"
    assert msg.media_data == pdf
    assert msg.media_mime == "application/pdf"