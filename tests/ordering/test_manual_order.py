# tests/ordering/test_manual_order.py
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.menu.models import Dish, Menu
from app.ordering.models import OrderItem, Customer, CustomerAddress
from app.outbox.models import OutboxMessage


async def _seed_menu(db_session, restaurant_id: int) -> Menu:
    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id,
        dish_number=101, name="Chicken Biryani", price_aed=Decimal("22.00"),
        category="Rice", is_available=True, name_normalized="chicken biryani",
    ))
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id,
        dish_number=201, name="Mutton Karahi", price_aed=Decimal("35.00"),
        category="Curries", is_available=True, name_normalized="mutton karahi",
    ))
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id,
        dish_number=301, name="Unavailable Dish", price_aed=Decimal("10.00"),
        category="Other", is_available=False, name_normalized="unavailable dish",
    ))
    await db_session.commit()
    return menu


async def _get_dish_id(db_session, menu_id: int, name: str) -> int:
    dish = await db_session.scalar(
        select(Dish).where(Dish.menu_id == menu_id, Dish.name == name)
    )
    return dish.id


async def test_create_manual_order_new_customer(db_session, restaurant):
    """New phone → customer created, order confirmed, items correct, SLA set."""
    from app.ordering.service import create_manual_order

    menu = await _seed_menu(db_session, restaurant.id)
    biryani_id = await _get_dish_id(db_session, menu.id, "Chicken Biryani")
    karahi_id = await _get_dish_id(db_session, menu.id, "Mutton Karahi")

    order = await create_manual_order(
        db_session,
        restaurant_id=restaurant.id,
        customer_phone="+971509990001",
        customer_name="Ahmed Al Rashid",
        items=[
            {"dish_id": biryani_id, "qty": 2, "notes": None},
            {"dish_id": karahi_id, "qty": 1, "notes": "extra spicy"},
        ],
        apt_room="Apt 404",
        building="Marina Tower",
        receiver_name="Ahmed Al Rashid",
        address_notes=None,
        delivery_fee_aed=Decimal("0.00"),
    )
    await db_session.commit()

    assert order.status == "confirmed"
    assert order.sla_confirmed_at is not None
    assert order.sla_deadline is not None

    items = (
        await db_session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ).all()
    assert len(items) == 2
    names = {i.dish_name for i in items}
    assert names == {"Chicken Biryani", "Mutton Karahi"}

    biryani = next(i for i in items if i.dish_name == "Chicken Biryani")
    assert biryani.qty == 2

    assert order.subtotal == Decimal("79.00")   # 22*2 + 35*1
    assert order.total == Decimal("79.00")

    customer = await db_session.scalar(
        select(Customer).where(Customer.phone == "+971509990001")
    )
    assert customer is not None
    assert customer.name == "Ahmed Al Rashid"


async def test_create_manual_order_existing_customer(db_session, restaurant):
    """Known phone → reuses customer row; new address stored."""
    from app.ordering.service import create_manual_order, get_or_create_customer

    menu = await _seed_menu(db_session, restaurant.id)
    biryani_id = await _get_dish_id(db_session, menu.id, "Chicken Biryani")

    # Pre-create customer
    existing = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971509990002"
    )
    existing.name = "Sara"
    await db_session.commit()

    await create_manual_order(
        db_session,
        restaurant_id=restaurant.id,
        customer_phone="+971509990002",
        customer_name="Sara Updated",   # should NOT overwrite existing name
        items=[{"dish_id": biryani_id, "qty": 1, "notes": None}],
        apt_room="Unit 5",
        building="Gold Tower",
        receiver_name="Sara",
        address_notes=None,
        delivery_fee_aed=Decimal("5.00"),
    )
    await db_session.commit()

    customers = (
        await db_session.scalars(
            select(Customer).where(
                Customer.restaurant_id == restaurant.id,
                Customer.phone == "+971509990002",
            )
        )
    ).all()
    assert len(customers) == 1  # no duplicate
    assert customers[0].name == "Sara"  # original name preserved

    address = await db_session.scalar(
        select(CustomerAddress).where(CustomerAddress.customer_id == customers[0].id)
    )
    assert address is not None
    assert address.building == "Gold Tower"


