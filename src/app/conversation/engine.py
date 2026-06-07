from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.conversation.models import Conversation
from app.conversation.service import get_or_create_conversation, record_message
from app.ordering.matching import MatchConfidence, find_dish_matches
from app.outbox.service import enqueue_message
from app.whatsapp.port import InboundMessage, MessageType, OutboundMessageType


async def _render_menu(session: AsyncSession, restaurant_id: int) -> str:
    """Render the active menu as categorized text."""
    from app.menu.models import Dish, Menu

    menu = await session.scalar(
        select(Menu).where(
            Menu.restaurant_id == restaurant_id,
            Menu.status == "active",
        )
    )
    if menu is None:
        return "Our menu is currently unavailable. Please try again later."

    dishes = await session.scalars(
        select(Dish)
        .where(Dish.menu_id == menu.id, Dish.is_available == True)  # noqa: E712
        .order_by(Dish.category, Dish.dish_number)
    )
    dish_list = list(dishes)
    if not dish_list:
        return "Our menu is currently unavailable. Please try again later."

    lines: list[str] = ["Welcome! Here is our menu:\n"]
    current_category: str | None = None
    for dish in dish_list:
        if dish.category != current_category:
            current_category = dish.category
            if current_category:
                lines.append(f"\n*{current_category}*")
        price = Decimal(dish.price_aed).normalize()
        lines.append(f"{dish.dish_number}. {dish.name} — AED {price}")

    return "\n".join(lines)


