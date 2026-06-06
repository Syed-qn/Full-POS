# tests/whatsapp/test_normalizer.py
from app.webhook.normalizer import parse_cloud_payload
from app.whatsapp.port import MessageType

_TEXT_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [{"changes": [{"value": {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "+97141234567", "phone_number_id": "111"},
        "messages": [{"id": "wamid.HBgL", "from": "971509876543", "timestamp": "1717660800",
                      "type": "text", "text": {"body": "Hello, I want to order"}}],
    }, "field": "messages"}]}],
}

_BUTTON_REPLY_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [{"changes": [{"value": {
        "metadata": {"display_phone_number": "+97141234567", "phone_number_id": "111"},
        "messages": [{"id": "wamid.BTN1", "from": "971509876543", "timestamp": "1717660900",
                      "type": "interactive",
                      "interactive": {"type": "button_reply", "button_reply": {"id": "confirm", "title": "Yes"}}}],
    }, "field": "messages"}]}],
}

_LOCATION_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [{"changes": [{"value": {
        "metadata": {"display_phone_number": "+97141234567", "phone_number_id": "111"},
        "messages": [{"id": "wamid.LOC1", "from": "971509876543", "timestamp": "1717661000",
                      "type": "location", "location": {"latitude": 25.2048, "longitude": 55.2708}}],
    }, "field": "messages"}]}],
}


def test_parse_text_message():
    msgs = parse_cloud_payload(_TEXT_PAYLOAD)
    assert len(msgs) == 1
    m = msgs[0]
    assert m.wa_message_id == "wamid.HBgL"
    assert m.from_phone == "+971509876543"
    assert m.type == MessageType.TEXT
    assert m.payload["text"] == "Hello, I want to order"
    assert m.restaurant_phone == "+97141234567"
    assert m.timestamp == 1717660800


def test_parse_button_reply():
    msgs = parse_cloud_payload(_BUTTON_REPLY_PAYLOAD)
    assert msgs[0].type == MessageType.BUTTON_REPLY
    assert msgs[0].payload["id"] == "confirm"
    assert msgs[0].payload["title"] == "Yes"


def test_parse_location():
    msgs = parse_cloud_payload(_LOCATION_PAYLOAD)
    assert msgs[0].type == MessageType.LOCATION
    assert msgs[0].payload["latitude"] == 25.2048
    assert msgs[0].payload["longitude"] == 55.2708


def test_parse_status_update_returns_empty():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {
            "metadata": {"display_phone_number": "+97141234567", "phone_number_id": "111"},
            "statuses": [{"id": "wamid.abc", "status": "delivered"}],
        }, "field": "messages"}]}],
    }
    assert parse_cloud_payload(payload) == []
