"""Resale offer surfaces in chat to the next customer + accept sells it."""
import copy
from decimal import Decimal

from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.conversation.models import Message
from app.conversation.service import get_or_create_conversation
from app.identity.models import DEFAULT_SETTINGS, Restaurant
from app.menu.models import Dish, Menu
from app.ordering import service as ordering
from app.ordering.fsm import OrderStatus
from app.ordering.models import Customer, CustomerAddress, Order, OrderItem
from app.whatsapp.port import InboundMessage, MessageType


async def _resto_with_resale(db_session):
    s = copy.deepcopy(DEFAULT_SETTINGS)
    s["resale"]["enabled"] = True  # 30% default
    r = Restaurant(name="R", phone="+97140000400", password_hash="x", lat=25.2, lng=55.2, settings=s)
    db_session.add(r)
    await db_session.flush()
    menu = Menu(restaurant_id=r.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(menu_id=menu.id, restaurant_id=r.id, dish_number=1, name="Biryani",
                price_aed=Decimal("40.00"), category="Rice", is_available=True, name_normalized="biryani")
    db_session.add(dish)
    await db_session.flush()
    # cancelled-after-cooking order -> ON_RESALE copy with items
    oc = Customer(restaurant_id=r.id, phone="+971500400001", name="Orig")
    db_session.add(oc)
    await db_session.flush()
    o = Order(restaurant_id=r.id, customer_id=oc.id, order_number="X-1", status=OrderStatus.PREPARING,
              subtotal=Decimal("40.00"), total=Decimal("40.00"))
    db_session.add(o)
    await db_session.flush()
    db_session.add(OrderItem(order_id=o.id, dish_id=dish.id, dish_number=1, dish_name="Biryani",
                             price_aed=Decimal("40.00"), qty=1))
    await db_session.flush()
    await ordering.cancel_order(db_session, order=o, actor="customer", reason="x")
    return r, dish


def _inb(r, phone, text, t="text"):
    return InboundMessage(wa_message_id=f"w-{phone}-{text[:5]}", from_phone=phone,
                          type=MessageType.TEXT, payload={"text": text},
                          restaurant_phone=r.phone, timestamp=1717660900)


async def _last(db_session, conv_id):
    rows = (await db_session.scalars(
        select(Message).where(Message.conversation_id == conv_id, Message.direction == "outbound")
        .order_by(Message.id.desc())
    )).all()
    return str(rows[0].payload) if rows else ""


async def test_resale_offered_on_catalog_greeting(db_session):
    """Catalog mode must still pitch resale (greeting used to return too early)."""
    r, _dish = await _resto_with_resale(db_session)
    r.settings = {**(r.settings or {}), "catalog_ordering_enabled": True, "catalog_id": "CAT1"}
    from app.catalog.models import CatalogProduct
    db_session.add(CatalogProduct(
        restaurant_id=r.id, retailer_id="nwb4pa5fbn", name="Biryani",
        price_aed=Decimal("40.00"), currency="AED", availability="in stock",
        category="Rice", is_active=True, raw={},
    ))
    await db_session.commit()

    phone = "+971500400998"
    await handle_inbound(db_session, _inb(r, phone, "hi"), restaurant_id=r.id)
    await db_session.commit()
    conv = await get_or_create_conversation(db_session, restaurant_id=r.id, phone=phone, counterpart="customer")
    assert conv.state.get("resale_offer_id") is not None


async def test_resale_offered_when_done_after_catalog_basket(db_session):
    """Typing 'done' after a catalogue basket must pitch resale before address."""
    r, dish = await _resto_with_resale(db_session)
    phone = "+971500400997"
    buyer = Customer(restaurant_id=r.id, phone=phone, name="Buyer")
    db_session.add(buyer)
    dish.catalog_retailer_id = "x"
    from app.catalog.models import CatalogProduct
    db_session.add(CatalogProduct(
        restaurant_id=r.id, retailer_id="x", name="Biryani",
        price_aed=Decimal("40.00"), currency="AED", availability="in stock",
        category="Rice", is_active=True, raw={},
    ))
    await db_session.commit()

    from app.catalog.service import handle_catalog_order
    from app.whatsapp.port import InboundMessage, MessageType

    await handle_catalog_order(
        db_session,
        InboundMessage(
            wa_message_id="w-basket", from_phone=phone, type=MessageType.ORDER,
            payload={"product_items": [
                {"product_retailer_id": "x", "quantity": 1, "item_price": "40", "currency": "AED"},
            ]},
            restaurant_phone=r.phone, timestamp=1717660900,
        ),
        restaurant_id=r.id,
    )
    await db_session.commit()

    await handle_inbound(db_session, _inb(r, phone, "done"), restaurant_id=r.id)
    await db_session.commit()
    conv = await get_or_create_conversation(db_session, restaurant_id=r.id, phone=phone, counterpart="customer")
    assert conv.state.get("resale_offer_id") is not None


async def test_resale_offered_on_greeting(db_session):
    r, dish = await _resto_with_resale(db_session)
    phone = "+971500400999"
    await handle_inbound(db_session, _inb(r, phone, "hi"), restaurant_id=r.id)
    await db_session.commit()
    conv = await get_or_create_conversation(db_session, restaurant_id=r.id, phone=phone, counterpart="customer")
    body = (await _last(db_session, conv.id)).lower()
    assert "ready" in body and ("save" in body or "off" in body)
    assert conv.state.get("resale_offer_id") is not None


async def test_resale_accept_with_location_pin_sells_it(db_session):
    r, dish = await _resto_with_resale(db_session)
    phone = "+971500400777"
    buyer = Customer(restaurant_id=r.id, phone=phone, name="Pin Buyer")
    db_session.add(buyer)
    await db_session.commit()

    await handle_inbound(db_session, _inb(r, phone, "hi"), restaurant_id=r.id)
    await db_session.commit()
    await handle_inbound(
        db_session,
        InboundMessage(
            wa_message_id="w-loc", from_phone=phone, type=MessageType.LOCATION,
            payload={"latitude": 25.21, "longitude": 55.21},
            restaurant_phone=r.phone, timestamp=1717660901,
        ),
        restaurant_id=r.id,
    )
    await db_session.commit()

    sold = (await db_session.scalars(
        select(Order).where(Order.customer_id == buyer.id)
    )).all()
    assert len(sold) == 1
    assert sold[0].subtotal == Decimal("28.00")


async def test_resale_accept_with_saved_address_sells_it(db_session):
    r, dish = await _resto_with_resale(db_session)
    phone = "+971500400888"
    # buyer with a saved confirmed address
    buyer = Customer(restaurant_id=r.id, phone=phone, name="Buyer")
    db_session.add(buyer)
    await db_session.flush()
    db_session.add(CustomerAddress(customer_id=buyer.id, latitude=25.21, longitude=55.21,
                                   room_apartment="9", building="Z", receiver_name="Buyer", confirmed=True))
    await db_session.commit()

    await handle_inbound(db_session, _inb(r, phone, "hi"), restaurant_id=r.id)
    await db_session.commit()
    await handle_inbound(db_session, _inb(r, phone, "grab it"), restaurant_id=r.id)
    await db_session.commit()

    # a discounted RESOLD->new order exists for the buyer
    sold = (await db_session.scalars(
        select(Order).where(Order.customer_id == buyer.id)
    )).all()
    assert len(sold) == 1
    assert sold[0].subtotal == Decimal("28.00")  # 30% off 40


async def test_resale_offered_on_direct_typed_order(db_session):
    """A NEW customer who skips the greeting and types a dish directly must still be
    pitched the ready-now resale food (regression: offer only fired on greeting/menu,
    so a typed order or AI chat never surfaced it)."""
    r, _dish = await _resto_with_resale(db_session)
    r.settings = {**(r.settings or {}), "catalog_ordering_enabled": True, "catalog_id": "CAT1"}
    from app.catalog.models import CatalogProduct
    db_session.add(CatalogProduct(
        restaurant_id=r.id, retailer_id="nwb4pa5fbn", name="Biryani",
        price_aed=Decimal("40.00"), currency="AED", availability="in stock",
        category="Rice", is_active=True, raw={},
    ))
    await db_session.commit()

    phone = "+971500400777"  # different phone → not excluded from the resale
    await handle_inbound(db_session, _inb(r, phone, "1 biryani"), restaurant_id=r.id)
    await db_session.commit()
    conv = await get_or_create_conversation(db_session, restaurant_id=r.id, phone=phone, counterpart="customer")
    assert conv.state.get("resale_offer_id") is not None  # offer was pitched


async def test_resale_offered_even_when_settings_lack_resale_block(db_session):
    """Restaurants created BEFORE the resale settings block existed (raw JSONB, no merge
    on read) must still offer resale — config falls back to defaults. Regression: the
    second customer never received the resale message because resale was silently off."""
    from app.menu.models import Dish, Menu
    from app.ordering.models import Customer, Order, OrderItem

    # Restaurant with OLD settings — no 'resale' key at all.
    r = Restaurant(name="Old", phone="+97140000402", password_hash="x", lat=25.2, lng=55.2,
                   settings={"max_radius_km": 10})
    db_session.add(r)
    await db_session.flush()
    menu = Menu(restaurant_id=r.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(menu_id=menu.id, restaurant_id=r.id, dish_number=1, name="Biryani",
                price_aed=Decimal("40.00"), category="Rice", is_available=True, name_normalized="biryani")
    db_session.add(dish)
    await db_session.flush()
    a = Customer(restaurant_id=r.id, phone="+971500402001", name="A")
    db_session.add(a)
    await db_session.flush()
    o = Order(restaurant_id=r.id, customer_id=a.id, order_number="Y-1", status=OrderStatus.PREPARING,
              subtotal=Decimal("40.00"), total=Decimal("40.00"))
    db_session.add(o)
    await db_session.flush()
    db_session.add(OrderItem(order_id=o.id, dish_id=dish.id, dish_number=1, dish_name="Biryani",
                             price_aed=Decimal("40.00"), qty=1))
    await db_session.flush()
    await ordering.cancel_order(db_session, order=o, actor="manager", reason="x")
    await db_session.commit()

    phone = "+971500402002"  # different customer B
    await handle_inbound(db_session, _inb(r, phone, "hi"), restaurant_id=r.id)
    await db_session.commit()
    conv = await get_or_create_conversation(db_session, restaurant_id=r.id, phone=phone, counterpart="customer")
    assert conv.state.get("resale_offer_id") is not None


async def test_resale_refused_when_same_phone_and_address_accepts(db_session):
    """AND-gate delivery guard at accept: the SAME phone + door + building + pin that
    cancelled can't get the food back; the bot refuses delivery to that address."""
    from app.conversation.engine import _handle_resale_accept
    from app.conversation.models import Conversation, Message
    from app.menu.models import Dish, Menu
    from app.ordering.models import Customer, CustomerAddress, Order, OrderItem

    r = Restaurant(name="R", phone="+97140000404", password_hash="x", lat=25.2, lng=55.2)
    db_session.add(r)
    await db_session.flush()
    menu = Menu(restaurant_id=r.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(menu_id=menu.id, restaurant_id=r.id, dish_number=1, name="Biryani",
                price_aed=Decimal("40"), category="Rice", is_available=True, name_normalized="biryani")
    db_session.add(dish)
    await db_session.flush()
    a = Customer(restaurant_id=r.id, phone="+971500404001", name="A")
    db_session.add(a)
    await db_session.flush()
    addr = CustomerAddress(customer_id=a.id, latitude=25.2048, longitude=55.2708,
                           room_apartment="101", building="Tower A", receiver_name="A", confirmed=True)
    db_session.add(addr)
    await db_session.flush()
    o = Order(restaurant_id=r.id, customer_id=a.id, order_number="Z-1", status=OrderStatus.PREPARING,
              subtotal=Decimal("40"), total=Decimal("40"), address_id=addr.id)
    db_session.add(o)
    await db_session.flush()
    db_session.add(OrderItem(order_id=o.id, dish_id=dish.id, dish_number=1, dish_name="Biryani",
                             price_aed=Decimal("40"), qty=1))
    await db_session.flush()
    resale = await ordering.cancel_order(db_session, order=o, actor="customer", reason="x")
    # A comes back on the SAME phone with the SAME saved address and tries to grab it.
    conv = Conversation(restaurant_id=r.id, phone="+971500404001", counterpart="customer",
                        state={"resale_offer_id": resale.id})
    db_session.add(conv)
    await db_session.commit()
    from app.whatsapp.port import InboundMessage, MessageType
    msg = InboundMessage(wa_message_id="zz", from_phone="+971500404001", type=MessageType.TEXT,
                         payload={"text": "grab it"}, restaurant_phone=r.phone, timestamp=1717660999)
    await _handle_resale_accept(db_session, conv, msg, r.id, resale.id)
    await db_session.commit()
    bodies = " ".join(str((m.payload or {}).get("body", "")) for m in (await db_session.scalars(
        select(Message).where(Message.direction == "outbound"))).all()).lower()
    assert "can't be delivered to this address" in bodies
    await db_session.refresh(resale)
    assert str(resale.status) == str(OrderStatus.ON_RESALE)  # NOT sold