async def _handle_greeting(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Send uploaded menu files (image/PDF) then a short prompt; fall back to text menu."""
    import base64

    from app.config import get_settings
    from app.menu.models import Menu, MenuFile
    from app.menu.storage import FileBlobStore

    menu = await session.scalar(
        select(Menu).where(
            Menu.restaurant_id == restaurant_id,
            Menu.status == "active",
        )
    )

    files_sent = 0
    if menu is not None:
        menu_files = list(
            (
                await session.scalars(
                    select(MenuFile).where(MenuFile.menu_id == menu.id)
                )
            ).all()
        )
        store = FileBlobStore(get_settings().upload_dir)
        for mf in menu_files:
            data = store.get(restaurant_id=restaurant_id, digest=mf.sha256)
            if data is None:
                continue
            b64 = base64.b64encode(data).decode()
            if mf.content_type.startswith("image/"):
                msg_type = OutboundMessageType.IMAGE
                payload: dict = {
                    "data": b64,
                    "content_type": mf.content_type,
                    "caption": mf.original_filename or "Menu",
                }
            else:
                msg_type = OutboundMessageType.DOCUMENT
                payload = {
                    "data": b64,
                    "content_type": mf.content_type,
                    "filename": mf.original_filename or "menu.pdf",
                    "caption": "Our menu",
                }
            await enqueue_message(
                session,
                restaurant_id=restaurant_id,
                to_phone=inbound.from_phone,
                msg_type=msg_type,
                payload=payload,
                idempotency_key=f"greeting-file-{mf.sha256[:16]}-{conv.id}-{inbound.wa_message_id}",
            )
            files_sent += 1

    if files_sent == 0:
        # No uploaded files — render the digital menu as text
        menu_text = await _render_menu(session, restaurant_id)
        await enqueue_message(
            session,
            restaurant_id=restaurant_id,
            to_phone=inbound.from_phone,
            msg_type=OutboundMessageType.TEXT,
            payload={"body": menu_text},
            idempotency_key=f"greeting-{conv.id}-{inbound.wa_message_id}",
        )
    else:
        await enqueue_message(
            session,
            restaurant_id=restaurant_id,
            to_phone=inbound.from_phone,
            msg_type=OutboundMessageType.TEXT,
            payload={"body": "Reply with the dish name to order."},
            idempotency_key=f"greeting-prompt-{conv.id}-{inbound.wa_message_id}",
        )

    conv.state = {**conv.state, "dialogue_state": "menu_sent"}
    await record_audit(
        session,
        actor="system",
        restaurant_id=restaurant_id,
        entity="conversation",
        entity_id=str(conv.id),
        action="state_transition",
        before={"dialogue_state": "greeting"},
        after={"dialogue_state": "menu_sent"},
    )


def _set_state(conv: Conversation, **updates) -> None:
    """Merge keys into conv.state (JSONB) without losing existing keys."""
    conv.state = {**conv.state, **updates}


async def _send_text(
    session: AsyncSession,
    *,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    prefix: str,
    body: str,
) -> None:
    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=inbound.from_phone,
        msg_type=OutboundMessageType.TEXT,
        payload={"body": body},
        idempotency_key=f"{prefix}-{conv.id}-{inbound.wa_message_id}",
    )


async def _send_buttons(
    session: AsyncSession,
    *,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    prefix: str,
    body: str,
    buttons: list[dict],
) -> None:
    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=inbound.from_phone,
        msg_type=OutboundMessageType.BUTTONS,
        payload={"body": body, "buttons": buttons},
        idempotency_key=f"{prefix}-{conv.id}-{inbound.wa_message_id}",
    )


async def _handle_collecting_items(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Parse dish name/number + qty from free text; add, disambiguate, or retry."""
    from app.ordering.models import Order
    from app.ordering.service import (
        add_item,
        create_draft_order,
        get_or_create_customer,
        parse_qty_and_text,
    )

    if inbound.type != MessageType.TEXT:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="need-text",
            body="Please type the name or number of a dish from the menu.",
        )
        return

    text = (inbound.payload.get("text") or "").strip()
    qty, dish_query = parse_qty_and_text(text)

    # "done" → proceed to delivery details (only if at least one item exists).
    if dish_query.lower() in ("done", "checkout", "that's all", "thats all"):
        draft_order_id = conv.state.get("draft_order_id")
        if not draft_order_id:
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="empty-cart",
                body="Your cart is empty. Please add at least one dish before proceeding.",
            )
            return
        _set_state(conv, dialogue_state="address_capture")
        await _send_buttons(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="ask-location",
            body="Great! Please share your delivery location pin, or type your address.",
            buttons=[{"id": "share_location", "title": "Share location"}],
        )
        return

    # "What is X?" dish question → describer.
    if dish_query.lower().startswith("what is "):
        from app.llm.factory import get_describer

        item_name = dish_query[8:].strip().rstrip("?")
        desc = get_describer().describe(item_name, "")
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="dish-desc", body=desc,
        )
        return

    result = await find_dish_matches(session, restaurant_id=restaurant_id, query=dish_query)

    if result.confidence == MatchConfidence.NO_MATCH:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="no-match",
            body="Sorry, I couldn't find that dish. Please reply with the dish "
                 "number from the menu, or try a different name.",
        )
        return

    if result.confidence == MatchConfidence.AMBIGUOUS:
        # Let LLM arbiter resolve ambiguity — avoids ping-pong with the customer.
        from app.llm.factory import get_arbiter
        try:
            dish = await get_arbiter().arbitrate(dish_query, result.candidates[:3])
        except Exception:
            dish = None
        if dish is None:
            options = " or ".join(
                f"{d.dish_number}. {d.name} (AED {Decimal(d.price_aed).normalize()})"
                for d in result.candidates[:3]
            )
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="ambiguous",
                body=f"Did you mean {options}? Please reply with the dish number.",
            )
            return
        # Arbiter resolved — fall through to add item below.

    # DIRECT match or arbiter-resolved → add to draft order.
    dish = dish if result.confidence == MatchConfidence.AMBIGUOUS else result.candidates[0]
    customer = await get_or_create_customer(
        session, restaurant_id=restaurant_id, phone=inbound.from_phone,
    )
    draft_order_id = conv.state.get("draft_order_id")
    order = await session.get(Order, draft_order_id) if draft_order_id else None
    if order is None:
        order = await create_draft_order(
            session, restaurant_id=restaurant_id, customer_id=customer.id,
        )
        _set_state(conv, draft_order_id=order.id)

    await add_item(session, order=order, dish=dish, qty=qty)
    _set_state(conv, dialogue_state="collecting_items")

    price = Decimal(dish.price_aed).normalize()
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="item-added",
        body=(
            f"Added {qty}x {dish.dish_number}. {dish.name} (AED {price}).\n"
            f"Reply with more items, or send 'done' to proceed to delivery details."
        ),
    )


async def _finalize_with_stored_address(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    stored,
    *,
    rest_lat: float,
    rest_lng: float,
) -> None:
    """Attach a returning customer's saved address to the draft and summarise."""
    from datetime import datetime, timezone

    from app.geo.haversine import distance_km
    from app.ordering.fees import UndeliverableError, calculate_fee
    from app.ordering.models import Order

    draft_order_id = conv.state.get("draft_order_id")
    order = await session.get(Order, draft_order_id) if draft_order_id else None
    if order is None:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="no-draft-saved",
            body="Your cart is empty. Please send 'hi' to start a new order.",
        )
        return

    dist = None
    fee = Decimal("0.00")
    if stored.latitude is not None and stored.longitude is not None:
        dist = distance_km(rest_lat, rest_lng, stored.latitude, stored.longitude)
        try:
            fee = calculate_fee(dist)
        except UndeliverableError:
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="undeliverable-saved",
                body="Sorry, your saved address is outside our delivery area "
                     "(maximum 10 km). Please share a new location.",
            )
            return

    order.address_id = stored.id
    order.distance_km = dist
    order.delivery_fee_aed = fee
    order.total = order.subtotal + fee
    stored.last_used_at = datetime.now(timezone.utc)
    await session.flush()

    _set_state(conv, dialogue_state="order_confirmation", pending_order_id=order.id)
    await _send_order_summary(session, conv, inbound, restaurant_id, order)


