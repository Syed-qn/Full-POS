# src/app/webhook/normalizer.py
from app.identity.phones import normalize_phone as _normalize_phone
from app.whatsapp.port import InboundMessage, MessageType


def _parse_single_message(msg: dict, restaurant_phone: str) -> InboundMessage | None:
    msg_type = msg.get("type", "unknown")
    if msg_type == "reaction":
        # A 👍/❤️ reaction needs no reply and no state change. As UNKNOWN it fell
        # through to the AI path, which answered a non-message with a canned
        # error and could mutate the cart (F83). Drop it before the engine.
        return None
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

    if msg_type == "button":
        # A tap on a TEMPLATE quick-reply button arrives as type "button" (not
        # interactive/button_reply). The developer-set payload (e.g.
        # "picked:123") is what the rider/customer flow keys on, so map it to
        # the same {"id", "title"} shape as an interactive button reply.
        btn = msg.get("button", {})
        return InboundMessage(
            wa_message_id=wa_id,
            from_phone=from_phone,
            type=MessageType.BUTTON_REPLY,
            payload={"id": btn.get("payload", ""), "title": btn.get("text", "")},
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
        image = msg.get("image", {})
        return InboundMessage(
            wa_message_id=wa_id,
            from_phone=from_phone,
            type=MessageType.IMAGE,
            payload={
                "image_id": image.get("id"),
                "mime": image.get("mime_type"),
                "caption": image.get("caption"),
            },
            restaurant_phone=restaurant_phone,
            timestamp=timestamp,
        )

    if msg_type == "document":
        doc = msg.get("document", {})
        return InboundMessage(
            wa_message_id=wa_id,
            from_phone=from_phone,
            type=MessageType.DOCUMENT,
            payload={
                "document_id": doc.get("id"),
                "mime": doc.get("mime_type"),
                "filename": doc.get("filename"),
                "caption": doc.get("caption"),
            },
            restaurant_phone=restaurant_phone,
            timestamp=timestamp,
        )

    if msg_type == "video":
        video = msg.get("video", {})
        return InboundMessage(
            wa_message_id=wa_id,
            from_phone=from_phone,
            type=MessageType.VIDEO,
            payload={
                "video_id": video.get("id"),
                "mime": video.get("mime_type"),
                "caption": video.get("caption"),
            },
            restaurant_phone=restaurant_phone,
            timestamp=timestamp,
        )

    if msg_type == "sticker":
        sticker = msg.get("sticker", {})
        return InboundMessage(
            wa_message_id=wa_id,
            from_phone=from_phone,
            type=MessageType.STICKER,
            payload={
                "sticker_id": sticker.get("id"),
                "mime": sticker.get("mime_type"),
            },
            restaurant_phone=restaurant_phone,
            timestamp=timestamp,
        )

    if msg_type == "audio":
        # WhatsApp voice notes (and uploaded audio) arrive as type "audio" carrying
        # a Meta media id; "voice": true marks a recorded voice note vs. an audio
        # file. We capture the id + mime so the engine can download and transcribe
        # it. The bytes are NOT in the webhook — they're fetched via the media id.
        audio = msg.get("audio", {})
        return InboundMessage(
            wa_message_id=wa_id,
            from_phone=from_phone,
            type=MessageType.AUDIO,
            payload={
                "audio_id": audio.get("id"),
                "mime": audio.get("mime_type"),
                "voice": bool(audio.get("voice", False)),
            },
            restaurant_phone=restaurant_phone,
            timestamp=timestamp,
        )

    if msg_type == "order":
        # A WhatsApp catalog cart. Meta sends the connected catalog_id plus the
        # product_items the customer added (each with its retailer/content id, qty,
        # unit price and currency). Handled by the SEPARATE catalog flow, not the
        # conversation engine.
        order = msg.get("order", {})
        return InboundMessage(
            wa_message_id=wa_id,
            from_phone=from_phone,
            type=MessageType.ORDER,
            payload={
                "catalog_id": order.get("catalog_id"),
                "text": order.get("text"),
                "product_items": order.get("product_items", []),
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
                parsed = _parse_single_message(msg, restaurant_phone)
                if parsed is not None:
                    results.append(parsed)
    return results


def slice_message_payload(payload: dict, wa_message_id: str) -> dict:
    """Return a minimal webhook payload containing only the one message row.

    Storing the full Meta batch on every idempotency row bloats the table when a
    single webhook carries many messages; each event only needs its own slice."""
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []):
                if msg.get("id") == wa_message_id:
                    slim_value = {
                        k: v for k, v in value.items() if k != "messages"
                    }
                    slim_value["messages"] = [msg]
                    return {
                        "object": payload.get("object"),
                        "entry": [{
                            **{k: v for k, v in entry.items() if k != "changes"},
                            "changes": [{
                                "field": change.get("field"),
                                "value": slim_value,
                            }],
                        }],
                    }
    return payload


def parse_status_events(payload: dict) -> list[dict]:
    """Extract delivery-status events (value.statuses) from a Cloud API payload.

    Only ``failed`` matters operationally today — a message Meta accepted at send
    time but could not deliver (closed 24h window, blocked recipient) previously
    vanished without trace. Each event: {wa_message_id, status, error_code}.
    """
    events: list[dict] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for st in change.get("value", {}).get("statuses", []):
                errors = st.get("errors") or []
                events.append({
                    "wa_message_id": st.get("id"),
                    "status": st.get("status"),
                    "error_code": errors[0].get("code") if errors else None,
                })
    return events
