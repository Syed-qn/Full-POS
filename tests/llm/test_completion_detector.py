"""Tests for FakeCompletionDetector and the modify-flow integration.

Unit tests — no DB required.
Integration tests drive the full engine modify flow and assert that
non-English/curly-apostrophe completions finalize the modification
(dialogue_state → modify_confirm) rather than being treated as dish names.
"""
import pytest

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Unit tests — FakeCompletionDetector
# ---------------------------------------------------------------------------


async def test_fake_completion_detector_done():
    from app.llm.fake import FakeCompletionDetector

    detector = FakeCompletionDetector()
    assert await detector.is_completion("done") is True


async def test_fake_completion_detector_khalas():
    from app.llm.fake import FakeCompletionDetector

    detector = FakeCompletionDetector()
    assert await detector.is_completion("khalas") is True


async def test_fake_completion_detector_curly_apostrophe():
    """'that’s all' (curly apostrophe U+2019) must return True."""
    from app.llm.fake import FakeCompletionDetector

    detector = FakeCompletionDetector()
    assert await detector.is_completion("No that’s all") is True


async def test_fake_completion_detector_dish_name_false():
    from app.llm.fake import FakeCompletionDetector

    detector = FakeCompletionDetector()
    assert await detector.is_completion("chicken biryani") is False


async def test_fake_completion_detector_question_false():
    from app.llm.fake import FakeCompletionDetector

    detector = FakeCompletionDetector()
    assert await detector.is_completion("what is biryani?") is False


async def test_fake_completion_detector_empty_false():
    from app.llm.fake import FakeCompletionDetector

    detector = FakeCompletionDetector()
    assert await detector.is_completion("") is False


async def test_fake_completion_detector_blank_false():
    from app.llm.fake import FakeCompletionDetector

    detector = FakeCompletionDetector()
    assert await detector.is_completion("   ") is False


async def test_fake_completion_detector_thats_all_straight():
    from app.llm.fake import FakeCompletionDetector

    detector = FakeCompletionDetector()
    assert await detector.is_completion("that's all") is True


async def test_fake_completion_detector_bas():
    from app.llm.fake import FakeCompletionDetector

    detector = FakeCompletionDetector()
    assert await detector.is_completion("bas") is True


async def test_fake_completion_detector_checkout():
    from app.llm.fake import FakeCompletionDetector

    detector = FakeCompletionDetector()
    assert await detector.is_completion("checkout") is True


async def test_fake_completion_detector_proceed():
    from app.llm.fake import FakeCompletionDetector

    detector = FakeCompletionDetector()
    assert await detector.is_completion("proceed") is True


async def test_fake_completion_detector_no_action():
    """Bare 'no' / 'na' / 'nah' / 'nope' are valid completion signals."""
    from app.llm.fake import FakeCompletionDetector

    detector = FakeCompletionDetector()
    for token in ("no", "na", "nah", "nope", "np"):
        assert await detector.is_completion(token) is True, f"expected True for {token!r}"


# ---------------------------------------------------------------------------
# Factory — get_completion_detector dispatches to FakeCompletionDetector
# ---------------------------------------------------------------------------


async def test_factory_get_completion_detector_fake(monkeypatch):
    """get_completion_detector() returns FakeCompletionDetector when provider=fake."""
    monkeypatch.setenv("APP_LLM_PROVIDER", "fake")
    from app.config import get_settings
    get_settings.cache_clear()
    from app.llm.factory import get_completion_detector
    detector = get_completion_detector()
    assert await detector.is_completion("done") is True
    assert await detector.is_completion("chicken biryani") is False
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Integration tests — modify flow finalizes with non-English completion
# ---------------------------------------------------------------------------