async def _handle_address_capture(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Capture delivery address: location pin (fee/radius check) or text address."""
    from app.geo.haversine import distance_km
    from app.identity.models import Restaurant
    from app.ordering.fees import UndeliverableError, calculate_fee
    from app.ordering.service import get_last_address, get_or_create_customer

    restaurant = await session.get(Restaurant, restaurant_id)
    rest_lat = restaurant.lat if restaurant else 25.2048
    rest_lng = restaurant.lng if restaurant else 55.2708

    customer = await get_or_create_customer(
        session, restaurant_id=restaurant_id, phone=inbound.from_phone,
    )

    # Button reply on a previously-offered saved address.
    if inbound.type == MessageType.BUTTON_REPLY:
        btn_id = inbound.payload.get("id", "")
        if btn_id == "use_saved_address":
            stored = await get_last_address(session, customer.id)
            if stored is not None:
                await _finalize_with_stored_address(
                    session, conv, inbound, restaurant_id, stored,
                    rest_lat=rest_lat, rest_lng=rest_lng,
                )
                return
        if btn_id == "new_address":
            _set_state(conv, address_offer_made=True)
            await _send_buttons(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="ask-location",
                body="Please share your delivery location pin, or type your address.",
                buttons=[{"id": "share_location", "title": "Share location"}],
            )
            return

    # Returning customer: offer the saved address once before asking for a pin.
    if not conv.state.get("address_offer_made"):
        stored = await get_last_address(session, customer.id)
        if stored is not None:
            _set_state(conv, address_offer_made=True)
            label = ", ".join(
                p for p in (stored.room_apartment, stored.building) if p
            ) or "your saved address"
            await _send_buttons(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="offer-saved-addr",
                body=f"Welcome back! Deliver to your saved address ({label})?",
                buttons=[
                    {"id": "use_saved_address", "title": "Use saved address"},
                    {"id": "new_address", "title": "New address"},
                ],
            )
            return

    if inbound.type == MessageType.LOCATION:
        lat = inbound.payload["latitude"]
        lon = inbound.payload["longitude"]
        dist = distance_km(rest_lat, rest_lng, lat, lon)
        try:
            fee = calculate_fee(dist)
        except UndeliverableError:
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="undeliverable",
                body="Sorry, your location is outside our delivery area "
                     "(maximum 10 km). We can't deliver there.",
            )
            return

        await get_or_create_customer(
            session, restaurant_id=restaurant_id, phone=inbound.from_phone,
        )
        _set_state(
            conv,
            pin_lat=lat, pin_lon=lon,
            distance_km=dist, delivery_fee=str(fee),
            dialogue_state="address_text_pending",
        )
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="ask-text-addr",
            body="Got it! Please send your room/apartment number and building, "
                 "separated by a comma.\nExample: 101, Tower A",
        )
        return

    # Text address: expect "room/apartment, building".
    text = (inbound.payload.get("text") or "").strip()
    if "," not in text:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="addr-format",
            body="Please include a comma between your room/apartment and building.\n"
                 "Example: 101, Tower A",
        )
        return

    room_apartment, building = (p.strip() for p in text.split(",", 1))
    _set_state(
        conv,
        pending_room=room_apartment,
        pending_building=building,
        dialogue_state="receiver_details",
    )
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="ask-receiver",
        body=f"Address noted: room/apartment number {room_apartment} building {building}.\n"
             f"Who should the rider ask for? Please reply with the receiver's name.",
    )


async def _handle_receiver_details(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Capture the receiver name, persist the address + order, then summarise."""
    from app.ordering.fees import calculate_fee
    from app.ordering.models import Order
    from app.ordering.service import get_or_create_customer, upsert_address

    receiver_name = (inbound.payload.get("text") or "").strip()
    if not receiver_name:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="ask-receiver-again",
            body="Please reply with the receiver's name.",
        )
        return

    customer = await get_or_create_customer(
        session, restaurant_id=restaurant_id, phone=inbound.from_phone,
    )
    addr = await upsert_address(
        session,
        customer_id=customer.id,
        latitude=conv.state.get("pin_lat"),
        longitude=conv.state.get("pin_lon"),
        room_apartment=conv.state.get("pending_room", ""),
        building=conv.state.get("pending_building", ""),
        receiver_name=receiver_name,
        confirmed=True,
    )

    draft_order_id = conv.state.get("draft_order_id")
    order = await session.get(Order, draft_order_id) if draft_order_id else None
    if order is None:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="no-draft",
            body="Your cart is empty. Please send 'hi' to start a new order.",
        )
        return

    dist = conv.state.get("distance_km")
    fee = Decimal(conv.state.get("delivery_fee", "0.00")) if conv.state.get("delivery_fee") \
        else calculate_fee(dist if dist is not None else 0.0)
    order.address_id = addr.id
    order.distance_km = dist
    order.delivery_fee_aed = fee
    order.total = order.subtotal + fee
    await session.flush()

    _set_state(conv, dialogue_state="order_confirmation", pending_order_id=order.id)
    await _send_order_summary(session, conv, inbound, restaurant_id, order)


