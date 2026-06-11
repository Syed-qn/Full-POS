# src/app/webhook/normalizer.py
import re

from app.whatsapp.port import InboundMessage, MessageType


def _normalize_phone(raw: str) -> str:
    """Normalize a phone to '+<digits>' (E.164-ish), stripping spaces, dashes,
    parentheses, etc.

    Meta's ``display_phone_number`` can arrive formatted ('+1 555-148-7637') while
    the same number elsewhere is bare ('15551487637'); both must compare equal so
    restaurant/customer matching never silently fails on cosmetic formatting.
    """
    digits = re.sub(r"\D", "", raw or "")
    return f"+{digits}" if digits else (raw or "")


def _parse_single_message(msg: dict, restaurant_phone: str) -> InboundMessage:
    msg_type = msg.get("type", "unknown")
    wa_id = msg["id"]
    from_phone = _normalize_phone(msg["from"])
    timestamp = int(msg.get("timestamp", 0))

    if msg_type == "text":
        return InboundMessage(
            wa_message_id=wa_id,
            from_phone=from_phone,
            type=MessageType.TEXT,
            payload={"text": msg["text"]["body"]},
            restaurant_phone=restaurant_phone,
            timestamp=timestamp,
        )

    if msg_type == "interactive":
        interactive = msg["interactive"]
        itype = interactive.get("type")
        if itype == "button_reply":
            br = interactive["button_reply"]
            return InboundMessage(
                wa_message_id=wa_id,
                from_phone=from_phone,
                type=MessageType.BUTTON_REPLY,
                payload={"id": br["id"], "title": br["title"]},
                restaurant_phone=restaurant_phone,
                timestamp=timestamp,
            )
        if itype == "list_reply":
            lr = interactive["list_reply"]
            return InboundMessage(
                wa_message_id=wa_id,
                from_phone=from_phone,
                type=MessageType.LIST_REPLY,
                payload={"id": lr["id"], "title": lr["title"]},
                restaurant_phone=restaurant_phone,
                timestamp=timestamp,
            )

    if msg_type == "location":
        loc = msg["location"]
        payload: dict = {"latitude": loc["latitude"], "longitude": loc["longitude"]}
        if "live_period" in loc:
            payload["is_live"] = True
        return InboundMessage(
            wa_message_id=wa_id,
            from_phone=from_phone,
            type=MessageType.LOCATION,
            payload=payload,
            restaurant_phone=restaurant_phone,
            timestamp=timestamp,
        )

    if msg_type == "image":
        return InboundMessage(
            wa_message_id=wa_id,
            from_phone=from_phone,
            type=MessageType.IMAGE,
            payload={
                "image_id": msg.get("image", {}).get("id"),
                "caption": msg.get("image", {}).get("caption"),
            },
            restaurant_phone=restaurant_phone,
            timestamp=timestamp,
        )

    return InboundMessage(
        wa_message_id=wa_id,
        from_phone=from_phone,
        type=MessageType.UNKNOWN,
        payload={"raw_type": msg_type},
        restaurant_phone=restaurant_phone,
        timestamp=timestamp,
    )


def parse_cloud_payload(payload: dict) -> list[InboundMessage]:
    """Parse a Meta Cloud API webhook payload into a list of InboundMessages.

    Returns empty list for status updates and other non-message events.
    """
    results: list[InboundMessage] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            raw_restaurant_phone = value.get("metadata", {}).get("display_phone_number", "")
            restaurant_phone = (
                _normalize_phone(raw_restaurant_phone) if raw_restaurant_phone else ""
            )
            for msg in value.get("messages", []):
                results.append(_parse_single_message(msg, restaurant_phone))
    return results
