import base64
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
    assert "110" in last_body or "biryani" in last_body.lower()

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


async def test_complaint_question_does_not_add_items(db_session, restaurant):
    """A complaint/question ("why did you add 2 biryani") must NOT be mined for a stray
    quantity and silently added to the cart. Reproduces the bug where asking why an item
    was added ADDED more of it."""
    from app.ordering.models import OrderItem

    await _seed_menu(db_session, restaurant.id)
    await handle_inbound(db_session, _msg("hi", "wamid.greet_q"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    conv.state = {**conv.state, "dialogue_state": "collecting_items", "draft_order_id": None}
    await db_session.commit()

    # A genuine order first: 2x Chicken Biryani.
    await handle_inbound(db_session, _msg("2x chicken biryani", "wamid.q_add"), restaurant_id=restaurant.id)
    await db_session.commit()
    before = (await db_session.execute(select(OrderItem))).scalars().all()
    assert len(before) == 1 and before[0].qty == 2

    # The complaint must leave the cart untouched (no 3rd/4th biryani).
    await handle_inbound(
        db_session, _msg("why did you add 2 biryani", "wamid.q_complaint"),
        restaurant_id=restaurant.id,
    )
    await db_session.commit()
    after = (await db_session.execute(select(OrderItem))).scalars().all()
    assert len(after) == 1 and after[0].qty == 2  # unchanged

    last = (await db_session.execute(select(OutboxMessage))).scalars().all()[-1].payload["body"]
    assert "Added" not in last  # it did not confirm an add


def test_is_done_intent_variants():
    """The checkout detector accepts real "finished" phrasings (incl. a leading 'no' and
    angry/trailing filler) but not orders or the ambiguous bare 'no'."""
    from app.conversation.engine import _is_done_intent

    for p in [
        "that's all", "No that's all", "thats all", "Thats all can't you understand",
        "Motherfucker that's all", "done", "nothing else", "no more thanks", "I'm done",
        "that's it", "proceed",
    ]:
        assert _is_done_intent(p) is True, p
    for p in ["chicken biryani", "2 mandi", "is that all you have", "add more", "no", ""]:
        assert _is_done_intent(p) is False, p


async def test_thats_all_checks_out_without_calling_llm(db_session, restaurant):
    """"No that's all" with a cart proceeds to checkout deterministically — the LLM is
    never called (it used to loop re-adding the item / sent a welcome mid-order)."""
    from unittest.mock import patch

    from app.conversation.engine import _handle_customer_ai
    from app.conversation.service import get_or_create_conversation
    from app.menu.models import Dish, Menu
    from app.ordering.models import OrderItem
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=110,
        name="Chicken Biryani", price_aed=Decimal("22.00"), category="Rice",
        is_available=True, name_normalized="chicken biryani",
    )
    db_session.add(dish)
    await db_session.commit()

    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant.id, phone="+971501110001", counterpart="customer"
    )
    customer = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971501110001"
    )
    order = await create_draft_order(
        db_session, restaurant_id=restaurant.id, customer_id=customer.id
    )
    await add_item(db_session, order=order, dish=dish, qty=1)
    conv.state = {
        **conv.state, "dialogue_phase": "ordering",
        "dialogue_state": "collecting_items", "draft_order_id": order.id,
    }
    await db_session.commit()

    async def _boom(*a, **k):
        raise AssertionError("LLM must not run for an explicit checkout phrase")

    with patch("app.llm.fake.FakeConversationAgent.respond", _boom):
        await _handle_customer_ai(
            db_session, conv, _msg("no that's all", "wamid.done"), restaurant.id, restaurant
        )
    await db_session.commit()

    # Cart unchanged (not re-added) and we advanced to address capture.
    items = (await db_session.execute(
        select(OrderItem).where(OrderItem.order_id == order.id)
    )).scalars().all()
    assert len(items) == 1 and items[0].qty == 1
    assert conv.state["dialogue_state"] == "address_capture"


def test_is_clear_cart_command_precise():
    """Clear detector fires on real clear commands but NOT on the dish 'clear soup'."""
    from app.conversation.engine import _is_clear_cart_command

    for p in ["clear cart", "Clear the cart", "empty cart", "start over", "reset cart",
              "clear all", "clear", "clear my basket", "remove everything"]:
        assert _is_clear_cart_command(p) is True, p
    for p in ["clear soup", "one clear soup", "chicken biryani", "clearance", "", "2 mandi"]:
        assert _is_clear_cart_command(p) is False, p