async def _send_order_summary(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    order,
) -> None:
    """Render order summary with totals + ETA and confirm/cancel buttons."""
    from app.ordering.models import OrderItem
    from app.weather.factory import get_weather_port

    items = (
        await session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ).all()
    item_lines = "\n".join(
        f"  {it.qty}x {it.dish_number}. {it.dish_name} — "
        f"AED {Decimal(it.price_aed * it.qty).normalize()}"
        for it in items
    )

    # Weather disclosure: if a delay is active, disclose at confirmation time so
    # that a later weather-caused delay does NOT trigger an automatic coupon.
    weather_note = ""
    if get_weather_port().is_delay_active():
        order.weather_delay_disclosed = True
        weather_note = (
            "\nNote: severe weather may delay delivery beyond the usual time."
        )
        await session.flush()

    summary = (
        f"Order summary:\n{item_lines}\n\n"
        f"Subtotal: AED {Decimal(order.subtotal).normalize()}\n"
        f"Delivery fee: AED {Decimal(order.delivery_fee_aed).normalize()}\n"
        f"Total: AED {Decimal(order.total).normalize()}\n"
        f"Payment: COD (cash on delivery)\n"
        f"ETA: 40 minutes{weather_note}\n\n"
        f"Confirm your order?"
    )
    await _send_buttons(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="order-summary", body=summary,
        buttons=[
            {"id": "confirm_order", "title": "Confirm order"},
            {"id": "cancel_order", "title": "Cancel"},
        ],
    )


async def _handle_order_confirmation(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Handle confirm/cancel buttons on the order summary."""
    from app.ordering.fsm import OrderStatus
    from app.ordering.fsm import transition as fsm_transition
    from app.ordering.models import Order
    from app.ordering.service import finalize_confirmation

    order_id = conv.state.get("pending_order_id")
    order = await session.get(Order, order_id) if order_id else None
    if order is None:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="no-pending-order",
            body="There is no order to confirm. Send 'hi' to start a new order.",
        )
        return

    btn_id = inbound.payload.get("id", "") if inbound.type == MessageType.BUTTON_REPLY else ""

    if btn_id == "confirm_order":
        await finalize_confirmation(session, order=order, actor="customer")
        _set_state(conv, dialogue_state="order_placed")
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="order-confirmed",
            body=(
                f"Order confirmed! Order #{order.order_number}.\n"
                f"Total: AED {Decimal(order.total).normalize()} "
                f"(COD — cash on delivery).\n"
                f"Your food will arrive within 40 minutes."
            ),
        )
        return

    if btn_id == "cancel_order":
        if order.status in (OrderStatus.DRAFT, OrderStatus.PENDING_CONFIRMATION):
            await fsm_transition(session, order, OrderStatus.CANCELLED, actor="customer")
        _set_state(conv, dialogue_state="cancelled", draft_order_id=None, pending_order_id=None)
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="order-cancelled",
            body="No problem — your order has been cancelled. Send 'hi' to start again.",
        )
        return

    # Unknown input while awaiting confirmation → re-prompt with the summary.
    await _send_order_summary(session, conv, inbound, restaurant_id, order)


async def _handle_modify_intent(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Start modify flow: lookup recent modifiable order (conv.state pending/ modify_order_id or by phone like status query).
    If before ready, set modify_items + empty proposed; prompt for new items (SLA restart noted).
    """
    from app.ordering.fsm import OrderStatus
    from app.ordering.models import Customer, Order

    order = None
    mod_id = conv.state.get("modify_order_id") or conv.state.get("pending_order_id")
    if mod_id:
        order = await session.get(Order, mod_id)

    if order is None:
        customer = await session.scalar(
            select(Customer).where(
                Customer.restaurant_id == restaurant_id,
                Customer.phone == inbound.from_phone,
            )
        )
        if customer:
            terminal = {
                str(OrderStatus.DELIVERED), str(OrderStatus.CANCELLED),
                str(OrderStatus.UNDELIVERABLE), str(OrderStatus.RESOLD),
                str(OrderStatus.WRITTEN_OFF),
            }
            order = await session.scalar(
                select(Order)
                .where(
                    Order.restaurant_id == restaurant_id,
                    Order.customer_id == customer.id,
                    Order.status.notin_(terminal),
                )
                .order_by(Order.created_at.desc())
                .limit(1)
            )

    if order is None:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="modify-no-order",
            body="You don't have any active orders to modify. Send 'hi' to place a new order.",
        )
        return

    # Mirror service _NON_MODIFIABLE_STATUSES (strings for safety, no private cross)
    non_mod_strs = {
        "ready", "assigned", "picked_up", "arriving", "delivered", "cancelled",
        "undeliverable", "on_resale", "resold", "written_off",
    }
    if str(order.status) in non_mod_strs:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="modify-blocked",
            body=f"Order #{order.order_number} cannot be modified (status: {order.status}). Modifications allowed only before ready per spec.",
        )
        return

    _set_state(conv, dialogue_state="modify_items", modify_order_id=order.id, modify_proposed=[])
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="modify-start",
        body=(
            f"Sure, let's modify order #{order.order_number}. "
            f"Reply with updated dishes (e.g. '2x 110' or names from menu), or 'done' when ready to review changes. "
            f"After you confirm, the 40-min SLA clock restarts."
        ),
    )


