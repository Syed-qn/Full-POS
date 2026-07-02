"""Regression: a stale draft_order_id (left over from a PLACED or CANCELLED order)
must never be reused as the live cart.

Prod bug: customer 'mohamed' accumulated 13+ draft orders; the conversation's
draft_order_id pointed at an old draft (R1-0034 = "3x Chicken Biryani (special)"),
so a fresh order's summary rendered those stale items instead of what was just
ordered. The draft pointer is now cleared on placement and the resolver refuses any
non-draft order as the cart.
"""
from decimal import Decimal

from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.conversation.models import Conversation
from app.whatsapp.port import InboundMessage, MessageType


def _msg(text: str, wa_id: str) -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id, from_phone="+971501110001", type=MessageType.TEXT,
        payload={"text": text}, restaurant_phone="+97141234567", timestamp=1717660800,
    )


async def _seed_menu(db_session, restaurant_id):
    from app.menu.models import Dish, Menu

    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=110,
        name="Chicken Biryani", price_aed=Decimal("20.00"), category="Rice",
        is_available=True, name_normalized="chicken biryani",
    ))
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=201,
        name="Mutton Karahi", price_aed=Decimal("35.00"), category="Curries",
        is_available=True, name_normalized="mutton karahi",
    ))
    await db_session.commit()


async def _chicken(db_session, restaurant_id):
    from app.menu.models import Dish
    return (await db_session.execute(
        select(Dish).where(Dish.dish_number == 110, Dish.restaurant_id == restaurant_id)
    )).scalar_one()


async def test_new_order_does_not_reuse_a_placed_order_pointer(db_session, restaurant):
    """draft_order_id left pointing at a CONFIRMED order → a new order starts a fresh
    draft; the placed order is never mutated and its items never leak into the cart."""
    from app.ordering.models import OrderItem
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer

    await _seed_menu(db_session, restaurant.id)
    cust = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971501110001"
    )
    placed = await create_draft_order(db_session, restaurant_id=restaurant.id, customer_id=cust.id)
    await add_item(db_session, order=placed, dish=await _chicken(db_session, restaurant.id), qty=3)
    placed.status = "confirmed"  # simulate an order that was already placed
    await db_session.flush()

    # A conversation whose STALE pointer still names the placed order.
    conv = Conversation(
        restaurant_id=restaurant.id, phone="+971501110001", counterpart="customer",
        state={"draft_order_id": placed.id, "dialogue_phase": "ordering",
               "dialogue_state": "collecting_items"},
    )
    db_session.add(conv)
    await db_session.commit()

    # Customer orders again WITHOUT a greeting — this used to append onto the placed order.
    await handle_inbound(db_session, _msg("mutton karahi", "wamid.dl-1"), restaurant_id=restaurant.id)
    await db_session.commit()

    # The placed order is untouched: still exactly its 3 chicken, still confirmed.
    placed_items = (await db_session.execute(
        select(OrderItem).where(OrderItem.order_id == placed.id)
    )).scalars().all()
    assert len(placed_items) == 1 and placed_items[0].qty == 3
    assert placed.status == "confirmed"

    # The new dish landed in a NEW draft order (different id), holding only the mutton.
    fresh = (await db_session.execute(
        select(OrderItem).where(OrderItem.dish_number == 201)
    )).scalars().all()
    assert len(fresh) == 1
    assert fresh[0].order_id != placed.id

    refreshed = (await db_session.execute(
        select(Conversation).where(Conversation.id == conv.id)
    )).scalar_one()
    assert refreshed.state["draft_order_id"] == fresh[0].order_id


async def test_resolver_refuses_a_confirmed_order_as_cart(db_session, restaurant):
    """_resolve_draft_order must not return a placed order as the live cart."""
    from app.conversation.engine import _resolve_draft_order
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer

    await _seed_menu(db_session, restaurant.id)
    cust = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971501110001"
    )
    placed = await create_draft_order(db_session, restaurant_id=restaurant.id, customer_id=cust.id)
    await add_item(db_session, order=placed, dish=await _chicken(db_session, restaurant.id), qty=1)
    placed.status = "confirmed"
    await db_session.flush()

    conv = Conversation(
        restaurant_id=restaurant.id, phone="+971501110001", counterpart="customer",
        state={"draft_order_id": placed.id},
    )
    db_session.add(conv)
    await db_session.flush()

    resolved = await _resolve_draft_order(
        db_session, conv, restaurant_id=restaurant.id, phone="+971501110001"
    )
    # No live draft exists (only a placed order) → None, never the confirmed order.
    assert resolved is None


