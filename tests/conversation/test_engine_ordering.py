from decimal import Decimal

from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.conversation.models import Conversation
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType


def _msg(text: str, wa_id: str = "wamid.o1") -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id,
        from_phone="+971501110001",
        type=MessageType.TEXT,
        payload={"text": text},
        restaurant_phone="+97141234567",
        timestamp=1717660800,
    )


def _loc_msg(lat: float, lon: float, wa_id: str = "wamid.loc1") -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id,
        from_phone="+971501110001",
        type=MessageType.LOCATION,
        payload={"latitude": lat, "longitude": lon},
        restaurant_phone="+97141234567",
        timestamp=1717660801,
    )


def _btn(btn_id: str, wa_id: str = "wamid.btn1") -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id,
        from_phone="+971501110001",
        type=MessageType.BUTTON_REPLY,
        payload={"id": btn_id, "title": "Yes"},
        restaurant_phone="+97141234567",
        timestamp=1717660802,
    )


async def _seed_menu(db_session, restaurant_id):
    """Seed an active menu with 2 dishes for the given restaurant."""
    from app.menu.models import Dish, Menu

    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=110,
        name="Chicken Biryani", price_aed=Decimal("22.00"),
        category="Rice", is_available=True, name_normalized="chicken biryani",
    ))
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=201,
        name="Mutton Karahi", price_aed=Decimal("35.00"),
        category="Curries", is_available=True, name_normalized="mutton karahi",
    ))
    await db_session.commit()


async def _conv(db_session) -> Conversation:
    return (await db_session.execute(
        select(Conversation).where(Conversation.phone == "+971501110001")
    )).scalar_one()


async def test_item_collection_direct_match_adds_item(db_session, restaurant):
    """After menu_sent, typing a dish name direct-matches and adds the item."""
    await _seed_menu(db_session, restaurant.id)

    await handle_inbound(db_session, _msg("hi", "wamid.greet"), restaurant_id=restaurant.id)
    await db_session.commit()

    await handle_inbound(db_session, _msg("chicken biryani", "wamid.item1"), restaurant_id=restaurant.id)
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    last_body = rows[-1].payload["body"]
    assert "110" in last_body or "Chicken Biryani" in last_body

    from app.ordering.models import OrderItem
    items = (await db_session.execute(select(OrderItem))).scalars().all()
    assert len(items) == 1
    assert items[0].dish_number == 110
    assert items[0].qty == 1


async def test_item_collection_qty_parsing(db_session, restaurant):
    """Quantity prefix 2x is parsed to qty=2 when adding an item."""
    await _seed_menu(db_session, restaurant.id)
    await handle_inbound(db_session, _msg("hi", "wamid.greet2"), restaurant_id=restaurant.id)
    await db_session.commit()

    conv = await _conv(db_session)
    conv.state = {**conv.state, "dialogue_state": "collecting_items", "draft_order_id": None}
    await db_session.commit()

    await handle_inbound(db_session, _msg("2x chicken biryani", "wamid.qty1"), restaurant_id=restaurant.id)
    await db_session.commit()

    from app.ordering.models import OrderItem
    items = (await db_session.execute(select(OrderItem))).scalars().all()
    assert len(items) == 1
    assert items[0].qty == 2


async def test_item_collection_no_match_polite_retry(db_session, restaurant):
    """An unmatched dish query yields a polite retry asking for the dish number."""
    await _seed_menu(db_session, restaurant.id)
    await handle_inbound(db_session, _msg("hi", "wamid.greet_nm"), restaurant_id=restaurant.id)
    await db_session.commit()

    conv = await _conv(db_session)
    conv.state = {**conv.state, "dialogue_state": "collecting_items"}
    await db_session.commit()

    await handle_inbound(db_session, _msg("zzzqwerty", "wamid.nm1"), restaurant_id=restaurant.id)
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    last = rows[-1].payload["body"].lower()
    assert "number" in last or "didn't find" in last or "did not find" in last

    from app.ordering.models import OrderItem
    items = (await db_session.execute(select(OrderItem))).scalars().all()
    assert items == []