async def _handle_modify_items(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Collect proposed replacement items for modify (re-uses _handle_collecting_items logic:
    parse_qty_and_text, find_dish_matches + confidence paths, 'what is' describer, 'done' gate).
    Stores serializable proposed list in conv.state['modify_proposed']; no DB mutation until confirm.
    """
    from app.ordering.service import parse_qty_and_text

    if inbound.type != MessageType.TEXT:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="need-text-mod",
            body="Please type the name or number of a dish from the menu to update your order.",
        )
        return

    text = (inbound.payload.get("text") or "").strip()
    qty, dish_query = parse_qty_and_text(text)
    lower_q = dish_query.lower()

    if lower_q in ("done", "checkout", "that's all", "thats all"):
        mod_id = conv.state.get("modify_order_id")
        proposed = conv.state.get("modify_proposed", []) or []
        if not mod_id or not proposed:
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="modify-no-proposed",
                body="No changes proposed yet. Reply with dishes or send 'hi' to start over.",
            )
            return
        _set_state(conv, dialogue_state="modify_confirm")
        await _send_modify_summary(session, conv, inbound, restaurant_id, mod_id, proposed)
        return

    if lower_q.startswith("what is "):
        from app.llm.factory import get_describer
        item_name = dish_query[8:].strip().rstrip("?")
        desc = get_describer().describe(item_name, "")
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="dish-desc-mod", body=desc,
        )
        return

    result = await find_dish_matches(session, restaurant_id=restaurant_id, query=dish_query)

    if result.confidence == MatchConfidence.NO_MATCH:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="no-match-mod",
            body="Sorry, I couldn't find that dish. Please reply with the dish number from the menu, or try a different name.",
        )
        return

    if result.confidence == MatchConfidence.AMBIGUOUS:
        options = " or ".join(
            f"{d.dish_number}. {d.name} (AED {Decimal(d.price_aed).normalize()})"
            for d in result.candidates[:3]
        )
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="ambiguous-mod",
            body=f"Did you mean {options}? Please reply with the dish number.",
        )
        return

    # Direct match: accumulate in proposed (replaces cart-add in collecting_items)
    dish = result.candidates[0]
    proposed = list(conv.state.get("modify_proposed", []) or [])
    proposed.append({
        "dish_id": dish.id,
        "dish_number": dish.dish_number,
        "name": dish.name,
        "price_aed": str(dish.price_aed),
        "qty": qty,
    })
    _set_state(conv, dialogue_state="modify_items", modify_proposed=proposed)

    price = Decimal(dish.price_aed).normalize()
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="item-proposed",
        body=(
            f"Added {qty}x {dish.dish_number}. {dish.name} (AED {price}) to your modification.\n"
            f"Reply with more items, or send 'done' to review and confirm (SLA restarts on confirm)."
        ),
    )


async def _send_modify_summary(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    order_id: int,
    proposed: list[dict],
) -> None:
    """Show current vs proposed + totals; buttons for confirm_modify / cancel_modify."""
    from app.ordering.models import Order, OrderItem

    order = await session.get(Order, order_id)
    if order is None:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="no-mod-order", body="Order not found.",
        )
        return

    current_items = list((
        await session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ).all())
    curr_lines = "\n".join(
        f"  {it.qty}x {it.dish_number}. {it.dish_name} — "
        f"AED {Decimal(it.price_aed * it.qty).normalize()}"
        for it in current_items
    ) or "  (none)"

    prop_lines = "\n".join(
        f"  {p['qty']}x {p.get('dish_number', '?')}. {p.get('name', '?')} — "
        f"AED {Decimal(str(p['price_aed'])) * p['qty'] :.2f}"
        for p in proposed
    ) or "  (none)"

    new_sub = sum(Decimal(str(p["price_aed"])) * p["qty"] for p in proposed)
    new_total = new_sub + (order.delivery_fee_aed or Decimal("0"))

    body = (
        f"Current order #{order.order_number}:\n{curr_lines}\n\n"
        f"Proposed new items:\n{prop_lines}\n\n"
        f"New subtotal: AED {new_sub.normalize()}\n"
        f"Delivery: AED {Decimal(order.delivery_fee_aed or 0).normalize()}\n"
        f"New total: AED {new_total.normalize()}\n\n"
        f"Confirm these changes? (COD, 40-min SLA restarts after your confirm)"
    )
    await _send_buttons(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="modify-summary",
        body=body,
        buttons=[
            {"id": "confirm_modify", "title": "Confirm changes"},
            {"id": "cancel_modify", "title": "Keep original"},
        ],
    )


async def _handle_modify_confirm(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Confirm handler for modify: load order WITH FOR UPDATE (per spec §4.2.8 and fsm concurrency note),
    build dish list, call ordering.service.modify_order (handles items replace, recalc, SLA restart, audit).
    Bounded context: engine only calls service, no direct model writes. Full flow wired (intent, states, confirm).
    """
    from app.menu.models import Dish
    from app.ordering.models import Order
    from app.ordering.service import modify_order

    mod_id = conv.state.get("modify_order_id")
    if not mod_id:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="no-mod-pending",
            body="No modification in progress. Send 'hi' to start a new order.",
        )
        return

    # for_update per spec §4.2.8 (modify only before ready) and fsm concurrency (race with kitchen ready). Full modify dialogue implemented.
    order = await session.get(Order, mod_id, with_for_update=True) if mod_id else None
    if order is None:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="no-mod-order",
            body="Order not found for modification.",
        )
        return

    btn_id = inbound.payload.get("id", "") if inbound.type == MessageType.BUTTON_REPLY else ""

    if btn_id == "confirm_modify":
        proposed = conv.state.get("modify_proposed", []) or []
        if not proposed:
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="modify-empty",
                body="No proposed changes. Modification cancelled.",
            )
            _set_state(conv, dialogue_state="order_placed", modify_order_id=None, modify_proposed=None)
            return

        new_items: list[dict] = []
        for p in proposed:
            dish = await session.get(Dish, p["dish_id"])
            if dish is not None:
                new_items.append({"dish": dish, "qty": p.get("qty", 1), "notes": None})

        if new_items:
            await modify_order(session, order=order, new_items=new_items, actor="customer")
            # commit by caller (webhook/router)

        _set_state(
            conv,
            dialogue_state="order_placed",
            modify_order_id=None,
            modify_proposed=None,
        )
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="modify-confirmed",
            body=(
                f"Order #{order.order_number} updated!\n"
                f"New total: AED {Decimal(order.total).normalize()} (COD).\n"
                f"The 40-minute delivery window restarts now."
            ),
        )
        return

    if btn_id == "cancel_modify":
        _set_state(conv, dialogue_state="order_placed", modify_order_id=None, modify_proposed=None)
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="modify-cancelled",
            body="Modification cancelled — original order unchanged. Send 'hi' if needed.",
        )
        return

    # re-prompt
    proposed = conv.state.get("modify_proposed", []) or []
    await _send_modify_summary(session, conv, inbound, restaurant_id, mod_id, proposed)