@pytest.fixture
async def restaurant_for_completion(db_session):
    """Seed a minimal restaurant row for the completion detector integration tests."""
    from app.identity.models import Restaurant

    row = Restaurant(
        name="Test Restaurant",
        phone="+97141234567",
        password_hash="x",
        lat=25.2048,
        lng=55.2708,
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def _seed_menu_for_completion(db_session, restaurant_id):
    from decimal import Decimal
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


def _txt(text: str, wa_id: str) -> "InboundMessage":  # noqa: F821  (resolved at runtime)
    from app.whatsapp.port import InboundMessage, MessageType
    return InboundMessage(
        wa_message_id=wa_id,
        from_phone="+971501110002",
        type=MessageType.TEXT,
        payload={"text": text},
        restaurant_phone="+97141234567",
        timestamp=1717660800,
    )


async def _get_conv(db_session):
    from sqlalchemy import select
    from app.conversation.models import Conversation
    return (await db_session.execute(
        select(Conversation).where(Conversation.phone == "+971501110002")
    )).scalar_one()


async def _drive_modify_to_proposed(db_session, restaurant):
    """Helper: create order, put conv in modify_items with 1 proposed item."""
    import datetime
    from decimal import Decimal
    from sqlalchemy import select as sa_select
    from app.conversation.engine import handle_inbound
    from app.menu.models import Dish
    from app.ordering.models import Customer, CustomerAddress, Order, OrderItem
    from app.ordering.fsm import OrderStatus

    customer = Customer(
        restaurant_id=restaurant.id, phone="+971501110002", name="Tester",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    addr = CustomerAddress(
        customer_id=customer.id, latitude=25.21, longitude=55.27,
        room_apartment="10", building="Test Tower",
        receiver_name="Tester", confirmed=True,
    )
    db_session.add(addr)
    await db_session.flush()

    now = datetime.datetime.now(datetime.timezone.utc)
    order = Order(
        restaurant_id=restaurant.id, customer_id=customer.id,
        order_number="R1-COMP1", status=OrderStatus.CONFIRMED,
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("22.00"), total=Decimal("22.00"),
        address_id=addr.id, distance_km=1.0,
        sla_confirmed_at=now,
        sla_deadline=now + datetime.timedelta(minutes=40),
    )
    db_session.add(order)
    await db_session.flush()

    dish = await db_session.scalar(
        sa_select(Dish).where(Dish.dish_number == 110)
    )
    db_session.add(OrderItem(
        order_id=order.id, dish_id=dish.id, dish_number=110,
        dish_name="Chicken Biryani", price_aed=Decimal("22.00"), qty=1,
    ))
    await db_session.commit()

    # Bootstrap the conversation via a greeting, then override state to modify_items
    await handle_inbound(db_session, _txt("hi", "wamid.compgreet"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _get_conv(db_session)
    conv.state = {
        **conv.state,
        "dialogue_phase": "post_order",
        "dialogue_state": "modify_items",
        "modify_order_id": order.id,
        "pending_order_id": order.id,
        "modify_proposed": [],
    }
    await db_session.commit()

    # Add a proposed item so the completion gate has something to confirm
    await handle_inbound(db_session, _txt("2x chicken biryani", "wamid.compitem"), restaurant_id=restaurant.id)
    await db_session.commit()

    conv = await _get_conv(db_session)
    return conv, order


async def test_modify_flow_finalizes_with_khalas(db_session, restaurant_for_completion):
    """Sending 'khalas' (Arabic closing) in modify_items advances to modify_confirm."""
    from app.conversation.engine import handle_inbound

    await _seed_menu_for_completion(db_session, restaurant_for_completion.id)
    conv, _order = await _drive_modify_to_proposed(db_session, restaurant_for_completion)

    proposed = conv.state.get("modify_proposed", [])
    assert len(proposed) >= 1, "precondition: at least one proposed item before completion"

    await handle_inbound(db_session, _txt("khalas", "wamid.khalas"), restaurant_id=restaurant_for_completion.id)
    await db_session.commit()

    conv = await _get_conv(db_session)
    assert conv.state.get("dialogue_state") == "modify_confirm", (
        f"Expected modify_confirm after 'khalas', got {conv.state.get('dialogue_state')!r}"
    )


async def test_modify_flow_finalizes_with_curly_apostrophe(db_session, restaurant_for_completion):
    """Sending 'that’s all' (curly apostrophe U+2019) advances to modify_confirm."""
    from app.conversation.engine import handle_inbound

    await _seed_menu_for_completion(db_session, restaurant_for_completion.id)

    # Need a fresh customer phone to avoid collision — patch the helper
    import datetime
    from decimal import Decimal
    from sqlalchemy import select as sa_select
    from app.menu.models import Dish
    from app.ordering.models import Customer, CustomerAddress, Order, OrderItem
    from app.ordering.fsm import OrderStatus
    from app.whatsapp.port import InboundMessage, MessageType

    PHONE2 = "+971501110003"

    def _txt2(text: str, wa_id: str) -> InboundMessage:
        return InboundMessage(
            wa_message_id=wa_id,
            from_phone=PHONE2,
            type=MessageType.TEXT,
            payload={"text": text},
            restaurant_phone="+97141234567",
            timestamp=1717660800,
        )

    customer = Customer(
        restaurant_id=restaurant_for_completion.id, phone=PHONE2, name="Tester2",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    addr = CustomerAddress(
        customer_id=customer.id, latitude=25.21, longitude=55.27,
        room_apartment="11", building="Test Tower",
        receiver_name="Tester2", confirmed=True,
    )
    db_session.add(addr)
    await db_session.flush()

    now = datetime.datetime.now(datetime.timezone.utc)
    order = Order(
        restaurant_id=restaurant_for_completion.id, customer_id=customer.id,
        order_number="R1-COMP2", status=OrderStatus.CONFIRMED,
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("22.00"), total=Decimal("22.00"),
        address_id=addr.id, distance_km=1.0,
        sla_confirmed_at=now,
        sla_deadline=now + datetime.timedelta(minutes=40),
    )
    db_session.add(order)
    await db_session.flush()

    dish = await db_session.scalar(sa_select(Dish).where(Dish.dish_number == 110))
    db_session.add(OrderItem(
        order_id=order.id, dish_id=dish.id, dish_number=110,
        dish_name="Chicken Biryani", price_aed=Decimal("22.00"), qty=1,
    ))
    await db_session.commit()

    await handle_inbound(db_session, _txt2("hi", "wamid.curlgreet"), restaurant_id=restaurant_for_completion.id)
    await db_session.commit()

    from sqlalchemy import select
    from app.conversation.models import Conversation
    conv2 = (await db_session.execute(
        select(Conversation).where(Conversation.phone == PHONE2)
    )).scalar_one()
    conv2.state = {
        **conv2.state,
        "dialogue_phase": "post_order",
        "dialogue_state": "modify_items",
        "modify_order_id": order.id,
        "pending_order_id": order.id,
        "modify_proposed": [],
    }
    await db_session.commit()

    # Add a proposed item
    await handle_inbound(db_session, _txt2("2x chicken biryani", "wamid.curlitem"), restaurant_id=restaurant_for_completion.id)
    await db_session.commit()

    # Send curly-apostrophe completion signal
    await handle_inbound(db_session, _txt2("that’s all", "wamid.curlapo"), restaurant_id=restaurant_for_completion.id)
    await db_session.commit()

    conv2 = (await db_session.execute(
        select(Conversation).where(Conversation.phone == PHONE2)
    )).scalar_one()
    assert conv2.state.get("dialogue_state") == "modify_confirm", (
        f"Expected modify_confirm after 'that’s all', got {conv2.state.get('dialogue_state')!r}"
    )


async def test_modify_flow_english_done_still_finalizes(db_session, restaurant_for_completion):
    """Regression: English 'done' still advances to modify_confirm after LLM wiring."""
    from app.conversation.engine import handle_inbound
    from app.whatsapp.port import InboundMessage, MessageType

    await _seed_menu_for_completion(db_session, restaurant_for_completion.id)

    PHONE3 = "+971501110004"

    def _txt3(text: str, wa_id: str) -> InboundMessage:
        return InboundMessage(
            wa_message_id=wa_id,
            from_phone=PHONE3,
            type=MessageType.TEXT,
            payload={"text": text},
            restaurant_phone="+97141234567",
            timestamp=1717660800,
        )

    import datetime
    from decimal import Decimal
    from sqlalchemy import select as sa_select, select
    from app.menu.models import Dish
    from app.ordering.models import Customer, CustomerAddress, Order, OrderItem
    from app.ordering.fsm import OrderStatus
    from app.conversation.models import Conversation

    customer = Customer(
        restaurant_id=restaurant_for_completion.id, phone=PHONE3, name="Tester3",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    addr = CustomerAddress(
        customer_id=customer.id, latitude=25.21, longitude=55.27,
        room_apartment="12", building="Test Tower",
        receiver_name="Tester3", confirmed=True,
    )
    db_session.add(addr)
    await db_session.flush()

    now = datetime.datetime.now(datetime.timezone.utc)
    order = Order(
        restaurant_id=restaurant_for_completion.id, customer_id=customer.id,
        order_number="R1-COMP3", status=OrderStatus.CONFIRMED,
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("22.00"), total=Decimal("22.00"),
        address_id=addr.id, distance_km=1.0,
        sla_confirmed_at=now,
        sla_deadline=now + datetime.timedelta(minutes=40),
    )
    db_session.add(order)
    await db_session.flush()

    dish = await db_session.scalar(sa_select(Dish).where(Dish.dish_number == 110))
    db_session.add(OrderItem(
        order_id=order.id, dish_id=dish.id, dish_number=110,
        dish_name="Chicken Biryani", price_aed=Decimal("22.00"), qty=1,
    ))
    await db_session.commit()

    await handle_inbound(db_session, _txt3("hi", "wamid.donegreet"), restaurant_id=restaurant_for_completion.id)
    await db_session.commit()

    conv3 = (await db_session.execute(
        select(Conversation).where(Conversation.phone == PHONE3)
    )).scalar_one()
    conv3.state = {
        **conv3.state,
        "dialogue_phase": "post_order",
        "dialogue_state": "modify_items",
        "modify_order_id": order.id,
        "pending_order_id": order.id,
        "modify_proposed": [],
    }
    await db_session.commit()

    await handle_inbound(db_session, _txt3("2x chicken biryani", "wamid.doneitem"), restaurant_id=restaurant_for_completion.id)
    await db_session.commit()

    await handle_inbound(db_session, _txt3("done", "wamid.donedone"), restaurant_id=restaurant_for_completion.id)
    await db_session.commit()

    conv3 = (await db_session.execute(
        select(Conversation).where(Conversation.phone == PHONE3)
    )).scalar_one()
    assert conv3.state.get("dialogue_state") == "modify_confirm", (
        f"Expected modify_confirm after 'done', got {conv3.state.get('dialogue_state')!r}"
    )