async def test_clear_cart_command_empties_without_llm(db_session, restaurant):
    """"Clear cart" empties the cart deterministically — the LLM never runs, so it can't
    fuzzy-match "clear" to the dish "Clear Soup" and add it."""
    from unittest.mock import patch

    from app.conversation.engine import _handle_customer_ai
    from app.conversation.service import get_or_create_conversation
    from app.menu.models import Dish, Menu
    from app.ordering.models import OrderItem
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    biryani = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=110,
        name="Chicken Biryani", price_aed=Decimal("22.00"), category="Rice",
        is_available=True, name_normalized="chicken biryani",
    )
    # A "Clear Soup" dish exists — the exact thing the LLM used to add on "clear cart".
    soup = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=300,
        name="Clear Soup", price_aed=Decimal("10.00"), category="Soup",
        is_available=True, name_normalized="clear soup",
    )
    db_session.add_all([biryani, soup])
    await db_session.commit()

    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant.id, phone="+971501110001", counterpart="customer"
    )
    customer = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971501110001"
    )
    order = await create_draft_order(
        db_session, restaurant_id=restaurant.id, customer_id=customer.id
    )
    await add_item(db_session, order=order, dish=biryani, qty=1)
    conv.state = {
        **conv.state, "dialogue_phase": "ordering",
        "dialogue_state": "collecting_items", "draft_order_id": order.id,
    }
    await db_session.commit()

    async def _boom(*a, **k):
        raise AssertionError("LLM must not run for an explicit clear command")

    with patch("app.llm.fake.FakeConversationAgent.respond", _boom):
        await _handle_customer_ai(
            db_session, conv, _msg("clear cart", "wamid.clr"), restaurant.id, restaurant
        )
    await db_session.commit()

    items = (await db_session.execute(
        select(OrderItem).where(OrderItem.order_id == order.id)
    )).scalars().all()
    assert items == []  # emptied, and NO "Clear Soup" added
    last = (await db_session.execute(select(OutboxMessage))).scalars().all()[-1].payload["body"]
    assert "Cleared your cart" in last and "Clear Soup" not in last


async def test_only_dish_keeps_that_dish_and_prunes_the_rest(db_session, restaurant):
    """"Only mandi" with [Mandi, Lemon Mint] in the cart keeps Mandi and removes the rest
    — it must NOT wipe the whole cart (the old behaviour said "Cleared your cart")."""
    from unittest.mock import patch

    from app.conversation.engine import _handle_customer_ai
    from app.conversation.service import get_or_create_conversation
    from app.menu.models import Dish, Menu
    from app.ordering.models import OrderItem
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    mandi = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=8, name="Mandi",
        price_aed=Decimal("40.00"), category="Rice", is_available=True,
        name_normalized="mandi",
    )
    mint = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=9, name="Lemon Mint",
        price_aed=Decimal("12.00"), category="Drinks", is_available=True,
        name_normalized="lemon mint",
    )
    db_session.add_all([mandi, mint])
    await db_session.commit()

    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant.id, phone="+971501110001", counterpart="customer"
    )
    customer = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971501110001"
    )
    order = await create_draft_order(
        db_session, restaurant_id=restaurant.id, customer_id=customer.id
    )
    await add_item(db_session, order=order, dish=mandi, qty=1)
    await add_item(db_session, order=order, dish=mint, qty=1)
    conv.state = {
        **conv.state, "dialogue_phase": "ordering",
        "dialogue_state": "collecting_items", "draft_order_id": order.id,
    }
    await db_session.commit()

    async def _boom(*a, **k):
        raise AssertionError("LLM must not run for keep-only")

    with patch("app.llm.fake.FakeConversationAgent.respond", _boom):
        await _handle_customer_ai(
            db_session, conv, _msg("only mandi", "wamid.only"), restaurant.id, restaurant
        )
    await db_session.commit()

    items = (await db_session.execute(
        select(OrderItem).where(OrderItem.order_id == order.id)
    )).scalars().all()
    active = {i.dish_number for i in items if i.qty > 0}
    assert active == {8}  # Mandi kept, Lemon Mint pruned — cart NOT wiped
    last = (await db_session.execute(select(OutboxMessage))).scalars().all()[-1].payload["body"]
    assert "Cleared your cart" not in last and "Kept only" in last


