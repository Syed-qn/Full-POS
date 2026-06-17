from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class OutboundMessageType(StrEnum):
    TEXT = "text"
    BUTTONS = "buttons"
    LIST = "list"
    LOCATION_REQUEST = "location_request"
    IMAGE = "image"
    DOCUMENT = "document"
    TEMPLATE = "template"


class MessageType(StrEnum):
    TEXT = "text"
    BUTTON_REPLY = "button_reply"
    LIST_REPLY = "list_reply"
    LOCATION = "location"
    IMAGE = "image"
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
    async def send(self, msg: OutboundMessage) -> str:
        """Send message; return wa_message_id."""
        ...
