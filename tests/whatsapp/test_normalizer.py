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


_TEMPLATE_BUTTON_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [{"changes": [{"value": {
        "metadata": {"display_phone_number": "+97141234567", "phone_number_id": "111"},
        "messages": [{"id": "wamid.TBTN1", "from": "971509876543", "timestamp": "1717660950",
                      "type": "button",
                      "button": {"payload": "picked:42", "text": "Orders Picked"}}],
    }, "field": "messages"}]}],
}


def test_parse_template_quick_reply_button():
    # A tap on a TEMPLATE quick-reply button arrives as type "button" (not
    # interactive) — the rider "Orders Picked" tap must still map to BUTTON_REPLY
    # with the developer payload as the id, or the rider flow never advances.
    msgs = parse_cloud_payload(_TEMPLATE_BUTTON_PAYLOAD)
    assert msgs[0].type == MessageType.BUTTON_REPLY
    assert msgs[0].payload["id"] == "picked:42"
    assert msgs[0].payload["title"] == "Orders Picked"


def test_parse_location():
    msgs = parse_cloud_payload(_LOCATION_PAYLOAD)
    assert msgs[0].type == MessageType.LOCATION
    assert msgs[0].payload["latitude"] == 25.2048
    assert msgs[0].payload["longitude"] == 55.2708
    assert "is_live" not in msgs[0].payload  # static pin has no live flag


def test_parse_live_location_sets_is_live():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {
            "metadata": {"display_phone_number": "+97141234567", "phone_number_id": "111"},
            "messages": [{"id": "wamid.LIVE1", "from": "971509876543", "timestamp": "1717661000",
                          "type": "location",
                          "location": {"latitude": 25.2048, "longitude": 55.2708, "live_period": 3600}}],
        }, "field": "messages"}]}],
    }
    msgs = parse_cloud_payload(payload)
    assert msgs[0].type == MessageType.LOCATION
    assert msgs[0].payload["is_live"] is True
    assert msgs[0].payload["latitude"] == 25.2048


_AUDIO_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [{"changes": [{"value": {
        "metadata": {"display_phone_number": "+97141234567", "phone_number_id": "111"},
        "messages": [{"id": "wamid.AUD1", "from": "971509876543", "timestamp": "1717661100",
                      "type": "audio",
                      "audio": {"id": "media-789", "mime_type": "audio/ogg; codecs=opus",
                                "voice": True}}],
    }, "field": "messages"}]}],
}


def test_parse_audio_voice_note():
    # A WhatsApp voice note arrives as type "audio" carrying a media id — the
    # normalizer must surface it as MessageType.AUDIO so the engine can download
    # and transcribe it (the bytes are NOT in the webhook).
    msgs = parse_cloud_payload(_AUDIO_PAYLOAD)
    assert len(msgs) == 1
    m = msgs[0]
    assert m.type == MessageType.AUDIO
    assert m.payload["audio_id"] == "media-789"
    assert m.payload["mime"] == "audio/ogg; codecs=opus"
    assert m.payload["voice"] is True
    assert m.from_phone == "+971509876543"


def test_parse_status_update_returns_empty():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {
            "metadata": {"display_phone_number": "+97141234567", "phone_number_id": "111"},
            "statuses": [{"id": "wamid.abc", "status": "delivered"}],
        }, "field": "messages"}]}],
    }
    assert parse_cloud_payload(payload) == []
