"""Split order by item, split order by seat, merge orders, and transfer order
between staff — service-level and router-level (RBAC) tests."""

import itertools
from decimal import Decimal

import pytest
from sqlalchemy import select

_order_number_seq = itertools.count(1)


async def _make_customer(db_session, restaurant, phone="+971500000900", name="Split Test"):
    from app.ordering.models import Customer

    cust = Customer(restaurant_id=restaurant.id, phone=phone, name=name)
    db_session.add(cust)
    await db_session.flush()
    return cust


async def _make_dish(db_session, restaurant, *, dish_number, name, price_aed):
    from app.menu.models import Dish, Menu

    menu = await db_session.scalar(
        select(Menu).where(Menu.restaurant_id == restaurant.id)
    )
    if menu is None:
        menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
        db_session.add(menu)
        await db_session.flush()
    dish = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=dish_number,
        name=name,
        price_aed=price_aed,
        category="Test",
        is_available=True,
        name_normalized=name.lower(),
    )
    db_session.add(dish)
    await db_session.flush()
    return dish


async def _make_order_with_items(
    db_session, restaurant, customer, *, status="draft", items=None, staff_id=None, table_id=None
):
    """items: list of dicts (price_aed, qty, seat_number)."""
    from app.ordering.models import Order, OrderItem

    items = items if items is not None else [{"price_aed": Decimal("10.00"), "qty": 1}]
    subtotal = sum(
        (Decimal(str(i["price_aed"])) * i.get("qty", 1) for i in items), Decimal("0.00")
    )
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        order_number=f"SPLIT-{customer.id}-{status}-{next(_order_number_seq)}",
        status=status,
        subtotal=subtotal,
        total=subtotal,
        staff_id=staff_id,
        table_id=table_id,
    )
    db_session.add(order)
    await db_session.flush()
    order_items = []
    for i, entry in enumerate(items):
        dish = await _make_dish(
            db_session,
            restaurant,
            dish_number=100 + i + order.id * 1000,
            name=f"Dish {i} for order {order.id}",
            price_aed=Decimal(str(entry["price_aed"])),
        )
        oi = OrderItem(
            order_id=order.id,
            dish_id=dish.id,
            dish_number=dish.dish_number,
            dish_name=dish.name,
            price_aed=Decimal(str(entry["price_aed"])),
            qty=entry.get("qty", 1),
            seat_number=entry.get("seat_number"),
        )
        db_session.add(oi)
        order_items.append(oi)
    await db_session.flush()
    return order, order_items


async def _restaurant_by_email(db_session, email="owner@biryani.ae"):
    from app.identity.models import Restaurant

    return await db_session.scalar(select(Restaurant).where(Restaurant.email == email))


