from app.whatsapp.port import (
    InboundMessage,
    MessageType,
    OutboundMessage,
    OutboundMessageType,
)


def test_outbound_message_text_shape():
    msg = OutboundMessage(
        to_phone="+971501234567",
        type=OutboundMessageType.TEXT,
        payload={"body": "Hello!"},
        idempotency_key="key-1",
    )
    assert msg.to_phone == "+971501234567"
    assert msg.payload["body"] == "Hello!"


def test_inbound_message_shape():
    msg = InboundMessage(
        wa_message_id="wamid.abc123",
        from_phone="+971509999999",
        type=MessageType.TEXT,
        payload={"text": "hi"},
        restaurant_phone="+97141234567",
    )
    assert msg.from_phone == "+971509999999"
    assert msg.type == MessageType.TEXT