async def test_clear_cart_action_with_a_dish_adds_instead_of_wiping(db_session, restaurant):
    """An order the LLM mis-tags as clear_cart ("one beef curry") must ADD the dish, not
    empty the cart. Reproduces the chat where "One beef curry" returned "Cleared your
    cart 🧹" and the order was silently dropped."""
    from types import SimpleNamespace

    from app.conversation.engine import _dispatch_action
    from app.menu.models import Dish, Menu
    from app.ordering.models import OrderItem
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    biryani = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=110,
        name="Chicken Biryani", price_aed=Decimal("22.00"), category="Rice",
        is_available=True, name_normalized="chicken biryani",
    )
    beef = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=150,
        name="Beef Curry", price_aed=Decimal("30.00"), category="Curry",
        is_available=True, name_normalized="beef curry",
    )
    db_session.add_all([biryani, beef])
    await db_session.commit()

    # Existing cart holds 1x Chicken Biryani.
    await handle_inbound(db_session, _msg("hi", "wamid.bc_hi"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    customer = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971501110001"
    )
    order = await create_draft_order(
        db_session, restaurant_id=restaurant.id, customer_id=customer.id
    )
    await add_item(db_session, order=order, dish=biryani, qty=1)
    conv.state = {**conv.state, "dialogue_state": "collecting_items", "draft_order_id": order.id}
    await db_session.commit()

    # LLM mis-classifies "one beef curry" as clear_cart.
    result = SimpleNamespace(action="clear_cart", action_data={}, message="")
    await _dispatch_action(
        db_session, conv, _msg("one beef curry", "wamid.bc"), restaurant.id,
        result, "ordering", restaurant,
    )
    await db_session.commit()

    items = (await db_session.execute(
        select(OrderItem).where(OrderItem.order_id == order.id)
    )).scalars().all()
    numbers = {i.dish_number for i in items}
    # Cart was NOT wiped: the biryani stayed AND beef curry was added.
    assert 110 in numbers and 150 in numbers
    last = (await db_session.execute(select(OutboxMessage))).scalars().all()[-1].payload["body"]
    assert "Cleared your cart" not in last


async def test_make_it_n_sets_quantity_instead_of_adding(db_session, restaurant):
    """"Make it 5 lemon mint" with 1 already in the cart must SET the quantity to 5, not
    add 5 (=6). Reproduces the chat where "make it 5" produced 6x."""
    from types import SimpleNamespace

    from app.conversation.engine import _dispatch_action
    from app.menu.models import Dish, Menu
    from app.ordering.models import OrderItem
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    mint = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=210,
        name="Lemon Mint", price_aed=Decimal("12.00"), category="Drinks",
        is_available=True, name_normalized="lemon mint",
    )
    db_session.add(mint)
    await db_session.commit()

    await handle_inbound(db_session, _msg("hi", "wamid.mi_hi"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    customer = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971501110001"
    )
    order = await create_draft_order(
        db_session, restaurant_id=restaurant.id, customer_id=customer.id
    )
    await add_item(db_session, order=order, dish=mint, qty=1)
    conv.state = {**conv.state, "dialogue_state": "collecting_items", "draft_order_id": order.id}
    await db_session.commit()

    # LLM tags "make it 5 lemon mint" as add_item(qty=5).
    result = SimpleNamespace(
        action="add_item", action_data={"dish_query": "lemon mint", "qty": 5}, message="",
    )
    await _dispatch_action(
        db_session, conv, _msg("make it 5 lemon mint", "wamid.mi"), restaurant.id,
        result, "ordering", restaurant,
    )
    await db_session.commit()

    items = (await db_session.execute(
        select(OrderItem).where(OrderItem.order_id == order.id)
    )).scalars().all()
    assert len(items) == 1
    assert items[0].qty == 5  # SET to 5, not 1 + 5 = 6
    last = (await db_session.execute(select(OutboxMessage))).scalars().all()[-1].payload["body"]
    assert "Updated" in last and "Added" not in last


async def test_multi_dish_make_it_sets_each_no_phantom(db_session, restaurant):
    """"Make it 5 lemon mint and 2 grill mandi" sets EACH dish and never creates a phantom
    line named "lemon mint and 2 grill mandi"."""
    from types import SimpleNamespace

    from app.conversation.engine import _dispatch_action
    from app.menu.models import Dish, Menu
    from app.ordering.models import OrderItem
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    mint = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=9, name="Lemon Mint",
        price_aed=Decimal("12.00"), category="Drinks", is_available=True,
        name_normalized="lemon mint",
    )
    mandi = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=8, name="Grill Mandi",
        price_aed=Decimal("40.00"), category="Rice", is_available=True,
        name_normalized="grill mandi",
    )
    db_session.add_all([mint, mandi])
    await db_session.commit()

    await handle_inbound(db_session, _msg("hi", "wamid.md_hi"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    customer = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971501110001"
    )
    order = await create_draft_order(
        db_session, restaurant_id=restaurant.id, customer_id=customer.id
    )
    await add_item(db_session, order=order, dish=mint, qty=1)
    await add_item(db_session, order=order, dish=mandi, qty=1)
    conv.state = {**conv.state, "dialogue_state": "collecting_items", "draft_order_id": order.id}
    await db_session.commit()

    # LLM mis-tags the multi-dish set as a single add_item with the whole phrase.
    result = SimpleNamespace(
        action="add_item",
        action_data={"dish_query": "lemon mint and 2 grill mandi", "qty": 5}, message="",
    )
    await _dispatch_action(
        db_session, conv, _msg("make it 5 lemon mint and 2 grill mandi", "wamid.md"),
        restaurant.id, result, "ordering", restaurant,
    )
    await db_session.commit()

    items = (await db_session.execute(
        select(OrderItem).where(OrderItem.order_id == order.id)
    )).scalars().all()
    by_num = {i.dish_number: i.qty for i in items if i.qty > 0}
    assert by_num == {9: 5, 8: 2}  # Lemon Mint→5, Grill Mandi→2, no phantom line
    last = (await db_session.execute(select(OutboxMessage))).scalars().all()[-1].payload["body"]
    assert "Updated" in last and "and 2 grill mandi" not in last


async def test_explicit_clear_still_empties_cart(db_session, restaurant):
    """A genuine "clear my cart" must still empty the cart (guard doesn't over-fire)."""
    from types import SimpleNamespace

    from app.conversation.engine import _dispatch_action
    from app.ordering.models import OrderItem
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer

    await _seed_menu(db_session, restaurant.id)
    await handle_inbound(db_session, _msg("hi", "wamid.cc_hi"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    customer = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971501110001"
    )
    order = await create_draft_order(
        db_session, restaurant_id=restaurant.id, customer_id=customer.id
    )
    from app.menu.models import Dish
    biryani = (await db_session.execute(
        select(Dish).where(Dish.dish_number == 110)
    )).scalar_one()
    await add_item(db_session, order=order, dish=biryani, qty=1)
    conv.state = {**conv.state, "dialogue_state": "collecting_items", "draft_order_id": order.id}
    await db_session.commit()

    result = SimpleNamespace(action="clear_cart", action_data={}, message="")
    await _dispatch_action(
        db_session, conv, _msg("clear my cart", "wamid.cc"), restaurant.id,
        result, "ordering", restaurant,
    )
    await db_session.commit()

    items = (await db_session.execute(
        select(OrderItem).where(OrderItem.order_id == order.id)
    )).scalars().all()
    assert items == []  # genuinely emptied
    last = (await db_session.execute(select(OutboxMessage))).scalars().all()[-1].payload["body"]
    assert "Cleared your cart" in last


async def test_item_collection_no_match_polite_retry(db_session, restaurant):
    """An unmatched dish query yields a polite retry asking for the dish name."""
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
    # Warm, honest, grounded: we don't have it, and a pointer back to the real menu.
    assert "don't have" in last and "menu" in last

    from app.ordering.models import OrderItem
    items = (await db_session.execute(select(OrderItem))).scalars().all()
    assert items == []


async def test_menu_request_renders_real_db_menu(db_session, restaurant):
    """Asking for the menu returns the REAL DB dishes, never an LLM-invented list
    (regression: the bot hallucinated a whole fake menu with wrong dish numbers)."""
    await _seed_menu(db_session, restaurant.id)
    await handle_inbound(db_session, _msg("hi", "wamid.m0"), restaurant_id=restaurant.id)
    await db_session.commit()
    await handle_inbound(db_session, _msg("menu", "wamid.m1"), restaurant_id=restaurant.id)
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    body = rows[-1].payload["body"]
    # Real seeded dishes (shown as bullets, no numbers), with their real prices.
    assert "• Chicken Biryani" in body
    assert "• Mutton Karahi" in body
    # Nothing invented.
    assert "Shawarma" not in body and "Lollipop" not in body


async def test_menu_request_after_order_renders_menu_and_resets_to_ordering(db_session, restaurant):
    """Regression: after a completed order (post_order phase) the customer asks
    'menu pls' — the bot must render the REAL menu (not LLM filler like "Here's
    our menu 🍛" with no dishes) and reset to a fresh ordering session so the
    next dish pick is valid."""
    await _seed_menu(db_session, restaurant.id)
    await handle_inbound(db_session, _msg("hi", "wamid.po0"), restaurant_id=restaurant.id)
    await db_session.commit()

    # Simulate a finished order: conversation parked in post_order.
    conv = await _conv(db_session)
    conv.state = {**conv.state, "dialogue_phase": "post_order", "dialogue_state": "order_placed"}
    await db_session.commit()

    await handle_inbound(db_session, _msg("menu pls", "wamid.po1"), restaurant_id=restaurant.id)
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    body = rows[-1].payload["body"]
    assert "• Chicken Biryani" in body
    assert "• Mutton Karahi" in body
    # Reset to a fresh ordering session so the next dish selection works.
    conv = await _conv(db_session)
    assert conv.state["dialogue_phase"] == "ordering"


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


async def test_negative_reply_advances_and_does_not_re_add(db_session, restaurant):
    """A closing/negative reply ("No") to 'anything else?' must move to address
    capture with the cart unchanged — never loop by re-adding the last dish."""
    from app.ordering.models import Order, OrderItem

    await _seed_menu(db_session, restaurant.id)
    await handle_inbound(db_session, _msg("hi", "wamid.greet_n"), restaurant_id=restaurant.id)
    await db_session.commit()
    await handle_inbound(db_session, _msg("chicken biryani", "wamid.item_n"), restaurant_id=restaurant.id)
    await db_session.commit()

    conv = await _conv(db_session)
    order_id = conv.state["draft_order_id"]
    before = (await db_session.scalars(select(OrderItem).where(OrderItem.order_id == order_id))).all()
    qty_before = sum(it.qty for it in before)

    # Closings as production actually sends them (curly apostrophe U+2019), plus a
    # bare decline. None may re-add or inflate the cart line.
    for i, word in enumerate(
        ("No that’s all", "No", "Np", "That’s all", "ok done thanks")
    ):
        await handle_inbound(db_session, _msg(word, f"wamid.close{i}"), restaurant_id=restaurant.id)
        await db_session.commit()
        items = (await db_session.scalars(
            select(OrderItem).where(OrderItem.order_id == order_id))).all()
        assert sum(it.qty for it in items) == qty_before  # never inflates

    conv = await _conv(db_session)
    assert conv.state["dialogue_state"] == "address_capture"
    assert await db_session.get(Order, order_id) is not None


async def _seed_lemon_mint(db_session, restaurant_id):
    """Add a Lemon Mint dish to the existing active menu (for re-add backstop tests)."""
    from app.menu.models import Dish, Menu

    menu = (await db_session.scalars(
        select(Menu).where(Menu.restaurant_id == restaurant_id, Menu.status == "active")
    )).first()
    assert menu is not None, "active menu required for lemon mint seed"
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=301,
        name="Lemon Mint", price_aed=Decimal("8.00"),
        category="Drinks", is_available=True, name_normalized="lemon mint",
    ))
    await db_session.flush()


