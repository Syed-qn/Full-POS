import hashlib
import hmac

import pytest

from app.whatsapp.cloud_provider import CloudAPIProvider, _build_graph_payload, verify_signature
from app.whatsapp.port import OutboundMessage, OutboundMessageType


def test_build_location_payload():
    """LOCATION type maps to a native WhatsApp location message with coords."""
    msg = OutboundMessage(
        to_phone="+971500000000",
        type=OutboundMessageType.LOCATION,
        payload={"latitude": 25.2048, "longitude": 55.2708, "name": "Track House"},
        idempotency_key="loc-1",
    )
    out = _build_graph_payload(msg)
    assert out["type"] == "location"
    assert out["location"]["latitude"] == 25.2048
    assert out["location"]["longitude"] == 55.2708
    assert out["location"]["name"] == "Track House"
    assert "address" not in out["location"]  # omitted when not provided


def test_build_catalog_message_payload():
    """CATALOG_MESSAGE maps to an interactive catalog_message with the View-catalog
    action and a thumbnail product; footer included only when provided."""
    msg = OutboundMessage(
        to_phone="+971500000000",
        type=OutboundMessageType.CATALOG_MESSAGE,
        payload={
            "type": "catalog_message",
            "body": "Here's our full menu 😊",
            "footer": "Send your basket to order.",
            "thumbnail_product_retailer_id": "dish-9-7",
        },
        idempotency_key="cat-1",
    )
    out = _build_graph_payload(msg)
    assert out["type"] == "interactive"
    inter = out["interactive"]
    assert inter["type"] == "catalog_message"
    assert inter["body"]["text"] == "Here's our full menu 😊"
    assert inter["action"]["name"] == "catalog_message"
    assert inter["action"]["parameters"]["thumbnail_product_retailer_id"] == "dish-9-7"
    assert inter["footer"]["text"] == "Send your basket to order."


def test_verify_signature_valid():
    secret = "testsecret"
    body = b'{"object":"whatsapp_business_account"}'
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    # Should not raise
    verify_signature(body, sig, secret)


def test_verify_signature_invalid_raises():
    with pytest.raises(ValueError, match="signature"):
        verify_signature(b"body", "sha256=badhex", "secret")


def test_verify_signature_missing_prefix_raises():
    with pytest.raises(ValueError, match="signature"):
        verify_signature(b"body", "badsig", "secret")


def test_cloud_provider_requires_config(monkeypatch):
    """CloudAPIProvider instantiates with settings; no network call in __init__."""
    from app.config import get_settings

    monkeypatch.setenv("APP_WA_ACCESS_TOKEN", "fake-token")
    monkeypatch.setenv("APP_WA_PHONE_NUMBER_ID", "12345")
    monkeypatch.setenv("APP_WA_APP_SECRET", "appsecret")
    get_settings.cache_clear()
    try:
        provider = CloudAPIProvider()
        assert provider is not None
    finally:
        get_settings.cache_clear()
