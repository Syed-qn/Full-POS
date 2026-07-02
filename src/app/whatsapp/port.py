from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class OutboundMessageType(StrEnum):
    TEXT = "text"
    BUTTONS = "buttons"
    CTA_URL = "cta_url"
    LIST = "list"
    LOCATION_REQUEST = "location_request"
    LOCATION = "location"
    IMAGE = "image"
    DOCUMENT = "document"
    TEMPLATE = "template"
    PRODUCT_LIST = "product_list"  # WhatsApp catalog products as tappable cards (catalog flow)
    CATALOG_MESSAGE = "catalog_message"  # "View catalog" button → native full-catalogue browse


class MessageType(StrEnum):
    TEXT = "text"
    BUTTON_REPLY = "button_reply"
    LIST_REPLY = "list_reply"
    LOCATION = "location"
    IMAGE = "image"
    AUDIO = "audio"
    DOCUMENT = "document"
    VIDEO = "video"
    STICKER = "sticker"
    ORDER = "order"  # WhatsApp catalog cart sent by the customer (separate catalog flow)
    UNKNOWN = "unknown"


@dataclass
class OutboundMessage:
    to_phone: str
    type: OutboundMessageType
    payload: dict
    idempotency_key: str
    # wa_message_id populated after successful send
    wa_message_id: str | None = None


@dataclass
class InboundMessage:
    wa_message_id: str
    from_phone: str
    type: MessageType
    payload: dict          # raw content; keys depend on type
    restaurant_phone: str  # the WABA number that received this
    timestamp: int = 0     # unix epoch from Meta payload


class WhatsAppPort(Protocol):
    async def send(
        self,
        msg: OutboundMessage,
        *,
        phone_number_id: str | None = None,
        access_token: str | None = None,
    ) -> str:
        """Send message; return wa_message_id.

        ``phone_number_id``/``access_token`` override the provider's defaults so a
        message is sent from the owning restaurant's own connected WhatsApp number.
        """
        ...

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        """Download inbound media (e.g. a voice note) by its provider media id.

        Returns ``(raw_bytes, mime_type)``. Used to fetch audio before transcription.
        """
        ...
