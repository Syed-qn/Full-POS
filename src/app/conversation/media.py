"""Helpers for inbound WhatsApp attachments shown in the manager Chats UI."""
from __future__ import annotations

from app.whatsapp.port import InboundMessage, MessageType

# Message types whose bytes can be downloaded from Meta and shown in the dashboard.
ATTACHMENT_TYPES = frozenset({
    MessageType.AUDIO,
    MessageType.IMAGE,
    MessageType.DOCUMENT,
    MessageType.VIDEO,
    MessageType.STICKER,
})

_MEDIA_ID_KEYS = (
    "audio_id",
    "image_id",
    "document_id",
    "video_id",
    "sticker_id",
    "media_id",
)


def inbound_media_id(payload: dict) -> str | None:
    for key in _MEDIA_ID_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def inbound_media_mime(inbound: InboundMessage) -> str:
    payload = inbound.payload or {}
    mime = payload.get("mime")
    if isinstance(mime, str) and mime.strip():
        return mime.split(";")[0].strip()
    defaults = {
        MessageType.AUDIO: "audio/ogg",
        MessageType.IMAGE: "image/jpeg",
        MessageType.DOCUMENT: "application/pdf",
        MessageType.VIDEO: "video/mp4",
        MessageType.STICKER: "image/webp",
    }
    return defaults.get(inbound.type, "application/octet-stream")


async def download_inbound_media(inbound: InboundMessage) -> tuple[bytes | None, str | None]:
    """Fetch attachment bytes for image/document/video/sticker messages."""
    if inbound.type not in ATTACHMENT_TYPES or inbound.type == MessageType.AUDIO:
        return None, None
    media_id = inbound_media_id(inbound.payload or {})
    if not media_id:
        return None, None
    try:
        from app.whatsapp.factory import get_whatsapp_provider

        data, fetched_mime = await get_whatsapp_provider().download_media(media_id)
        if not data:
            return None, None
        payload_mime = inbound_media_mime(inbound)
        fetched = (fetched_mime or "").split(";")[0].strip()
        # Prefer the webhook mime when present (mock provider returns audio/ogg for all).
        resolved = payload_mime if (inbound.payload or {}).get("mime") else (fetched or payload_mime)
        return data, resolved
    except Exception:
        return None, None


def attachment_preview_label(msg_type: str, payload: dict) -> str:
    if msg_type == "image":
        return "📷 Photo"
    if msg_type == "document":
        name = payload.get("filename")
        if isinstance(name, str) and name.strip():
            return f"📎 {name.strip()}"
        return "📎 Document"
    if msg_type == "video":
        return "🎬 Video"
    if msg_type == "sticker":
        return "🙂 Sticker"
    if msg_type == "audio":
        return "🎙️ Voice"
    return "📎 Attachment"