"""WhatsApp catalog ordering flow (separate from the conversation engine).

Covers: the normalizer parsing an ``order`` (cart) message, and the catalog handler
turning a cart into a draft order + confirmation, with retailer-id -> dish mapping.
"""
from decimal import Decimal

from sqlalchemy import select

from app.catalog.service import handle_catalog_order
from app.menu.models import Dish, Menu
from app.ordering.models import Order, OrderItem
from app.outbox.models import OutboxMessage
from app.webhook.normalizer import parse_cloud_payload
from app.whatsapp.port import InboundMessage, MessageType


def _order_inbound(items, wa_id="wamid.cart1") -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id, from_phone="+971501110001", type=MessageType.ORDER,
        payload={"catalog_id": "1528685515412822", "text": None, "product_items": items},
        restaurant_phone="+97141234567", timestamp=1717660800,
    )


async def _seed_catalog_menu(db_session, restaurant_id):
    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=1,
        name="Chicken Biryani", price_aed=Decimal("20.00"), category="Biryani",
        is_available=True, name_normalized="chicken biryani",
        catalog_retailer_id="nwb4pa5fbn",
    ))
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=2,
        name="Lemon Mint", price_aed=Decimal("12.00"), category="Drinks",
        is_available=True, name_normalized="lemon mint",
        catalog_retailer_id="lemonmint01",
    ))
    await db_session.commit()


# ── normalizer ───────────────────────────────────────────────────────────────

def test_normalizer_parses_catalog_order():
    payload = {
        "entry": [{"changes": [{"value": {
            "metadata": {"display_phone_number": "+97141234567"},
            "messages": [{
                "id": "wamid.x", "from": "971501110001", "timestamp": "1717660800",
                "type": "order",
                "order": {
                    "catalog_id": "1528685515412822",
                    "product_items": [
                        {"product_retailer_id": "nwb4pa5fbn", "quantity": "2",
                         "item_price": "20", "currency": "AED"},
                    ],
                },
            }],
        }}]}],
    }
    msgs = parse_cloud_payload(payload)
    assert len(msgs) == 1
    m = msgs[0]
    assert m.type == MessageType.ORDER
    assert m.payload["catalog_id"] == "1528685515412822"
    assert m.payload["product_items"][0]["product_retailer_id"] == "nwb4pa5fbn"


# ── handler ──────────────────────────────────────────────────────────────────

async def test_catalog_cart_creates_order_and_confirms(db_session, restaurant):
    await _seed_catalog_menu(db_session, restaurant.id)
    inbound = _order_inbound([
        {"product_retailer_id": "nwb4pa5fbn", "quantity": "2", "item_price": "20", "currency": "AED"},
        {"product_retailer_id": "lemonmint01", "quantity": "1", "item_price": "12", "currency": "AED"},
    ])
    await handle_catalog_order(db_session, inbound, restaurant_id=restaurant.id)
    await db_session.commit()

    order = (await db_session.scalars(select(Order))).one()
    items = (await db_session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))).all()
    assert {i.dish_name for i in items} == {"Chicken Biryani", "Lemon Mint"}
    assert order.subtotal == Decimal("52.00")  # 2*20 + 1*12

    msg = (await db_session.scalars(
        select(OutboxMessage).where(OutboxMessage.to_phone == "+971501110001")
    )).one()
    body = msg.payload["body"]
    assert "Chicken Biryani" in body
    # After the basket the customer is in the SAME flow as the text bot: send 'done'
    # to continue to delivery (not a separate catalogue-only path).
    assert "done" in body.lower()

    # The basket filled the engine's conversation cart and left normal state.
    from app.conversation.models import Conversation
    conv = (await db_session.scalars(
        select(Conversation).where(Conversation.phone == "+971501110001")
    )).one()
    assert conv.state.get("draft_order_id") == order.id
    assert conv.state.get("dialogue_state") == "collecting_items"


async def test_unmapped_items_do_not_create_empty_order(db_session, restaurant):
    await _seed_catalog_menu(db_session, restaurant.id)
    inbound = _order_inbound([
        {"product_retailer_id": "unknown999", "quantity": "1", "item_price": "99", "currency": "AED"},
    ])
    await handle_catalog_order(db_session, inbound, restaurant_id=restaurant.id)
    await db_session.commit()

    items = (await db_session.scalars(select(OrderItem))).all()
    assert items == []  # nothing mappable
    msg = (await db_session.scalars(
        select(OutboxMessage).where(OutboxMessage.to_phone == "+971501110001")
    )).one()
    assert "couldn't match" in msg.payload["body"]


async def test_partial_mapping_adds_known_and_lists_unknown(db_session, restaurant):
    await _seed_catalog_menu(db_session, restaurant.id)
    inbound = _order_inbound([
        {"product_retailer_id": "nwb4pa5fbn", "quantity": "1", "item_price": "20", "currency": "AED"},
        {"product_retailer_id": "ghost", "quantity": "3", "item_price": "5", "currency": "AED"},
    ])
    await handle_catalog_order(db_session, inbound, restaurant_id=restaurant.id)
    await db_session.commit()

    items = (await db_session.scalars(select(OrderItem))).all()
    assert len(items) == 1 and items[0].dish_name == "Chicken Biryani"
    body = (await db_session.scalars(select(OutboxMessage))).one().payload["body"]
    assert "couldn't add" in body.lower()
