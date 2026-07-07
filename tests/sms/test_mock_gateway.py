from app.sms.mock import MockSmsGateway


async def test_send_records_message_and_returns_message_id():
    gateway = MockSmsGateway()

    message_id = await gateway.send(to_phone="+971500000001", body="Your order is ready!")

    assert isinstance(message_id, str)
    assert message_id
    assert len(gateway.sent) == 1
    assert gateway.sent[0]["to_phone"] == "+971500000001"
    assert gateway.sent[0]["body"] == "Your order is ready!"
    assert gateway.sent[0]["message_id"] == message_id


async def test_send_is_deterministic_but_unique_per_call():
    gateway = MockSmsGateway()

    id1 = await gateway.send(to_phone="+971500000001", body="hello")
    id2 = await gateway.send(to_phone="+971500000001", body="hello")

    assert id1 != id2
    assert len(gateway.sent) == 2


def test_get_sms_port_returns_mock_gateway_by_default(monkeypatch):
    from app.config import get_settings
    from app.sms.factory import get_sms_port
    from app.sms.mock import MockSmsGateway

    get_settings.cache_clear()
    monkeypatch.delenv("APP_SMS_PROVIDER", raising=False)

    port = get_sms_port()

    assert isinstance(port, MockSmsGateway)
    get_settings.cache_clear()


def test_get_sms_port_raises_for_unknown_provider(monkeypatch):
    from app.config import get_settings
    from app.sms.factory import get_sms_port

    get_settings.cache_clear()
    monkeypatch.setenv("APP_SMS_PROVIDER", "twilio")

    try:
        import pytest

        with pytest.raises(ValueError):
            get_sms_port()
    finally:
        monkeypatch.delenv("APP_SMS_PROVIDER", raising=False)
        get_settings.cache_clear()
