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

    elif msg.type == OutboundMessageType.CTA_URL:
        # payload: {"body": str, "button_label": str, "url": str}
        # Single tappable URL button (e.g. "Open in Maps"). WhatsApp does not
        # allow combining a URL button with quick-reply buttons in one message,
        # so this is sent as its own message.
        base["type"] = "interactive"
        base["interactive"] = {
            "type": "cta_url",
            "body": {"text": msg.payload["body"]},
            "action": {
                "name": "cta_url",
                "parameters": {
                    "display_text": msg.payload["button_label"],
                    "url": msg.payload["url"],
                },
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

    elif msg.type == OutboundMessageType.PRODUCT_LIST:
        # payload: {"header": str, "body": str, "footer": str?, "catalog_id": str,
        #           "sections": [{"title": str, "product_items": [{"product_retailer_id": str}]}]}
        # Multi-product message: the catalog items shown as tappable cards with an
        # Add to basket button. The customer sends the basket back as an `order`.
        base["type"] = "interactive"
        interactive: dict[str, Any] = {
            "type": "product_list",
            "header": {"type": "text", "text": msg.payload["header"]},
            "body": {"text": msg.payload["body"]},
            "action": {
                "catalog_id": msg.payload["catalog_id"],
                "sections": msg.payload["sections"],
            },
        }
        if msg.payload.get("footer"):
            interactive["footer"] = {"text": msg.payload["footer"]}
        base["interactive"] = interactive

    elif msg.type == OutboundMessageType.CATALOG_MESSAGE:
        # payload: {"body": str, "footer": str?, "thumbnail_product_retailer_id": str}
        # A single "View catalog" button that opens the WABA's connected catalogue in
        # WhatsApp's native storefront — the customer browses EVERY product (no 30-card
        # cap, no "Show more") with collections shown as categories. The thumbnail is one
        # sendable product shown on the button card.
        base["type"] = "interactive"
        cat_interactive: dict[str, Any] = {
            "type": "catalog_message",
            "body": {"text": msg.payload["body"]},
            "action": {
                "name": "catalog_message",
                "parameters": {
                    "thumbnail_product_retailer_id": msg.payload["thumbnail_product_retailer_id"],
                },
            },
        }
        if msg.payload.get("footer"):
            cat_interactive["footer"] = {"text": msg.payload["footer"]}
        base["interactive"] = cat_interactive

    elif msg.type == OutboundMessageType.LOCATION:
        # payload: {"latitude": float, "longitude": float, "name": str?, "address": str?}
        # Sends a native WhatsApp location pin (opens in the recipient's maps app).
        loc: dict[str, Any] = {
            "latitude": msg.payload["latitude"],
            "longitude": msg.payload["longitude"],
        }
        if msg.payload.get("name"):
            loc["name"] = msg.payload["name"]
        if msg.payload.get("address"):
            loc["address"] = msg.payload["address"]
        base["type"] = "location"
        base["location"] = loc

    elif msg.type == OutboundMessageType.LOCATION_REQUEST:
        # payload: {"body": str}
        base["type"] = "interactive"
        base["interactive"] = {
            "type": "location_request_message",
            "body": {"text": msg.payload["body"]},
            "action": {"name": "send_location"},
        }

    elif msg.type == OutboundMessageType.IMAGE:
        # payload: {"url": str, "caption": str} OR {"media_id": str, "caption": str}
        base["type"] = "image"
        if "media_id" in msg.payload:
            base["image"] = {"id": msg.payload["media_id"], "caption": msg.payload.get("caption", "")}
        else:
            base["image"] = {"link": msg.payload["url"], "caption": msg.payload.get("caption", "")}

    elif msg.type == OutboundMessageType.DOCUMENT:
        # payload: {"url": str, "filename": str} OR {"media_id": str, "filename": str}
        base["type"] = "document"
        if "media_id" in msg.payload:
            base["document"] = {
                "id": msg.payload["media_id"],
                "filename": msg.payload.get("filename", "menu.pdf"),
            }
        else:
            base["document"] = {
                "link": msg.payload["url"],
                "filename": msg.payload.get("filename", "menu.pdf"),
                "caption": msg.payload.get("caption", ""),
            }

    elif msg.type == OutboundMessageType.TEMPLATE:
        # payload: {"name": str, "language": str, "components": list}
        base["type"] = "template"
        base["template"] = {
            "name": msg.payload["name"],
            "language": {"code": msg.payload.get("language", "en")},
            "components": msg.payload.get("components", []),
        }

    else:
        raise NotImplementedError(f"Unsupported message type: {msg.type!r}")

    return base


class CloudAPIProvider:
    def __init__(self) -> None:
        settings = get_settings()
        self._token = settings.wa_access_token.get_secret_value()
        self._phone_number_id = settings.wa_phone_number_id
        self._app_secret = settings.wa_app_secret.get_secret_value()

    async def _upload_media(
        self,
        data: bytes,
        content_type: str,
        *,
        phone_number_id: str,
        access_token: str,
    ) -> str:
        """Upload raw bytes to Meta media API; return the media_id."""
        import base64 as _b64
        _ = _b64  # suppress unused import — base64 used only by caller
        url = f"{_GRAPH_BASE}/{phone_number_id}/media"
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                headers=headers,
                data={"messaging_product": "whatsapp"},
                files={"file": ("file", data, content_type)},
            )
        resp.raise_for_status()
        return resp.json()["id"]

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        """Fetch inbound media bytes from the Graph API (two-step: resolve the
        temporary URL by media id, then GET it — both require the bearer token).
        Returns (bytes, mime_type)."""
        headers = {"Authorization": f"Bearer {self._token}"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            meta = await client.get(f"{_GRAPH_BASE}/{media_id}", headers=headers)
            meta.raise_for_status()
            info = meta.json()
            mime = info.get("mime_type", "application/octet-stream")
            blob = await client.get(info["url"], headers=headers)
            blob.raise_for_status()
        return blob.content, mime

    async def send(
        self,
        msg: OutboundMessage,
        *,
        phone_number_id: str | None = None,
        access_token: str | None = None,
    ) -> str:
        # Per-restaurant number/token when provided, else this provider's env defaults.
        pid = phone_number_id or self._phone_number_id
        token = access_token or self._token

        # For file messages with raw base64 data, upload to Meta first to get media_id.
        if msg.type in (OutboundMessageType.IMAGE, OutboundMessageType.DOCUMENT):
            if "data" in msg.payload and "media_id" not in msg.payload:
                import base64
                raw = base64.b64decode(msg.payload["data"])
                media_id = await self._upload_media(
                    raw,
                    msg.payload["content_type"],
                    phone_number_id=pid,
                    access_token=token,
                )
                msg.payload = {**msg.payload, "media_id": media_id}

        url = f"{_GRAPH_BASE}/{pid}/messages"
        headers = {
            "Authorization": f"Bearer {token}",
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