async def test_cart_summary_merges_same_dish_into_one_noted_line(db_session, restaurant):
    """W2 contract (R-002 / RA-4): a dish merges to ONE line per (dish_id, variant_name);
    a note applied to that dish updates the single line rather than creating a duplicate
    paid line. This kills the biryani incident (plain + 'double masala' showed as two
    biryani lines and doubled the price).

    NOTE (product consequence, W2 design 'one line per (dish, variant); notes accumulate'):
    two DELIBERATE separate-prep orders for the same dish (e.g. '2 no onion' + '2 extra
    spicy') also collapse to one line with the surviving note — the kitchen loses the
    per-unit distinction. Accepted under the approved W2 design; revisit if per-unit prep
    tickets are needed."""
    from app.conversation.engine import _build_cart_summary
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer

    await _seed_menu(db_session, restaurant.id)
    cust = await get_or_create_customer(db_session, restaurant_id=restaurant.id, phone="+971501110001")
    order = await create_draft_order(db_session, restaurant_id=restaurant.id, customer_id=cust.id)
    chicken = await _chicken(db_session, restaurant.id)
    await add_item(db_session, order=order, dish=chicken, qty=2)  # plain
    await add_item(db_session, order=order, dish=chicken, qty=2, notes="double masala")  # note wins, merges
    await db_session.commit()

    conv = Conversation(
        restaurant_id=restaurant.id, phone="+971501110001", counterpart="customer",
        state={"draft_order_id": order.id, "dialogue_phase": "ordering"},
    )
    db_session.add(conv)
    await db_session.commit()

    summary = await _build_cart_summary(db_session, conv)
    assert "double masala" in summary  # the note is visible on the merged line
    # ONE merged biryani line (no accidental duplicate) — the W2 fix.
    assert summary.count("Chicken Biryani") == 1
    assert "4x" in summary  # qty accumulated onto the single line


async def test_special_note_for_existing_cart_item_updates_line_not_duplicate(db_session, restaurant):
    """A prep note for an item already in the cart must update that line, not add a
    second copy of the same dish and overcharge the customer."""
    from unittest.mock import AsyncMock, patch

    from app.llm.port import ConversationAgentResult
    from app.ordering.models import OrderItem
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer

    await _seed_menu(db_session, restaurant.id)
    cust = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971501110001"
    )
    order = await create_draft_order(db_session, restaurant_id=restaurant.id, customer_id=cust.id)
    chicken = await _chicken(db_session, restaurant.id)
    await add_item(db_session, order=order, dish=chicken, qty=1)
    conv = Conversation(
        restaurant_id=restaurant.id, phone="+971501110001", counterpart="customer",
        state={"draft_order_id": order.id, "dialogue_phase": "ordering",
               "dialogue_state": "collecting_items"},
    )
    db_session.add(conv)
    await db_session.commit()

    result = ConversationAgentResult(
        message="Noted, double masala for the Chicken Biryani.",
        action="add_item",
        action_data={
            "dish_query": "chicken biryani",
            "qty": 1,
            "special_note": "double masala",
        },
    )
    with patch("app.llm.fake.FakeConversationAgent.respond",
               new=AsyncMock(return_value=result)):
        await handle_inbound(
            db_session,
            _msg("Need double masala in biriyani", "wamid.note-existing"),
            restaurant_id=restaurant.id,
        )
    await db_session.commit()

    items = (await db_session.scalars(
        select(OrderItem).where(OrderItem.order_id == order.id)
    )).all()
    assert len(items) == 1
    assert items[0].qty == 1
    assert items[0].notes == "double masala"
    await db_session.refresh(order)
    assert order.subtotal == Decimal("20.00")


async def test_quantity_correction_with_note_collapses_duplicate_same_dish_lines(
    db_session, restaurant
):
    """If a duplicate plain/noted line already exists, a structured correction to
    exactly one noted item must collapse the cart to that single line."""
    from unittest.mock import AsyncMock, patch

    from app.llm.port import ConversationAgentResult
    from app.ordering.models import OrderItem
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer

    await _seed_menu(db_session, restaurant.id)
    cust = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971501110001"
    )
    order = await create_draft_order(db_session, restaurant_id=restaurant.id, customer_id=cust.id)
    chicken = await _chicken(db_session, restaurant.id)
    await add_item(db_session, order=order, dish=chicken, qty=1)
    await add_item(db_session, order=order, dish=chicken, qty=1, notes="double masala")
    conv = Conversation(
        restaurant_id=restaurant.id, phone="+971501110001", counterpart="customer",
        state={"draft_order_id": order.id, "dialogue_phase": "ordering",
               "dialogue_state": "collecting_items"},
    )
    db_session.add(conv)
    await db_session.commit()

    result = ConversationAgentResult(
        message="Updated to 1 Chicken Biryani with double masala.",
        action="update_qty",
        action_data={
            "dish_query": "chicken biryani",
            "qty": 1,
            "special_note": "double masala",
        },
    )
    with patch("app.llm.fake.FakeConversationAgent.respond",
               new=AsyncMock(return_value=result)):
        await handle_inbound(
            db_session,
            _msg("I need only 1 biriyani with double masala", "wamid.note-correct"),
            restaurant_id=restaurant.id,
        )
    await db_session.commit()

    items = (await db_session.scalars(
        select(OrderItem).where(OrderItem.order_id == order.id)
    )).all()
    assert len(items) == 1
    assert items[0].qty == 1
    assert items[0].notes == "double masala"
    await db_session.refresh(order)
    assert order.subtotal == Decimal("20.00")