async def test_create_manual_order_delivery_fee_included_in_total(db_session, restaurant):
    """delivery_fee_aed is added to subtotal in order total."""
    from app.ordering.service import create_manual_order

    menu = await _seed_menu(db_session, restaurant.id)
    biryani_id = await _get_dish_id(db_session, menu.id, "Chicken Biryani")

    order = await create_manual_order(
        db_session,
        restaurant_id=restaurant.id,
        customer_phone="+971509990003",
        customer_name=None,
        items=[{"dish_id": biryani_id, "qty": 1, "notes": None}],
        apt_room="12A",
        building="Al Noor",
        receiver_name="Guest",
        address_notes=None,
        delivery_fee_aed=Decimal("10.00"),
    )
    await db_session.commit()

    assert order.delivery_fee_aed == Decimal("10.00")
    assert order.subtotal == Decimal("22.00")
    assert order.total == Decimal("32.00")


async def test_create_manual_order_no_active_menu_raises(db_session, restaurant):
    """ValueError raised when no active menu exists."""
    from app.ordering.service import create_manual_order

    with pytest.raises(ValueError, match="No active menu"):
        await create_manual_order(
            db_session,
            restaurant_id=restaurant.id,
            customer_phone="+971509990004",
            customer_name=None,
            items=[{"dish_id": 999, "qty": 1, "notes": None}],
            apt_room="1A",
            building="Tower",
            receiver_name="Guest",
            address_notes=None,
            delivery_fee_aed=Decimal("0.00"),
        )


async def test_create_manual_order_unavailable_dish_raises(db_session, restaurant):
    """ValueError raised when dish is unavailable."""
    from app.ordering.service import create_manual_order

    menu = await _seed_menu(db_session, restaurant.id)
    unavail_id = await _get_dish_id(db_session, menu.id, "Unavailable Dish")

    with pytest.raises(ValueError, match=str(unavail_id)):
        await create_manual_order(
            db_session,
            restaurant_id=restaurant.id,
            customer_phone="+971509990005",
            customer_name=None,
            items=[{"dish_id": unavail_id, "qty": 1, "notes": None}],
            apt_room="1A",
            building="Tower",
            receiver_name="Guest",
            address_notes=None,
            delivery_fee_aed=Decimal("0.00"),
        )


async def test_outbox_message_enqueued_after_manual_order(db_session, restaurant):
    """WhatsApp confirmation OutboxMessage created with correct phone."""
    from app.ordering.service import create_manual_order

    menu = await _seed_menu(db_session, restaurant.id)
    biryani_id = await _get_dish_id(db_session, menu.id, "Chicken Biryani")

    order = await create_manual_order(
        db_session,
        restaurant_id=restaurant.id,
        customer_phone="+971509990006",
        customer_name=None,
        items=[{"dish_id": biryani_id, "qty": 1, "notes": None}],
        apt_room="1A",
        building="Tower",
        receiver_name="Guest",
        address_notes=None,
        delivery_fee_aed=Decimal("0.00"),
    )
    await db_session.commit()

    outbox = (
        await db_session.scalars(
            select(OutboxMessage).where(
                OutboxMessage.restaurant_id == restaurant.id,
                OutboxMessage.to_phone == "+971509990006",
            )
        )
    ).all()
    assert len(outbox) == 1
    assert order.order_number in outbox[0].payload["body"]


