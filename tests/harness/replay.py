"""Transcript replay driver.

Drives a list of turn dicts through the real ``handle_inbound`` entrypoint and
snapshots, per turn:
  - outbound messages produced (body + msg_type; prefix="" because it is not
    stored in the Message payload — only in the idempotency_key)
  - draft cart rows (dish_id, dish_name, variant_name, notes, qty, price_aed)
  - order subtotal / total
  - dialogue_phase and full conv.state

Mirrors the fixture / construction pattern used in
``tests/conversation/test_engine_full_ai.py``.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.service import handle_catalog_order
from app.conversation.engine import handle_inbound
from app.conversation.models import Conversation, Message
from app.ordering.models import Order, OrderItem
from app.whatsapp.port import InboundMessage, MessageType
from tests.harness.result import OutboundCapture, TranscriptResult, TranscriptTurnResult


def _build_inbound(
    turn: dict,
    phone: str,
    idx: int,
    restaurant_phone: str,
) -> InboundMessage:
    ttype = turn.get("type", "text")
    payload = {k: v for k, v in turn.items() if k not in ("type",)}
    mt = {
        "text": MessageType.TEXT,
        "order": MessageType.ORDER,
        "button_reply": MessageType.BUTTON_REPLY,
        "audio": MessageType.AUDIO,
        # Any unrecognised type (e.g. WhatsApp reactions, system events) maps to
        # UNKNOWN so the engine's reaction/unknown path is exercised in evals.
    }.get(ttype, MessageType.UNKNOWN)
    return InboundMessage(
        wa_message_id=f"harness-{phone}-{idx}",
        from_phone=phone,
        type=mt,
        payload=payload,
        restaurant_phone=restaurant_phone,
        timestamp=1_700_000_000 + idx,  # fixed clock; no Date.now() in tests
    )


async def _conv_for(
    session: AsyncSession,
    restaurant_id: int,
    phone: str,
) -> Conversation | None:
    from app.identity.phones import normalize_phone

    normalized = normalize_phone(phone)
    return await session.scalar(
        select(Conversation).where(
            Conversation.restaurant_id == restaurant_id,
            Conversation.phone == normalized,
        )
    )


async def _snapshot_cart(
    session: AsyncSession,
    draft_order_id: int | None,
) -> tuple[list[dict], Decimal | None, Decimal | None]:
    if not draft_order_id:
        return [], None, None
    order = await session.get(Order, draft_order_id)
    if order is None:
        return [], None, None
    items = (
        await session.scalars(
            select(OrderItem).where(OrderItem.order_id == order.id)
        )
    ).all()
    rows = [
        {
            "dish_id": it.dish_id,
            "dish_name": it.dish_name,
            "variant_name": it.variant_name,
            "notes": it.notes,
            "qty": it.qty,
            "price_aed": it.price_aed,
        }
        for it in items
    ]
    return rows, order.subtotal, order.total


async def drive_turns(
    session: AsyncSession,
    *,
    restaurant_id: int,
    phone: str,
    turns: list[dict],
) -> TranscriptResult:
    """Drive *turns* through the real handle_inbound and return a TranscriptResult.

    Each turn dict must have at minimum ``{"type": "text"|"order"|"button_reply"|"audio",
    "text": str, ...}``.  Additional keys are forwarded as payload.

    The caller must supply a seeded menu and a valid restaurant row so that the
    conversation engine can resolve dishes and produce outbound messages.
    """
    # Look up the restaurant phone (required by InboundMessage) once upfront.
    from app.identity.models import Restaurant

    restaurant = await session.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise ValueError(f"Restaurant {restaurant_id} not found in DB")
    restaurant_phone = restaurant.phone

    result = TranscriptResult()

    for idx, turn in enumerate(turns):
        # High-water mark so we only capture THIS turn's new outbounds.
        before_id: int = (
            await session.scalar(
                select(Message.id)
                .where(Message.direction == "outbound")
                .order_by(Message.id.desc())
                .limit(1)
            )
        ) or 0

        inbound = _build_inbound(turn, phone, idx, restaurant_phone)
        # Mirror production webhook routing (webhook/router.py):
        #   1. MessageType.ORDER → handle_catalog_order
        #   2. Everything else   → handle_inbound (the old _CATALOG_KEYWORDS
        #      send_catalog bypass was deleted — menu keywords now route through
        #      the engine's _is_menu_request → _send_menu_or_catalog path).
        if inbound.type == MessageType.ORDER:
            await handle_catalog_order(session, inbound, restaurant_id=restaurant_id)
        else:
            await handle_inbound(session, inbound, restaurant_id=restaurant_id)
        await session.flush()

        # Capture outbound Message rows created during this turn.
        out_rows = (
            await session.scalars(
                select(Message)
                .where(
                    Message.direction == "outbound",
                    Message.id > before_id,
                )
                .order_by(Message.id)
            )
        ).all()

        outbounds = [
            OutboundCapture(
                # prefix is stored in idempotency_key (outbox), not in payload
                prefix="",
                body=(m.payload or {}).get("body") or (m.payload or {}).get("text", ""),
                msg_type=m.type,
            )
            for m in out_rows
        ]

        conv = await _conv_for(session, restaurant_id, phone)
        state = dict(conv.state or {}) if conv else {}

        rows, subtotal, total = await _snapshot_cart(
            session, state.get("draft_order_id")
        )

        result.turns.append(
            TranscriptTurnResult(
                inbound_text=turn.get("text", ""),
                outbounds=outbounds,
                cart_rows=rows,
                subtotal=subtotal,
                total=total,
                phase=state.get("dialogue_phase"),
                state=state,
            )
        )

    return result