async def _handle_status_query(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Reply to 'where is my order' with the current order status and ETA.

    For en-route statuses (assigned / picked_up / arriving) the reply is
    built by ``build_tracking_reply`` which uses the rider's latest GPS ping
    and the geo provider to compute a live ETA.
    """
    from datetime import datetime, timezone

    from app.dispatch.tracking import build_tracking_reply
    from app.geo.factory import get_geo_provider
    from app.ordering.fsm import OrderStatus
    from app.ordering.models import Customer, Order

    customer = await session.scalar(
        select(Customer).where(
            Customer.restaurant_id == restaurant_id,
            Customer.phone == inbound.from_phone,
        )
    )
    if not customer:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="status-no-customer",
            body="I don't see any recent orders for this number. "
                 "Send 'hi' to start a new order.",
        )
        return

    terminal = {
        str(OrderStatus.DELIVERED), str(OrderStatus.CANCELLED),
        str(OrderStatus.UNDELIVERABLE), str(OrderStatus.RESOLD),
        str(OrderStatus.WRITTEN_OFF),
    }
    order = await session.scalar(
        select(Order)
        .where(
            Order.restaurant_id == restaurant_id,
            Order.customer_id == customer.id,
            Order.status.notin_(terminal),
        )
        .order_by(Order.created_at.desc())
        .limit(1)
    )

    if not order:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="status-no-order",
            body="You don't have any active orders right now. "
                 "Send 'hi' to place a new order.",
        )
        return

    _en_route = {
        str(OrderStatus.ASSIGNED),
        str(OrderStatus.PICKED_UP),
        str(OrderStatus.ARRIVING),
    }

    if str(order.status) in _en_route:
        # Delegate to build_tracking_reply for live rider ETA via GPS + geo provider.
        body = await build_tracking_reply(
            session, order=order, geo=get_geo_provider()
        )
    else:
        status_messages = {
            str(OrderStatus.DRAFT): "Your order is being assembled.",
            str(OrderStatus.PENDING_CONFIRMATION): "Your order is waiting for your confirmation.",
            str(OrderStatus.CONFIRMED): (
                f"Your order #{order.order_number} is confirmed and will be ready "
                f"in about 40 minutes."
            ),
            str(OrderStatus.PREPARING): (
                f"Your order #{order.order_number} is being prepared in the kitchen."
            ),
            str(OrderStatus.READY): (
                f"Your order #{order.order_number} is ready and waiting for the rider."
            ),
            str(OrderStatus.ON_RESALE): (
                "Your order was cancelled. Please contact the restaurant for more information."
            ),
        }
        body = status_messages.get(str(order.status), f"Order status: {order.status}.")

        if order.sla_deadline:
            remaining = int(
                (order.sla_deadline - datetime.now(timezone.utc)).total_seconds() / 60
            )
            if 0 < remaining <= 40 and str(order.status) in (
                str(OrderStatus.CONFIRMED),
                str(OrderStatus.PREPARING),
                str(OrderStatus.READY),
            ):
                body += f" Estimated time remaining: ~{remaining} minutes."

    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="status-reply", body=body,
    )


async def _resolve_counterpart(
    session: AsyncSession, restaurant_id: int, phone: str
):
    """Return ("rider", rider) if the phone is a rider for this tenant, else ("customer", None)."""
    from app.identity.models import Rider

    rider = await session.scalar(
        select(Rider).where(
            Rider.restaurant_id == restaurant_id, Rider.phone == phone
        )
    )
    return ("rider", rider) if rider is not None else ("customer", None)


async def _handle_rider_inbound(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    rider,
) -> None:
    """Rider-side handlers: location pings (button actions added in Task 11)."""
    from app.dispatch.rider_location import update_rider_location

    if inbound.type == MessageType.LOCATION:
        await update_rider_location(
            session,
            rider=rider,
            latitude=float(inbound.payload["latitude"]),
            longitude=float(inbound.payload["longitude"]),
        )
        # Geofence check per spec §4.4 + transcript: if near current stop (~100m), send dual "Delivered" | "Delivered and Next Order Location"
        # Button click is ONLY way to reveal next location (flow integrity). Power bank provided per ops policy for all-day location.
        from app.dispatch.rider_flow import check_and_send_near_dual_if_applicable
        await check_and_send_near_dual_if_applicable(session, restaurant_id=restaurant_id, rider=rider)
        return

    if inbound.type == MessageType.BUTTON_REPLY:
        # Accept either payload key shape ("button_id" from dispatch buttons,
        # "id" from the shared button helper).
        button_id = inbound.payload.get("button_id") or inbound.payload.get("id", "")
        if button_id.startswith("picked:"):
            from app.dispatch.rider_flow import handle_orders_picked

            await handle_orders_picked(
                session,
                restaurant_id=restaurant_id,
                rider=rider,
                batch_id=int(button_id.split(":", 1)[1]),
            )
        elif button_id.startswith("delivered:"):
            from app.dispatch.rider_flow import handle_delivered

            await handle_delivered(
                session,
                restaurant_id=restaurant_id,
                rider=rider,
                order_id=int(button_id.split(":", 1)[1]),
            )
        elif button_id.startswith("delivered_next:"):
            from app.dispatch.rider_flow import handle_delivered

            await handle_delivered(
                session,
                restaurant_id=restaurant_id,
                rider=rider,
                order_id=int(button_id.split(":", 1)[1]),
            )
            # "Delivered and Next Order Location" click reveals next stop location immediately (bypass near wait for subsequent)
            return
        return
    # Other rider message types (e.g. free text) are ignored — flow is button-only.


async def handle_inbound(
    session: AsyncSession,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Main entry point: load conversation → record message → dispatch state handler."""
    counterpart, rider = await _resolve_counterpart(
        session, restaurant_id, inbound.from_phone
    )
    conv = await get_or_create_conversation(
        session,
        restaurant_id=restaurant_id,
        phone=inbound.from_phone,
        counterpart=counterpart,
    )

    await record_message(
        session,
        conversation_id=conv.id,
        direction="inbound",
        wa_message_id=inbound.wa_message_id,
        msg_type=str(inbound.type),
        payload=inbound.payload,
        ts=inbound.timestamp,
    )

    # STOP opt-out — must be checked before any dialogue processing
    from app.marketing.optout import is_stop_keyword, record_opt_out
    if is_stop_keyword(inbound.payload.get("text", "") if inbound.type == MessageType.TEXT else ""):
        await record_opt_out(
            session,
            restaurant_id=restaurant_id,
            phone=inbound.from_phone,
        )
        await enqueue_message(
            session,
            restaurant_id=restaurant_id,
            to_phone=inbound.from_phone,
            msg_type=OutboundMessageType.TEXT,
            payload={"body": "You've been unsubscribed from marketing messages. Reply START to re-subscribe."},
            idempotency_key=f"stop-ack-{inbound.wa_message_id}",
        )
        return  # do not process further

    # Manual takeover: bot is silent, human handles it
    if conv.manual_takeover:
        return

    # Rider conversations bypass the customer dialogue entirely.
    if counterpart == "rider":
        await _handle_rider_inbound(session, conv, inbound, restaurant_id, rider)
        return

    # Intent intercept: a status query ("where is my order") is answered from
    # any state without disturbing the in-progress dialogue.
    # Modify intent ("modify", "change order", "edit my order") also intercepted
    # from any state (post-confirmation primarily) to start modify flow per spec.
    if inbound.type == MessageType.TEXT:
        import asyncio
        from app.llm.factory import get_intent_classifier

        text = inbound.payload.get("text", "") or ""
        # Run sync classifier in thread — avoids blocking the async event loop
        # (both Claude and DeepSeek use sync HTTP clients).
        # Fall back to "other" on any network / parse failure.
        try:
            intent = await asyncio.to_thread(get_intent_classifier().classify, text)
        except Exception:
            intent = "other"

        if intent == "status":
            await _handle_status_query(session, conv, inbound, restaurant_id)
            return
        lower = text.lower()
        # Modify intercept only valid AFTER an order is placed — prevents "make it 2
        # biriyani" from triggering modify while the customer is still building their cart.
        _cur_state = conv.state.get("dialogue_state", "greeting")
        if (_cur_state == "order_placed") and (
            intent == "modify" or ("edit" in lower and "order" in lower)
        ):
            await _handle_modify_intent(session, conv, inbound, restaurant_id)
            return

    # Greeting reset: "hi/hello/hey/start/menu" from any state re-shows the menu.
    _GREET = {"hi", "hello", "hey", "start", "menu", "مرحبا", "السلام عليكم", "hii", "helo"}
    if inbound.type == MessageType.TEXT:
        _txt_lower = (inbound.payload.get("text") or "").strip().lower()
        if _txt_lower in _GREET:
            _set_state(conv, dialogue_state="greeting", draft_order_id=None)
            await _handle_greeting(session, conv, inbound, restaurant_id)
            return

    dialogue_state = conv.state.get("dialogue_state", "greeting")

    if dialogue_state == "greeting":
        await _handle_greeting(session, conv, inbound, restaurant_id)
    elif dialogue_state in ("menu_sent", "collecting_items"):
        await _handle_collecting_items(session, conv, inbound, restaurant_id)
    elif dialogue_state in ("address_capture", "address_text_pending"):
        await _handle_address_capture(session, conv, inbound, restaurant_id)
    elif dialogue_state == "receiver_details":
        await _handle_receiver_details(session, conv, inbound, restaurant_id)
    elif dialogue_state == "order_confirmation":
        await _handle_order_confirmation(session, conv, inbound, restaurant_id)
    elif dialogue_state == "modify_items":
        await _handle_modify_items(session, conv, inbound, restaurant_id)
    elif dialogue_state == "modify_confirm":
        await _handle_modify_confirm(session, conv, inbound, restaurant_id)
    # Terminal states (order_placed, cancelled) are pass-through for now.
    # (modify intent is intercepted early; new states only entered from order_placed via modify flow)