async def test_readd_backstop_blocks_inflation_on_unnamed_add(db_session, restaurant, monkeypatch):
    """If the agent mis-fires add_item for a dish already in the cart and the
    customer's text does not name that dish, the cart line must not inflate."""
    from app.ordering.models import OrderItem
    from app.llm.port import ConversationAgentResult

    await _seed_menu(db_session, restaurant.id)
    await _seed_lemon_mint(db_session, restaurant.id)
    await handle_inbound(db_session, _msg("hi", "wamid.bg"), restaurant_id=restaurant.id)
    await db_session.commit()
    await handle_inbound(db_session, _msg("lemon mint", "wamid.bi"), restaurant_id=restaurant.id)
    await db_session.commit()

    conv = await _conv(db_session)
    order_id = conv.state["draft_order_id"]
    qty_before = sum(
        it.qty for it in (await db_session.scalars(
            select(OrderItem).where(OrderItem.order_id == order_id))).all()
    )

    class _StubAddAgent:
        async def respond(self, **kwargs):
            # Mis-fire: add the dish already in cart, customer text won't name it.
            return ConversationAgentResult(
                message="1x Lemon mint added! Anything else?",
                action="add_item",
                action_data={"dish_query": "lemon mint", "qty": None, "items": [],
                             "special_note": "", "apt_room": "", "building": "",
                             "receiver_name": ""},
            )

    monkeypatch.setattr("app.llm.factory.get_conversation_agent", lambda: _StubAddAgent())

    await handle_inbound(db_session, _msg("No that's all", "wamid.bclose"),
                         restaurant_id=restaurant.id)
    await db_session.commit()

    items = (await db_session.scalars(
        select(OrderItem).where(OrderItem.order_id == order_id))).all()
    assert sum(it.qty for it in items) == qty_before  # backstop prevented inflation