async def test_manual_order_geocodes_address_to_pin(db_session, restaurant):
    """A typed manual address is geocoded to a drop-off pin so the rider gets a
    Navigate link and the customer's tracking map has a destination."""
    from app.ordering.service import create_manual_order

    menu = await _seed_menu(db_session, restaurant.id)
    biryani_id = await _get_dish_id(db_session, menu.id, "Chicken Biryani")

    order = await create_manual_order(
        db_session,
        restaurant_id=restaurant.id,
        customer_phone="+971509990777",
        customer_name="Pin User",
        items=[{"dish_id": biryani_id, "qty": 1, "notes": None}],
        apt_room="Apt 12",
        building="Marina Tower",  # offline gazetteer resolves "marina" → coords
        receiver_name="Pin User",
        address_notes=None,
        delivery_fee_aed=Decimal("0.00"),
    )
    await db_session.commit()

    addr = await db_session.get(CustomerAddress, order.address_id)
    assert addr is not None
    assert addr.latitude is not None and addr.longitude is not None
    # Dubai Marina centroid from the offline gazetteer.
    assert round(addr.latitude, 3) == 25.081


async def test_manual_order_uses_explicit_pin_when_provided(db_session, restaurant):
    """When the manager picks a pin on the map, those exact coords are stored —
    no geocoding of the building text."""
    from app.ordering.service import create_manual_order

    menu = await _seed_menu(db_session, restaurant.id)
    biryani_id = await _get_dish_id(db_session, menu.id, "Chicken Biryani")

    order = await create_manual_order(
        db_session,
        restaurant_id=restaurant.id,
        customer_phone="+971509990779",
        customer_name="Pin Picker",
        items=[{"dish_id": biryani_id, "qty": 1, "notes": None}],
        apt_room="Apt 7",
        building="Anything At All",  # would NOT geocode — but pin overrides
        receiver_name="Pin Picker",
        address_notes=None,
        delivery_fee_aed=Decimal("0.00"),
        latitude=25.1972,
        longitude=55.2744,
    )
    await db_session.commit()

    addr = await db_session.get(CustomerAddress, order.address_id)
    assert (addr.latitude, addr.longitude) == (25.1972, 55.2744)


def test_fake_geo_suggest_returns_candidates():
    """The offline provider's suggest() backs the no-pin geocode fallback."""
    from app.geo.fake import FakeGeoProvider

    out = FakeGeoProvider().suggest("Dubai Marina tower", near=(25.2, 55.27))
    assert out and out[0].latitude and out[0].longitude
    assert isinstance(out[0].description, str)
    # Unknown place → no candidates.
    assert FakeGeoProvider().suggest("zzqq nowhere 9981") == []


async def test_manual_order_unknown_building_degrades_to_no_pin(db_session, restaurant):
    """If geocoding can't resolve the building, the order still succeeds with a
    null pin (text-only address) — no crash, same as before."""
    from app.ordering.service import create_manual_order

    menu = await _seed_menu(db_session, restaurant.id)
    biryani_id = await _get_dish_id(db_session, menu.id, "Chicken Biryani")

    order = await create_manual_order(
        db_session,
        restaurant_id=restaurant.id,
        customer_phone="+971509990778",
        customer_name="NoPin User",
        items=[{"dish_id": biryani_id, "qty": 1, "notes": None}],
        apt_room="Apt 9",
        building="Zzqq Unknown Place 9981",  # not in any gazetteer
        receiver_name="NoPin User",
        address_notes=None,
        delivery_fee_aed=Decimal("0.00"),
    )
    await db_session.commit()

    assert order.status == "confirmed"
    addr = await db_session.get(CustomerAddress, order.address_id)
    assert addr is not None
    assert addr.latitude is None and addr.longitude is None


def _token(restaurant_id: int) -> str:
    from app.identity.auth import create_access_token
    return create_access_token(restaurant_id=restaurant_id)