async def _manager_staff_headers(client, auth_headers, name="Manager Layla", pin="7777"):
    staff_resp = await client.post(
        "/api/v1/staff",
        json={"name": name, "role": "manager", "pin": pin},
        headers=auth_headers,
    )
    staff_id = staff_resp.json()["id"]
    login = await client.post(
        "/api/v1/staff/login", json={"staff_id": staff_id, "pin": pin}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, staff_id


async def _cashier_staff_headers(client, auth_headers, name="Cashier Nadia", pin="8888"):
    staff_resp = await client.post(
        "/api/v1/staff",
        json={"name": name, "role": "cashier", "pin": pin},
        headers=auth_headers,
    )
    staff_id = staff_resp.json()["id"]
    login = await client.post(
        "/api/v1/staff/login", json={"staff_id": staff_id, "pin": pin}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, staff_id


# ---------------------------------------------------------------------------
# split_order_by_items — service level
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_split_order_by_items_service_moves_items_and_recomputes_totals(
    db_session, restaurant
):
    from app.ordering.service import split_order_by_items

    cust = await _make_customer(db_session, restaurant)
    order, items = await _make_order_with_items(
        db_session,
        restaurant,
        cust,
        items=[
            {"price_aed": Decimal("10.00"), "qty": 1},
            {"price_aed": Decimal("15.00"), "qty": 2},
        ],
    )
    await db_session.commit()

    move_item_id = items[1].id  # qty 2 @ 15.00 = 30.00
    new_order = await split_order_by_items(
        db_session,
        restaurant_id=restaurant.id,
        order_id=order.id,
        item_ids=[move_item_id],
    )
    await db_session.commit()

    await db_session.refresh(order)
    assert new_order.id != order.id
    assert new_order.customer_id == order.customer_id
    assert new_order.total == Decimal("30.00")
    assert order.total == Decimal("10.00")

    moved = await db_session.get(type(items[1]), move_item_id)
    assert moved.order_id == new_order.id


@pytest.mark.anyio
async def test_split_order_by_items_rejects_item_not_on_order(db_session, restaurant):
    from app.ordering.service import split_order_by_items

    cust = await _make_customer(db_session, restaurant)
    order, items = await _make_order_with_items(db_session, restaurant, cust)
    other_order, other_items = await _make_order_with_items(
        db_session, restaurant, cust, status="draft"
    )
    await db_session.commit()

    with pytest.raises(ValueError):
        await split_order_by_items(
            db_session,
            restaurant_id=restaurant.id,
            order_id=order.id,
            item_ids=[other_items[0].id],
        )


@pytest.mark.anyio
async def test_split_order_by_items_rejects_after_ready(db_session, restaurant):
    from app.ordering.service import split_order_by_items

    cust = await _make_customer(db_session, restaurant)
    order, items = await _make_order_with_items(db_session, restaurant, cust, status="ready")
    await db_session.commit()

    with pytest.raises(ValueError):
        await split_order_by_items(
            db_session,
            restaurant_id=restaurant.id,
            order_id=order.id,
            item_ids=[items[0].id],
        )


# ---------------------------------------------------------------------------
# split_order_by_items — router level (manager RBAC)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_split_order_by_items_router_manager_ok(client, auth_headers, db_session):
    restaurant = await _restaurant_by_email(db_session)
    cust = await _make_customer(db_session, restaurant, phone="+971500000901")
    order, items = await _make_order_with_items(
        db_session,
        restaurant,
        cust,
        items=[
            {"price_aed": Decimal("10.00"), "qty": 1},
            {"price_aed": Decimal("20.00"), "qty": 1},
        ],
    )
    await db_session.commit()

    manager_headers, _ = await _manager_staff_headers(client, auth_headers)
    resp = await client.post(
        f"/api/v1/orders/{order.id}/split-by-items",
        json={"item_ids": [items[1].id]},
        headers=manager_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_aed"] == "20.00"


@pytest.mark.anyio
async def test_split_order_by_items_router_non_manager_forbidden(
    client, auth_headers, db_session
):
    restaurant = await _restaurant_by_email(db_session)
    cust = await _make_customer(db_session, restaurant, phone="+971500000902")
    order, items = await _make_order_with_items(db_session, restaurant, cust)
    await db_session.commit()

    cashier_headers, _ = await _cashier_staff_headers(client, auth_headers)
    resp = await client.post(
        f"/api/v1/orders/{order.id}/split-by-items",
        json={"item_ids": [items[0].id]},
        headers=cashier_headers,
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# split_order_by_seat — service level
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_split_order_by_seat_service(db_session, restaurant):
    from app.ordering.service import split_order_by_seat

    cust = await _make_customer(db_session, restaurant, phone="+971500000903")
    order, items = await _make_order_with_items(
        db_session,
        restaurant,
        cust,
        items=[
            {"price_aed": Decimal("12.00"), "qty": 1, "seat_number": 1},
            {"price_aed": Decimal("8.00"), "qty": 1, "seat_number": 2},
            {"price_aed": Decimal("5.00"), "qty": 1, "seat_number": None},
        ],
    )
    await db_session.commit()

    new_order = await split_order_by_seat(
        db_session, restaurant_id=restaurant.id, order_id=order.id, seat_number=1
    )
    await db_session.commit()

    await db_session.refresh(order)
    assert new_order.total == Decimal("12.00")
    assert order.total == Decimal("13.00")  # seat 2 + unassigned


@pytest.mark.anyio
async def test_split_order_by_seat_no_items_raises(db_session, restaurant):
    from app.ordering.service import split_order_by_seat

    cust = await _make_customer(db_session, restaurant, phone="+971500000904")
    order, items = await _make_order_with_items(
        db_session, restaurant, cust, items=[{"price_aed": Decimal("10.00"), "seat_number": 1}]
    )
    await db_session.commit()

    with pytest.raises(ValueError):
        await split_order_by_seat(
            db_session, restaurant_id=restaurant.id, order_id=order.id, seat_number=99
        )


# ---------------------------------------------------------------------------
# split_order_by_seat — router level
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_split_order_by_seat_router_manager_ok(client, auth_headers, db_session):
    restaurant = await _restaurant_by_email(db_session)
    cust = await _make_customer(db_session, restaurant, phone="+971500000905")
    order, items = await _make_order_with_items(
        db_session,
        restaurant,
        cust,
        items=[
            {"price_aed": Decimal("12.00"), "seat_number": 1},
            {"price_aed": Decimal("8.00"), "seat_number": 2},
        ],
    )
    await db_session.commit()

    manager_headers, _ = await _manager_staff_headers(
        client, auth_headers, name="Manager Rana", pin="7771"
    )
    resp = await client.post(
        f"/api/v1/orders/{order.id}/split-by-seat",
        json={"seat_number": 2},
        headers=manager_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["total_aed"] == "8.00"


@pytest.mark.anyio
async def test_split_order_by_seat_router_non_manager_forbidden(
    client, auth_headers, db_session
):
    restaurant = await _restaurant_by_email(db_session)
    cust = await _make_customer(db_session, restaurant, phone="+971500000906")
    order, items = await _make_order_with_items(
        db_session, restaurant, cust, items=[{"price_aed": Decimal("10.00"), "seat_number": 1}]
    )
    await db_session.commit()

    cashier_headers, _ = await _cashier_staff_headers(
        client, auth_headers, name="Cashier Omar", pin="8881"
    )
    resp = await client.post(
        f"/api/v1/orders/{order.id}/split-by-seat",
        json={"seat_number": 1},
        headers=cashier_headers,
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# merge_orders — service level
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_merge_orders_service_moves_items_and_cancels_secondary(db_session, restaurant):
    from app.ordering.service import merge_orders

    cust = await _make_customer(db_session, restaurant, phone="+971500000907")
    primary, primary_items = await _make_order_with_items(
        db_session, restaurant, cust, items=[{"price_aed": Decimal("10.00"), "qty": 1}]
    )
    secondary, secondary_items = await _make_order_with_items(
        db_session, restaurant, cust, items=[{"price_aed": Decimal("20.00"), "qty": 1}]
    )
    await db_session.commit()

    merged = await merge_orders(
        db_session,
        restaurant_id=restaurant.id,
        primary_order_id=primary.id,
        secondary_order_id=secondary.id,
    )
    await db_session.commit()

    await db_session.refresh(primary)
    await db_session.refresh(secondary)
    assert merged.id == primary.id
    assert primary.total == Decimal("30.00")
    assert secondary.status == "cancelled"

    moved = await db_session.get(type(secondary_items[0]), secondary_items[0].id)
    assert moved.order_id == primary.id


@pytest.mark.anyio
async def test_merge_orders_rejects_non_mergeable_status(db_session, restaurant):
    from app.ordering.service import merge_orders

    cust = await _make_customer(db_session, restaurant, phone="+971500000908")
    primary, _ = await _make_order_with_items(db_session, restaurant, cust, status="draft")
    secondary, _ = await _make_order_with_items(db_session, restaurant, cust, status="ready")
    await db_session.commit()

    with pytest.raises(ValueError):
        await merge_orders(
            db_session,
            restaurant_id=restaurant.id,
            primary_order_id=primary.id,
            secondary_order_id=secondary.id,
        )


@pytest.mark.anyio
async def test_merge_orders_rejects_self_merge(db_session, restaurant):
    from app.ordering.service import merge_orders

    cust = await _make_customer(db_session, restaurant, phone="+971500000909")
    order, _ = await _make_order_with_items(db_session, restaurant, cust)
    await db_session.commit()

    with pytest.raises(ValueError):
        await merge_orders(
            db_session,
            restaurant_id=restaurant.id,
            primary_order_id=order.id,
            secondary_order_id=order.id,
        )


# ---------------------------------------------------------------------------
# merge_orders — router level
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_merge_orders_router(client, auth_headers, db_session):
    restaurant = await _restaurant_by_email(db_session)
    cust = await _make_customer(db_session, restaurant, phone="+971500000910")
    primary, _ = await _make_order_with_items(
        db_session, restaurant, cust, items=[{"price_aed": Decimal("10.00"), "qty": 1}]
    )
    secondary, _ = await _make_order_with_items(
        db_session, restaurant, cust, items=[{"price_aed": Decimal("5.00"), "qty": 1}]
    )
    await db_session.commit()

    resp = await client.post(
        "/api/v1/orders/merge",
        json={"primary_order_id": primary.id, "secondary_order_id": secondary.id},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["total_aed"] == "15.00"


@pytest.mark.anyio
async def test_merge_orders_router_bad_status_422(client, auth_headers, db_session):
    restaurant = await _restaurant_by_email(db_session)
    cust = await _make_customer(db_session, restaurant, phone="+971500000911")
    primary, _ = await _make_order_with_items(db_session, restaurant, cust, status="draft")
    secondary, _ = await _make_order_with_items(db_session, restaurant, cust, status="delivered")
    await db_session.commit()

    resp = await client.post(
        "/api/v1/orders/merge",
        json={"primary_order_id": primary.id, "secondary_order_id": secondary.id},
        headers=auth_headers,
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# transfer_order_staff — service level
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_transfer_order_staff_service(db_session, restaurant):
    from app.ordering.service import transfer_order_staff
    from app.staff.models import StaffMember

    cust = await _make_customer(db_session, restaurant, phone="+971500000912")
    order, _ = await _make_order_with_items(db_session, restaurant, cust)
    staff = StaffMember(
        restaurant_id=restaurant.id, name="Server Ali", role="server", pin_hash="x"
    )
    db_session.add(staff)
    await db_session.flush()
    await db_session.commit()

    updated = await transfer_order_staff(
        db_session, restaurant_id=restaurant.id, order_id=order.id, new_staff_id=staff.id
    )
    await db_session.commit()

    assert updated.staff_id == staff.id

    from app.audit.models import AuditLog

    audit_row = await db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity == "order",
            AuditLog.entity_id == str(order.id),
            AuditLog.action == "order_staff_transferred",
        )
    )
    assert audit_row is not None


@pytest.mark.anyio
async def test_transfer_order_staff_rejects_foreign_staff(db_session, restaurant):
    from app.identity.models import Restaurant
    from app.ordering.service import transfer_order_staff
    from app.staff.models import StaffMember

    other_restaurant = Restaurant(
        name="Other Restaurant", phone="+97141234000", password_hash="x",
        lat=25.1, lng=55.1,
    )
    db_session.add(other_restaurant)
    await db_session.flush()

    cust = await _make_customer(db_session, restaurant, phone="+971500000913")
    order, _ = await _make_order_with_items(db_session, restaurant, cust)
    foreign_staff = StaffMember(
        restaurant_id=other_restaurant.id, name="Foreign Staff", role="server", pin_hash="x"
    )
    db_session.add(foreign_staff)
    await db_session.flush()
    await db_session.commit()

    with pytest.raises(ValueError):
        await transfer_order_staff(
            db_session,
            restaurant_id=restaurant.id,
            order_id=order.id,
            new_staff_id=foreign_staff.id,
        )


# ---------------------------------------------------------------------------
# transfer_order_staff — router level
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_transfer_order_staff_router(client, auth_headers, db_session):
    restaurant = await _restaurant_by_email(db_session)
    cust = await _make_customer(db_session, restaurant, phone="+971500000914")
    order, _ = await _make_order_with_items(db_session, restaurant, cust)
    await db_session.commit()

    staff_resp = await client.post(
        "/api/v1/staff",
        json={"name": "Server Huda", "role": "server", "pin": "9999"},
        headers=auth_headers,
    )
    staff_id = staff_resp.json()["id"]

    resp = await client.patch(
        f"/api/v1/orders/{order.id}/transfer-staff",
        json={"staff_id": staff_id},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