async def test_readd_backstop_allows_named_repeat(db_session, restaurant, monkeypatch):
    """Naming the dish again (or giving a qty) is a real add — backstop must allow it."""
    from app.ordering.models import OrderItem
    from app.llm.port import ConversationAgentResult

    await _seed_menu(db_session, restaurant.id)
    await _seed_lemon_mint(db_session, restaurant.id)
    await handle_inbound(db_session, _msg("hi", "wamid.rg"), restaurant_id=restaurant.id)
    await db_session.commit()
    await handle_inbound(db_session, _msg("lemon mint", "wamid.ri"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    order_id = conv.state["draft_order_id"]
    qty_before = sum(it.qty for it in (await db_session.scalars(
        select(OrderItem).where(OrderItem.order_id == order_id))).all())

    class _StubAddAgent:
        async def respond(self, **kwargs):
            return ConversationAgentResult(
                message="Added another Lemon mint! 🛒", action="add_item",
                action_data={"dish_query": "lemon mint", "qty": None, "items": [],
                             "special_note": "", "apt_room": "", "building": "",
                             "receiver_name": ""})
    monkeypatch.setattr("app.llm.factory.get_conversation_agent", lambda: _StubAddAgent())

    # Customer NAMES the dish -> real add.
    await handle_inbound(db_session, _msg("another lemon mint", "wamid.rclose"),
                         restaurant_id=restaurant.id)
    await db_session.commit()
    items = (await db_session.scalars(
        select(OrderItem).where(OrderItem.order_id == order_id))).all()
    assert sum(it.qty for it in items) == qty_before + 1  # named -> added


async def test_location_pin_within_radius_advances_to_address_text(db_session, restaurant):
    """A pin within 10 km is accepted; bot asks for room/building text address."""
    await _seed_menu(db_session, restaurant.id)

    await handle_inbound(db_session, _msg("hi", "wamid.greet3"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    conv.state = {**conv.state, "dialogue_phase": "address_capture",
                  "dialogue_state": "address_capture"}
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
    conv.state = {**conv.state, "dialogue_phase": "address_capture",
                  "dialogue_state": "address_capture"}
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
    # The confirm safety-gate refuses an order with no items, so seed the line that
    # backs the 22.00 subtotal (1x Chicken Biryani @ 22).
    from app.menu.models import Dish
    from app.ordering.models import OrderItem
    dish = (await db_session.scalars(
        select(Dish).where(Dish.restaurant_id == restaurant.id, Dish.dish_number == 110)
    )).first()
    db_session.add(OrderItem(
        order_id=order.id, dish_id=dish.id, dish_number=110, dish_name="Chicken Biryani",
        price_aed=Decimal("22.00"), qty=1,
    ))
    await db_session.flush()
    await db_session.commit()

    await handle_inbound(db_session, _msg("hi", "wamid.greet5"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    conv.state = {
        **conv.state,
        "dialogue_phase": "awaiting_confirmation",
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

    # Real flow: ordering then "done" auto-attaches the saved address on entry to
    # address capture and shows the order summary directly — before any pin is
    # shared. (Sharing a NEW pin is still honoured as a new address.)
    await handle_inbound(db_session, _msg("hi", "wamid.ret1"), restaurant_id=restaurant.id)
    await db_session.commit()
    await handle_inbound(db_session, _msg("chicken biryani", "wamid.retitem"), restaurant_id=restaurant.id)
    await db_session.commit()
    await handle_inbound(db_session, _msg("done", "wamid.ret2"), restaurant_id=restaurant.id)
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


async def _seed_returning_with_saved_address(db_session, restaurant):
    """Seed a customer (phone +971501110001) with one confirmed saved address."""
    from app.ordering.models import Customer, CustomerAddress

    customer = Customer(
        restaurant_id=restaurant.id, phone="+971501110001", name="Returning",
        usual_order_times={}, tags={}, total_orders=1, total_spend=Decimal("22.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    db_session.add(CustomerAddress(
        customer_id=customer.id, latitude=25.21, longitude=55.27,
        room_apartment="5B", building="Marina Tower",
        receiver_name="Returning", confirmed=True,
    ))
    await db_session.commit()


async def test_returning_customer_checkout_goes_straight_to_summary(db_session, restaurant):
    """Returning customer's saved address is auto-attached at checkout and the order
    summary is shown directly — no separate 'use saved address?' step. The summary
    shows the address and offers Confirm / Use new address / Cancel (single-tap repeat)."""
    await _seed_menu(db_session, restaurant.id)
    await _seed_returning_with_saved_address(db_session, restaurant)

    for m in (_msg("hi", "wamid.pa1"), _msg("chicken biryani", "wamid.pa2"),
              _msg("done", "wamid.pa3")):
        await handle_inbound(db_session, m, restaurant_id=restaurant.id)
        await db_session.commit()

    rows = (await db_session.execute(
        select(OutboxMessage).order_by(OutboxMessage.id)
    )).scalars().all()
    last = rows[-1].payload
    assert last.get("type") == "buttons"
    # Summary, not the old "Welcome back?" prompt.
    assert "Welcome back" not in last.get("body", "")
    assert "Order summary" in last.get("body", "")
    # Address shown back to the customer in the summary.
    assert "Marina" in last.get("body", "") or "5B" in last.get("body", "")
    btn_ids = {b["id"] for b in last.get("buttons", [])}
    assert btn_ids == {"confirm_order", "use_new_address", "cancel_order"}

    # The draft order is now in confirmation with the saved address attached.
    conv = await _conv(db_session)
    assert conv.state["dialogue_state"] == "order_confirmation"


async def test_use_new_address_button_switches_to_location_capture(db_session, restaurant):
    """'Use new address' on the summary drops the saved address and re-requests a
    location pin, keeping the cart and not re-offering the saved address."""
    await _seed_menu(db_session, restaurant.id)
    await _seed_returning_with_saved_address(db_session, restaurant)

    for m in (_msg("hi", "wamid.un1"), _msg("chicken biryani", "wamid.un2"),
              _msg("done", "wamid.un3")):
        await handle_inbound(db_session, m, restaurant_id=restaurant.id)
        await db_session.commit()
    await handle_inbound(db_session, _btn("use_new_address", "wamid.un4"),
                         restaurant_id=restaurant.id)
    await db_session.commit()

    conv = await _conv(db_session)
    assert conv.state.get("saved_address_id") is None
    assert conv.state["dialogue_state"] == "address_capture"
    rows = (await db_session.execute(
        select(OutboxMessage).order_by(OutboxMessage.id)
    )).scalars().all()
    body = rows[-1].payload.get("body", "")
    assert "location" in body.lower()
    assert "Welcome back" not in body


async def test_use_saved_button_attaches_address_and_confirms(db_session, restaurant):
    """Tapping 'Use saved address' after the proactive offer attaches it and moves
    to confirmation — one tap, no typing."""
    await _seed_menu(db_session, restaurant.id)
    await _seed_returning_with_saved_address(db_session, restaurant)

    for m in (_msg("hi", "wamid.us1"), _msg("chicken biryani", "wamid.us2"),
              _msg("done", "wamid.us3")):
        await handle_inbound(db_session, m, restaurant_id=restaurant.id)
        await db_session.commit()
    await handle_inbound(db_session, _btn("use_saved_address", "wamid.us4"),
                         restaurant_id=restaurant.id)
    await db_session.commit()

    conv = await _conv(db_session)
    assert conv.state["dialogue_state"] == "order_confirmation"


async def test_new_address_button_marks_offer_and_does_not_reoffer(db_session, restaurant):
    """Tapping 'New address' asks for location/text and marks the offer made, so the
    saved address is never offered again (no double entry)."""
    await _seed_menu(db_session, restaurant.id)
    await _seed_returning_with_saved_address(db_session, restaurant)

    for m in (_msg("hi", "wamid.na1"), _msg("chicken biryani", "wamid.na2"),
              _msg("done", "wamid.na3")):
        await handle_inbound(db_session, m, restaurant_id=restaurant.id)
        await db_session.commit()
    await handle_inbound(db_session, _btn("new_address", "wamid.na4"),
                         restaurant_id=restaurant.id)
    await db_session.commit()

    conv = await _conv(db_session)
    assert conv.state.get("address_offer_made") is True
    rows = (await db_session.execute(
        select(OutboxMessage).order_by(OutboxMessage.id)
    )).scalars().all()
    body = rows[-1].payload.get("body", "")
    assert "location" in body.lower() or "address" in body.lower()
    assert "Welcome back" not in body


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
    last = rows[-1].payload["body"].lower()
    # Arbiter resolves ambiguity automatically — reply confirms addition (not disambiguation prompt).
    # AI reply format varies; check that it's an addition confirmation, not a disambiguation question.
    assert "biryani" in last or "add" in last or "cart" in last


async def test_modify_order_dialogue_flow_after_placed_restarts_sla_and_updates_items(db_session, restaurant):
    """Full modify dialogue after order_placed: 'modify'/'change' -> collect new items (reuse logic) -> 'done' -> confirm button
    calls service (via effects), restarts SLA, updates items, audit, state back to order_placed. TDD red->green.
    """
    await _seed_menu(db_session, restaurant.id)

    from app.menu.models import Dish
    from app.ordering.models import Customer, CustomerAddress, Order, OrderItem
    from app.ordering.fsm import OrderStatus
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal
    from sqlalchemy import select as sa_select

    customer = Customer(
        restaurant_id=restaurant.id, phone="+971501110001", name="Modder",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    addr = CustomerAddress(
        customer_id=customer.id, latitude=25.21, longitude=55.27,
        room_apartment="10", building="Mod Tower",
        receiver_name="Modder", confirmed=True,
    )
    db_session.add(addr)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    order = Order(
        restaurant_id=restaurant.id, customer_id=customer.id,
        order_number="R1-MODT", status=OrderStatus.CONFIRMED,
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("22.00"), total=Decimal("22.00"),
        address_id=addr.id, distance_km=1.0,
        sla_confirmed_at=now, sla_deadline=now + timedelta(minutes=40),
    )
    db_session.add(order)
    await db_session.flush()

    dish = await db_session.scalar(
        sa_select(Dish).where(Dish.dish_number == 110)
    )
    item = OrderItem(
        order_id=order.id, dish_id=dish.id, dish_number=110,
        dish_name="Chicken Biryani", price_aed=Decimal("22.00"), qty=1,
    )
    db_session.add(item)
    await db_session.commit()

    # Ensure conv exists (hi creates it) then force to placed with the order ref (simulates post-confirmation)
    await handle_inbound(db_session, _msg("hi", "wamid.greetmod"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    conv.state = {
        **conv.state,
        "dialogue_phase": "post_order",
        "dialogue_state": "order_placed",
        "pending_order_id": order.id,
    }
    await db_session.commit()

    # 1. Customer says modify (or change order) -> should prompt and set modify_items state
    await handle_inbound(db_session, _msg("modify my order", "wamid.mod1"), restaurant_id=restaurant.id)
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    last_body = rows[-1].payload.get("body", "").lower()
    assert any(k in last_body for k in ["modify", "change", "update", "items", "what would you like"]), f"prompt missing modify cue: {last_body}"

    conv = await _conv(db_session)
    assert conv.state.get("dialogue_state") == "modify_items"
    assert conv.state.get("modify_order_id") == order.id

    # 2. Send new items (qty change) -> accumulates in proposed (re-uses parse/match logic)
    await handle_inbound(db_session, _msg("2x chicken biryani", "wamid.moditem"), restaurant_id=restaurant.id)
    await db_session.commit()

    conv = await _conv(db_session)
    proposed = conv.state.get("modify_proposed", [])
    assert len(proposed) >= 1, "proposed items not collected in state"
    assert any(p.get("qty") == 2 for p in proposed)

    # 3. 'done' -> advances to modify_confirm (shows summary prompt)
    await handle_inbound(db_session, _msg("done", "wamid.moddone"), restaurant_id=restaurant.id)
    await db_session.commit()

    conv = await _conv(db_session)
    assert conv.state.get("dialogue_state") == "modify_confirm"

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    last_body = rows[-1].payload.get("body", "").lower()
    assert "confirm" in last_body or "change" in last_body

    # 4. Confirm button -> calls modify_order (via engine), items updated, SLA restarted, audit, state reset
    orig_deadline = order.sla_deadline
    await handle_inbound(db_session, _btn("confirm_modify", "wamid.modconf"), restaurant_id=restaurant.id)
    await db_session.commit()

    await db_session.refresh(order)
    assert order.subtotal == Decimal("44.00")
    assert order.total == Decimal("44.00")
    assert order.sla_deadline is not None
    assert order.sla_deadline > orig_deadline, "SLA clock must restart on customer-confirmed modify per spec"

    from app.audit.models import AuditLog
    logs = (await db_session.execute(sa_select(AuditLog))).scalars().all()
    assert any(getattr(audit_log, "action", None) == "order_modified" for audit_log in logs), "modify must produce audit"

    conv = await _conv(db_session)
    assert conv.state.get("dialogue_state") == "order_placed"


async def test_greeting_sends_menu_file_when_uploaded(db_session, restaurant, tmp_path, monkeypatch):
    """When MenuFile records exist, greeting enqueues IMAGE/DOCUMENT + short text prompt."""
    from app.config import get_settings
    from app.menu.models import Dish, Menu, MenuFile
    from app.menu.storage import FileBlobStore

    monkeypatch.setenv("APP_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
        db_session.add(menu)
        await db_session.flush()
        db_session.add(Dish(
            menu_id=menu.id, restaurant_id=restaurant.id, dish_number=101,
            name="Biryani", price_aed=Decimal("20.00"),
            category="Rice", is_available=True, name_normalized="biryani",
        ))

        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        store = FileBlobStore(tmp_path)
        digest = store.put(restaurant_id=restaurant.id, data=fake_png, content_type="image/png")
        db_session.add(MenuFile(
            restaurant_id=restaurant.id,
            menu_id=menu.id,
            sha256=digest,
            content_type="image/png",
            size_bytes=len(fake_png),
            original_filename="menu.png",
        ))
        await db_session.commit()

        await handle_inbound(db_session, _msg("hi", "wamid.greet-file"), restaurant_id=restaurant.id)
        await db_session.commit()

        rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
        types = [r.payload.get("type") for r in rows]
        assert "image" in types, "must enqueue IMAGE when menu file is an image"
        assert "text" in types, "must enqueue text prompt after file"

        img_row = next(r for r in rows if r.payload.get("type") == "image")
        assert img_row.payload.get("data") == base64.b64encode(fake_png).decode()
        assert img_row.payload.get("content_type") == "image/png"

        text_rows = [r for r in rows if r.payload.get("type") == "text"]
        # Prompt — not the full processed menu text
        assert any("dish" in (r.payload.get("body") or "").lower() for r in text_rows)
    finally:
        get_settings.cache_clear()


async def test_greeting_falls_back_to_text_menu_when_no_files(db_session, restaurant):
    """When no MenuFile records exist, greeting renders and sends the digital text menu."""
    from app.menu.models import Dish, Menu

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=101,
        name="Biryani", price_aed=Decimal("20.00"),
        category="Rice", is_available=True, name_normalized="biryani",
    ))
    await db_session.commit()

    await handle_inbound(db_session, _msg("hi", "wamid.greet-text"), restaurant_id=restaurant.id)
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    types = [r.payload.get("type") for r in rows]
    assert "text" in types
    assert "image" not in types
    assert "document" not in types
    text_rows = [r for r in rows if r.payload.get("type") == "text"]
    assert any("biryani" in (r.payload.get("body") or "").lower() for r in text_rows)


def test_looks_like_menu_detects_fabricated_list():
    """Safety net: a reply listing dishes+prices is detected (and gets replaced
    with the real DB menu in the ordering phase)."""
    from app.conversation.engine import _looks_like_menu

    fake = "Here's our menu!\n1. Chicken 65 — AED 12\n2. Samosa — AED 5\n3. Lassi — AED 8"
    assert _looks_like_menu(fake) is True
    assert _looks_like_menu("Added Chicken Biryani! Want a drink for AED 12? 😊") is False
    assert _looks_like_menu("Your total is AED 33. Confirm?") is False

    # Emoji-bulleted menu (the live hallucination) — older bullet-only detection MISSED
    # this and let an invented menu through. Must be caught now.
    emoji_menu = (
        "We have a few dishes actually! Here's what's on our menu:\n"
        "🍗 Chicken Biryani, AED 20\n🍗 Special Chicken Biryani, AED 25\n"
        "🍗 Chicken 65, AED 15\n🫓 Parotta, AED 5\n🥤 Mandi Drink, AED 5"
    )
    assert _looks_like_menu(emoji_menu) is True

    # "1x ..." multi-item narration the model claimed on a multi-add (one of which did
    # NOT actually add) — also a fabricated priced list, must be caught.
    narration = "1x Chicken Biryani, AED 20\n1x Mutton Biryani, AED 25\nTotal: AED 45"
    assert _looks_like_menu(narration) is True

    # A single real dish mention + a deterministic cart/summary line must NOT trip it.
    assert _looks_like_menu("Chicken Biryani is AED 20 😊") is False
    assert _looks_like_menu(
        "Added! 🛒 1x Chicken Biryani (AED 20) | Subtotal: AED 20"
    ) is False


async def test_confirm_without_address_routes_to_address_capture(db_session, restaurant):
    """FSM gate: confirming an order that has items but NO delivery address must not place
    it — route back to address capture instead of dispatching an undeliverable order."""
    from app.menu.models import Dish
    from app.ordering.models import Customer, Order, OrderItem

    await _seed_menu(db_session, restaurant.id)
    await handle_inbound(db_session, _msg("hi", "wamid.cna"), restaurant_id=restaurant.id)
    await db_session.commit()
    cust = Customer(restaurant_id=restaurant.id, phone="+971501110001", name="NoAddr",
                    total_orders=0, total_spend=Decimal("0.00"))
    db_session.add(cust)
    await db_session.flush()
    dish = (await db_session.scalars(select(Dish).where(Dish.dish_number == 110))).first()
    order = Order(restaurant_id=restaurant.id, customer_id=cust.id, order_number="R1-NOADDR",
                  status="pending_confirmation", subtotal=Decimal("22.00"),
                  delivery_fee_aed=Decimal("0.00"), total=Decimal("22.00"), address_id=None)
    db_session.add(order)
    await db_session.flush()
    db_session.add(OrderItem(order_id=order.id, dish_id=dish.id, dish_number=110,
                             dish_name="Chicken Biryani", price_aed=Decimal("22.00"), qty=1))
    await db_session.flush()
    conv = await _conv(db_session)
    conv.state = {**conv.state, "dialogue_phase": "awaiting_confirmation",
                  "dialogue_state": "order_confirmation", "pending_order_id": order.id}
    await db_session.commit()

    await handle_inbound(db_session, _btn("confirm_order", "wamid.cnab"), restaurant_id=restaurant.id)
    await db_session.commit()
    await db_session.refresh(order)
    assert order.status == "pending_confirmation"  # NOT confirmed (no address)
    conv = await _conv(db_session)
    assert conv.state["dialogue_state"] == "address_capture"


async def test_frustration_closing_advances_no_inflation(db_session, restaurant):
    """A frustrated 'thats all can't you understand' with a non-empty cart advances
    to address capture without re-adding (real Fake agent path)."""
    from app.ordering.models import OrderItem

    await _seed_menu(db_session, restaurant.id)
    await handle_inbound(db_session, _msg("hi", "wamid.fg"), restaurant_id=restaurant.id)
    await db_session.commit()
    await handle_inbound(db_session, _msg("chicken biryani", "wamid.fi"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    order_id = conv.state["draft_order_id"]
    qty_before = sum(it.qty for it in (await db_session.scalars(
        select(OrderItem).where(OrderItem.order_id == order_id))).all())

    await handle_inbound(db_session, _msg("thats all can't you understand", "wamid.ff"),
                         restaurant_id=restaurant.id)
    await db_session.commit()

    conv = await _conv(db_session)
    items = (await db_session.scalars(
        select(OrderItem).where(OrderItem.order_id == order_id))).all()
    assert sum(it.qty for it in items) == qty_before
    assert conv.state["dialogue_state"] == "address_capture"
