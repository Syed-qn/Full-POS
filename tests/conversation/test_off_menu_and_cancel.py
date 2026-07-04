"""Off-menu order guard + cancel-during-modify escape hatch.

Regression for a live chat where (1) an off-menu add at the order summary was
mis-routed by the LLM (opened a modify flow / cleared the cart instead of
declining), and (2) tapping 'Cancel order' inside the modify flow was treated as a
dish and looped — trapping the customer with no way out.
"""
from decimal import Decimal

from sqlalchemy import select

from app.conversation.engine import (
    _extract_order_dish_query,
    _is_cancel_intent,
    handle_inbound,
)
from app.conversation.models import Conversation
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType

_PHONE = "+971501110001"
_REST_PHONE = "+97141234567"


def _msg(text: str, wa_id: str) -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id, from_phone=_PHONE, type=MessageType.TEXT,
        payload={"text": text}, restaurant_phone=_REST_PHONE, timestamp=1717660800,
    )


def _btn(btn_id: str, wa_id: str) -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id, from_phone=_PHONE, type=MessageType.BUTTON_REPLY,
        payload={"id": btn_id, "title": "Cancel order"},
        restaurant_phone=_REST_PHONE, timestamp=1717660802,
    )


async def _conv(db_session) -> Conversation:
    return (await db_session.execute(
        select(Conversation).where(Conversation.phone == _PHONE)
    )).scalar_one()


async def _seed_menu(db_session, restaurant_id):
    from app.menu.models import Dish, Menu

    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=110,
        name="Chicken Biryani", price_aed=Decimal("20.00"),
        category="Rice", is_available=True, name_normalized="chicken biryani",
    ))
    await db_session.commit()
    return menu


# ── Pure-function: the order-intent extractor ──────────────────────────────────

def test_extract_order_dish_query_positive():
    # Clear orders → the dish phrase is extracted (stripped of qty/articles/filler).
    assert _extract_order_dish_query("1 beef biryani") == "beef biryani"
    assert _extract_order_dish_query("One beef bitani") == "beef bitani"
    assert _extract_order_dish_query("I want one beef biryani also") == "beef biryani"
    assert _extract_order_dish_query("give me 2 paneer tikka") == "paneer tikka"
    assert _extract_order_dish_query("can I get a fish curry please") == "fish curry"


def test_extract_order_dish_query_negative():
    # NOT orders → None, so the off-menu guard never hijacks them.
    for s in (
        "give me a minute",
        "i want to know the price",
        "where is my order",
        "cancel order",
        "i want delivery",
        "add my address",
        "hi",
        "what do you have?",
        "thanks",
        "biryani",  # single word — below the ≥2-token order bar
    ):
        assert _extract_order_dish_query(s) is None, s


def test_is_cancel_intent():
    for s in ("cancel", "Cancel order", "cancel my order", "stop", "never mind", "forget it"):
        assert _is_cancel_intent(s) is True, s
    for s in ("cancel my coupon", "i want chicken biryani", "don't cancel", "cancellation policy?"):
        assert _is_cancel_intent(s) is False, s


# ── Integration: off-menu order at the summary declines (no modify, no clear) ───

async def test_off_menu_order_at_summary_declines(db_session, restaurant):
    """At the order summary, an off-menu add gets the warm decline — never opens a
    modify flow and never clears the cart."""
    await _seed_menu(db_session, restaurant.id)
    await handle_inbound(db_session, _msg("hi", "wamid.g1"), restaurant_id=restaurant.id)
    await db_session.commit()

    conv = await _conv(db_session)
    conv.state = {**conv.state, "dialogue_phase": "awaiting_confirmation",
                  "dialogue_state": "order_confirmation"}
    await db_session.commit()

    await handle_inbound(
        db_session, _msg("I want one beef biryani also", "wamid.off1"),
        restaurant_id=restaurant.id,
    )
    await db_session.commit()

    body = (await db_session.execute(
        select(OutboxMessage).order_by(OutboxMessage.id.desc())
    )).scalars().first().payload["body"]
    assert ("don't have" in body.lower()) or ("couldn't find" in body.lower())
    assert "beef biryani" in body.lower()
    assert "modify" not in body.lower()

    conv = await _conv(db_session)
    assert conv.state.get("dialogue_state") != "modify_items"


# ── Integration: cancel inside the modify flow actually cancels (no trap) ───────

async def test_cancel_order_button_in_modify_cancels(db_session, restaurant):
    """A 'Cancel order' tap while in modify_items cancels the order and exits the
    flow — it is NOT read as a dish (the trap we're fixing)."""
    from app.ordering.service import (
        add_item,
        create_draft_order,
        get_or_create_customer,
    )
    from app.menu.models import Dish

    menu = await _seed_menu(db_session, restaurant.id)
    await handle_inbound(db_session, _msg("hi", "wamid.g2"), restaurant_id=restaurant.id)
    await db_session.commit()

    customer = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone=_PHONE
    )
    dish = await db_session.scalar(select(Dish).where(Dish.menu_id == menu.id))
    order = await create_draft_order(
        db_session, restaurant_id=restaurant.id, customer_id=customer.id
    )
    await add_item(db_session, order=order, dish=dish, qty=1)
    await db_session.flush()

    # Simulate the AI having dropped the customer into the modify flow.
    conv = await _conv(db_session)
    conv.state = {**conv.state, "dialogue_phase": "ordering",
                  "dialogue_state": "modify_items", "modify_order_id": order.id,
                  "pending_order_id": order.id, "draft_order_id": order.id,
                  "modify_proposed": []}
    await db_session.commit()

    await handle_inbound(db_session, _btn("cancel_order", "wamid.cxl"), restaurant_id=restaurant.id)
    await db_session.commit()

    await db_session.refresh(order)
    assert str(order.status) == "cancelled"

    conv = await _conv(db_session)
    assert conv.state.get("dialogue_state") == "cancelled"
    assert conv.state.get("modify_order_id") is None

    body = (await db_session.execute(
        select(OutboxMessage).order_by(OutboxMessage.id.desc())
    )).scalars().first().payload["body"]
    assert "cancel" in body.lower()
    assert "dish" not in body.lower()  # NOT the old "type the name of a dish" loop