async def test_api_customer_lookup_found(client, db_session, restaurant):
    """GET /manual/customer-lookup returns name + last address for known phone."""
    from app.ordering.service import get_or_create_customer, upsert_address

    customer = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971509991001"
    )
    customer.name = "Lookup User"
    await db_session.flush()
    await upsert_address(
        db_session,
        customer_id=customer.id,
        latitude=None, longitude=None,
        room_apartment="B12",
        building="Creek Tower",
        receiver_name="Lookup User",
        additional_details=None,
        confirmed=True,
    )
    await db_session.commit()

    resp = await client.get(
        "/api/v1/orders/manual/customer-lookup",
        params={"phone": "+971509991001"},
        headers={"Authorization": f"Bearer {_token(restaurant.id)}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Lookup User"
    assert data["last_address"]["building"] == "Creek Tower"
    assert data["last_address"]["apt_room"] == "B12"


async def test_api_customer_lookup_not_found(client, db_session, restaurant):
    """GET /manual/customer-lookup returns 404 for unknown phone."""
    resp = await client.get(
        "/api/v1/orders/manual/customer-lookup",
        params={"phone": "+971509999999"},
        headers={"Authorization": f"Bearer {_token(restaurant.id)}"},
    )
    assert resp.status_code == 404


async def test_api_create_manual_order(client, db_session, restaurant):
    """POST /manual creates confirmed order, returns OrderOut."""
    menu = await _seed_menu(db_session, restaurant.id)
    biryani_id = await _get_dish_id(db_session, menu.id, "Chicken Biryani")

    body = {
        "customer_phone": "+971509992001",
        "customer_name": "Walk-in User",
        "items": [{"dish_id": biryani_id, "qty": 2, "notes": None}],
        "address": {
            "apt_room": "Room 7",
            "building": "Hotel Block",
            "receiver_name": "Walk-in User",
            "notes": None,
        },
        "delivery_fee_aed": "0.00",
    }
    resp = await client.post(
        "/api/v1/orders/manual",
        json=body,
        headers={"Authorization": f"Bearer {_token(restaurant.id)}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "confirmed"
    assert data["customer_phone"] == "+971509992001"
    assert len(data["items"]) == 1
    assert data["items"][0]["qty"] == 2
    assert data["total_aed"] == "44.00"


async def test_api_create_manual_order_unavailable_dish_returns_422(client, db_session, restaurant):
    """POST /manual with unavailable dish → 422."""
    menu = await _seed_menu(db_session, restaurant.id)
    unavail_id = await _get_dish_id(db_session, menu.id, "Unavailable Dish")

    body = {
        "customer_phone": "+971509992002",
        "customer_name": None,
        "items": [{"dish_id": unavail_id, "qty": 1, "notes": None}],
        "address": {"apt_room": "1A", "building": "T", "receiver_name": "X", "notes": None},
        "delivery_fee_aed": "0.00",
    }
    resp = await client.post(
        "/api/v1/orders/manual",
        json=body,
        headers={"Authorization": f"Bearer {_token(restaurant.id)}"},
    )
    assert resp.status_code == 422


async def test_api_create_manual_order_no_menu_returns_422(client, db_session, restaurant):
    """POST /manual with no active menu → 422."""
    body = {
        "customer_phone": "+971509992003",
        "customer_name": None,
        "items": [{"dish_id": 1, "qty": 1, "notes": None}],
        "address": {"apt_room": "1A", "building": "T", "receiver_name": "X", "notes": None},
        "delivery_fee_aed": "0.00",
    }
    resp = await client.post(
        "/api/v1/orders/manual",
        json=body,
        headers={"Authorization": f"Bearer {_token(restaurant.id)}"},
    )
    assert resp.status_code == 422


async def test_api_get_active_menu(client, db_session, restaurant):
    """GET /menus/active returns active menu with dishes."""
    await _seed_menu(db_session, restaurant.id)

    resp = await client.get(
        "/api/v1/menus/active",
        headers={"Authorization": f"Bearer {_token(restaurant.id)}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "active"
    available = [d for d in data["dishes"] if d["is_available"]]
    assert len(available) == 2
