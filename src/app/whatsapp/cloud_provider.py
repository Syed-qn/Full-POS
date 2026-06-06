import hashlib
import hmac as _hmac
from typing import Any

import httpx

from app.config import get_settings
from app.whatsapp.port import OutboundMessage, OutboundMessageType

_GRAPH_BASE = "https://graph.facebook.com/v21.0"


def verify_signature(body: bytes, header: str, secret: str) -> None:
    """Raise ValueError if X-Hub-Signature-256 header does not match body HMAC."""
    if not header.startswith("sha256="):
        raise ValueError("signature header missing sha256= prefix")
    expected = _hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    received = header[len("sha256="):]
    if not _hmac.compare_digest(expected, received):
        raise ValueError("signature mismatch — request not from Meta")


def _build_graph_payload(msg: OutboundMessage) -> dict[str, Any]:
    base: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": msg.to_phone,
    }
    if msg.type == OutboundMessageType.TEXT:
        base["type"] = "text"
        base["text"] = {"body": msg.payload["body"], "preview_url": False}

    elif msg.type == OutboundMessageType.BUTTONS:
        # payload: {"body": str, "buttons": [{"id": str, "title": str}]}
        base["type"] = "interactive"
        base["interactive"] = {
            "type": "button",
            "body": {"text": msg.payload["body"]},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}}
                    for b in msg.payload["buttons"]
                ]
            },
        }

    elif msg.type == OutboundMessageType.LIST:
        # payload: {"body": str, "button_label": str, "sections": [...]}
        base["type"] = "interactive"
        base["interactive"] = {
            "type": "list",
            "body": {"text": msg.payload["body"]},
            "action": {
                "button": msg.payload["button_label"],
                "sections": msg.payload["sections"],
            },
        }

    elif msg.type == OutboundMessageType.LOCATION_REQUEST:
        # payload: {"body": str}
        base["type"] = "interactive"
        base["interactive"] = {
            "type": "location_request_message",
            "body": {"text": msg.payload["body"]},
            "action": {"name": "send_location"},
        }

    elif msg.type == OutboundMessageType.IMAGE:
        # payload: {"url": str, "caption": str}
        base["type"] = "image"
        base["image"] = {"link": msg.payload["url"], "caption": msg.payload.get("caption", "")}

    elif msg.type == OutboundMessageType.TEMPLATE:
        # payload: {"name": str, "language": str, "components": list}
        base["type"] = "template"
        base["template"] = {
            "name": msg.payload["name"],
            "language": {"code": msg.payload.get("language", "en")},
            "components": msg.payload.get("components", []),
        }

    return base


class CloudAPIProvider:
    def __init__(self) -> None:
        settings = get_settings()
        self._token = settings.wa_access_token.get_secret_value()
        self._phone_number_id = settings.wa_phone_number_id
        self._app_secret = settings.wa_app_secret.get_secret_value()

    async def send(self, msg: OutboundMessage) -> str:
        url = f"{_GRAPH_BASE}/{self._phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        payload = _build_graph_payload(msg)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        wa_id: str = data["messages"][0]["id"]
        msg.wa_message_id = wa_id
        return wa_id

    def verify_inbound_signature(self, body: bytes, header: str) -> None:
        verify_signature(body, header, self._app_secret)