async def test_done_advances_to_address_capture(db_session, restaurant):
    """Sending 'done' with items in the draft advances to address capture."""
    await _seed_menu(db_session, restaurant.id)
    await handle_inbound(db_session, _msg("hi", "wamid.greet_d"), restaurant_id=restaurant.id)
    await db_session.commit()

    await handle_inbound(db_session, _msg("chicken biryani", "wamid.item_d"), restaurant_id=restaurant.id)
    await db_session.commit()
    await handle_inbound(db_session, _msg("done", "wamid.done1"), restaurant_id=restaurant.id)
    await db_session.commit()

    conv = await _conv(db_session)
    assert conv.state["dialogue_state"] == "address_capture"


async def test_location_pin_within_radius_advances_to_address_text(db_session, restaurant):
    """A pin within 10 km is accepted; bot asks for room/building text address."""
    await _seed_menu(db_session, restaurant.id)

    await handle_inbound(db_session, _msg("hi", "wamid.greet3"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    conv.state = {**conv.state, "dialogue_state": "address_capture"}
    await db_session.commit()

    await handle_inbound(db_session, _loc_msg(25.2100, 55.2750, "wamid.pin1"), restaurant_id=restaurant.id)
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    last = rows[-1].payload["body"].lower()
    assert "room" in last or "apartment" in last or "building" in last


async def test_location_pin_beyond_radius_sends_undeliverable(db_session, restaurant):
    """A pin > 10 km from the restaurant sends an undeliverable message."""
    await _seed_menu(db_session, restaurant.id)

    await handle_inbound(db_session, _msg("hi", "wamid.greet4"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    conv.state = {**conv.state, "dialogue_state": "address_capture"}
    await db_session.commit()

    # Abu Dhabi pin — far from Dubai restaurant (25.2048, 55.2708)
    await handle_inbound(db_session, _loc_msg(24.4539, 54.3773, "wamid.far1"), restaurant_id=restaurant.id)
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    last = rows[-1].payload["body"].lower()
    assert "deliverable" in last or "sorry" in last


async def test_order_confirmation_message_includes_totals_and_eta(db_session, restaurant):
    """order_confirmation confirm button finalizes the order with totals + ETA."""
    await _seed_menu(db_session, restaurant.id)

    from app.ordering.models import Customer, CustomerAddress, Order

    customer = Customer(
        restaurant_id=restaurant.id, phone="+971501110001", name="Ali",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    addr = CustomerAddress(
        customer_id=customer.id, latitude=25.21, longitude=55.27,
        room_apartment="101", building="Tower A",
        receiver_name="Ali", confirmed=True,
    )
    db_session.add(addr)
    await db_session.flush()

    order = Order(
        restaurant_id=restaurant.id, customer_id=customer.id,
        order_number="R1-0001", status="pending_confirmation",
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("22.00"), total=Decimal("22.00"),
        address_id=addr.id, distance_km=1.5,
    )
    db_session.add(order)
    await db_session.flush()
    await db_session.commit()

    await handle_inbound(db_session, _msg("hi", "wamid.greet5"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    conv.state = {
        **conv.state,
        "dialogue_state": "order_confirmation",
        "pending_order_id": order.id,
    }
    await db_session.commit()

    await handle_inbound(db_session, _btn("confirm_order", "wamid.conf1"), restaurant_id=restaurant.id)
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    last = rows[-1].payload["body"]
    assert "40" in last or "AED" in last or "COD" in last.upper()

    await db_session.refresh(order)
    assert order.status == "confirmed"
    assert order.sla_confirmed_at is not None


async def test_returning_customer_offered_stored_address(db_session, restaurant):
    """A customer with a confirmed address is offered it rather than asked for text."""
    await _seed_menu(db_session, restaurant.id)

    from app.ordering.models import Customer, CustomerAddress

    customer = Customer(
        restaurant_id=restaurant.id, phone="+971501110001", name="Returning",
        usual_order_times={}, tags={}, total_orders=1, total_spend=Decimal("22.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    addr = CustomerAddress(
        customer_id=customer.id, latitude=25.21, longitude=55.27,
        room_apartment="5B", building="Marina Tower",
        receiver_name="Returning", confirmed=True,
    )
    db_session.add(addr)
    await db_session.commit()

    await handle_inbound(db_session, _msg("hi", "wamid.ret1"), restaurant_id=restaurant.id)
    await db_session.commit()

    conv = await _conv(db_session)
    conv.state = {**conv.state, "dialogue_state": "address_capture"}
    await db_session.commit()

    await handle_inbound(
        db_session, _loc_msg(25.21, 55.27, "wamid.ret2"), restaurant_id=restaurant.id
    )
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    last = rows[-1].payload
    assert (
        last.get("type") == "buttons"
        or "5B" in last.get("body", "")
        or "Marina" in last.get("body", "")
    )


async def test_returning_customer_confirms_saved_address_skips_to_summary(db_session, restaurant):
    """Selecting the saved-address button reuses it and advances to order confirmation."""
    await _seed_menu(db_session, restaurant.id)

    from app.menu.models import Dish
    from app.ordering.models import Customer, CustomerAddress, Order, OrderItem

    dish = await db_session.scalar(select(Dish).where(Dish.dish_number == 110))

    customer = Customer(
        restaurant_id=restaurant.id, phone="+971501110001", name="Returning",
        usual_order_times={}, tags={}, total_orders=1, total_spend=Decimal("22.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    addr = CustomerAddress(
        customer_id=customer.id, latitude=25.21, longitude=55.27,
        room_apartment="5B", building="Marina Tower",
        receiver_name="Returning", confirmed=True,
    )
    db_session.add(addr)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=customer.id,
        order_number="R1-RET1", status="draft",
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("22.00"), total=Decimal("22.00"),
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(OrderItem(
        order_id=order.id, dish_id=dish.id, dish_number=110,
        dish_name="Chicken Biryani", price_aed=Decimal("22.00"), qty=1,
    ))
    await db_session.commit()

    await handle_inbound(db_session, _msg("hi", "wamid.retb1"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    conv.state = {
        **conv.state,
        "dialogue_state": "address_capture",
        "draft_order_id": order.id,
    }
    await db_session.commit()

    await handle_inbound(
        db_session, _btn("use_saved_address", "wamid.retb2"), restaurant_id=restaurant.id
    )
    await db_session.commit()

    conv = await _conv(db_session)
    assert conv.state["dialogue_state"] == "order_confirmation"
    await db_session.refresh(order)
    assert order.address_id == addr.id


async def test_what_is_query_returns_description_without_price(db_session, restaurant):
    """'What is chicken biryani' → describer reply, no price."""
    await _seed_menu(db_session, restaurant.id)

    await handle_inbound(db_session, _msg("hi", "wamid.desc1"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    conv.state = {**conv.state, "dialogue_state": "collecting_items"}
    await db_session.commit()

    await handle_inbound(
        db_session, _msg("what is chicken biryani", "wamid.desc2"), restaurant_id=restaurant.id
    )
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    last = rows[-1].payload["body"]
    assert "22" not in last  # no price
    assert "AED" not in last


async def test_ambiguous_match_sends_disambiguation_question(db_session, restaurant):
    """Two similar dishes → disambiguation message with both options."""
    from app.menu.models import Dish, Menu

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=110,
        name="Chicken Biryani", price_aed=Decimal("22.00"),
        category="Rice", is_available=True, name_normalized="chicken biryani",
    ))
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=111,
        name="Special Chicken Biryani", price_aed=Decimal("28.00"),
        category="Rice", is_available=True, name_normalized="special chicken biryani",
    ))
    await db_session.commit()

    import unittest.mock as mock

    from app.menu.models import Dish as DishModel
    from app.ordering.matching import MatchConfidence, MatchResult
    from sqlalchemy import select as sa_select

    await handle_inbound(db_session, _msg("hi", "wamid.ambig1"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    conv.state = {**conv.state, "dialogue_state": "collecting_items"}
    await db_session.commit()

    ambig_dish_1 = await db_session.scalar(
        sa_select(DishModel).where(DishModel.dish_number == 110)
    )
    ambig_dish_2 = await db_session.scalar(
        sa_select(DishModel).where(DishModel.dish_number == 111)
    )

    async def _fake_matches(*args, **kwargs):
        return MatchResult(
            confidence=MatchConfidence.AMBIGUOUS,
            candidates=[ambig_dish_1, ambig_dish_2],
        )

    with mock.patch(
        "app.conversation.engine.find_dish_matches", side_effect=_fake_matches
    ):
        await handle_inbound(
            db_session, _msg("biryani", "wamid.ambig2"), restaurant_id=restaurant.id
        )
        await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    last = rows[-1].payload["body"]
    assert "110" in last or "111" in last  # disambiguation lists dish numbers
    assert "mean" in last.lower()
