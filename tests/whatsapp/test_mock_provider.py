from app.whatsapp.port import (
    InboundMessage,
    MessageType,
    OutboundMessage,
    OutboundMessageType,
)
from app.whatsapp.mock_provider import MockProvider


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


async def test_mock_send_records_and_returns_id():
    provider = MockProvider()
    msg = OutboundMessage(
        to_phone="+971501234567",
        type=OutboundMessageType.TEXT,
        payload={"body": "Hello!"},
        idempotency_key="k1",
    )
    wa_id = await provider.send(msg)
    assert wa_id.startswith("mock-wamid-")
    sent = provider.drain_sends()
    assert len(sent) == 1
    assert sent[0].wa_message_id == wa_id


async def test_mock_inject_inbound_queues_message():
    provider = MockProvider()
    inbound = InboundMessage(
        wa_message_id="wamid.test1",
        from_phone="+971509999999",
        type=MessageType.TEXT,
        payload={"text": "hi"},
        restaurant_phone="+97141234567",
    )
    provider.inject_inbound(inbound)
    queued = provider.drain_inbound()
    assert len(queued) == 1
    assert queued[0].wa_message_id == "wamid.test1"


async def test_mock_drain_clears_log():
    provider = MockProvider()
    msg = OutboundMessage(
        to_phone="+971501234567",
        type=OutboundMessageType.TEXT,
        payload={"body": "Hi"},
        idempotency_key="k2",
    )
    await provider.send(msg)
    provider.drain_sends()
    assert provider.drain_sends() == []
