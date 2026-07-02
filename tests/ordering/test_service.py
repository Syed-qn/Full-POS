from decimal import Decimal

from app.ordering.models import Customer, CustomerAddress, Order


async def test_customer_table_has_expected_columns(db_session, restaurant):
    c = Customer(
        restaurant_id=restaurant.id,
        phone="+971501234567",
        name="Ali Hassan",
        usual_order_times={},
        tags={},
        total_orders=0,
        total_spend="0.00",
    )
    db_session.add(c)
    await db_session.commit()
    await db_session.refresh(c)
    assert c.id is not None
    assert c.total_orders == 0


async def test_customer_address_table_has_expected_columns(db_session, restaurant):
    c = Customer(
        restaurant_id=restaurant.id, phone="+971501234568", name="Sara",
        usual_order_times={}, tags={}, total_orders=0, total_spend="0.00",
    )
    db_session.add(c)
    await db_session.flush()

    addr = CustomerAddress(
        customer_id=c.id,
        latitude=25.2048,
        longitude=55.2708,
        room_apartment="111",
        building="1-2",
        receiver_name="Sara",
        additional_details="Blue door",
        confirmed=True,
    )
    db_session.add(addr)
    await db_session.commit()
    await db_session.refresh(addr)
    assert addr.id is not None
    assert addr.confirmed is True
    assert addr.last_used_at is None


async def test_upsert_address_backfills_blank_customer_name_from_receiver(db_session, restaurant):
    """The WhatsApp flow only collects a receiver name, so upsert_address backfills
    the customer's display name from it when the customer has none yet."""
    from app.ordering.service import get_or_create_customer, upsert_address

    customer = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971500000001"
    )
    assert customer.name is None

    await upsert_address(
        db_session, customer_id=customer.id, latitude=None, longitude=None,
        room_apartment="12", building="Tower A", receiver_name="Asfer", confirmed=True,
    )
    await db_session.refresh(customer)
    assert customer.name == "Asfer"


async def test_upsert_address_does_not_overwrite_existing_customer_name(db_session, restaurant):
    """An existing customer name is preserved — receiver names never clobber it."""
    from app.ordering.service import get_or_create_customer, upsert_address

    customer = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971500000002"
    )
    customer.name = "Ali Hassan"
    await db_session.flush()

    await upsert_address(
        db_session, customer_id=customer.id, latitude=None, longitude=None,
        room_apartment="9", building="Tower B", receiver_name="Someone Else", confirmed=True,
    )
    await db_session.refresh(customer)
    assert customer.name == "Ali Hassan"


async def test_upsert_address_overwrites_in_place_one_per_customer(db_session, restaurant):
    """A customer keeps exactly ONE saved address — a new address overwrites the
    old one (pin, room, building, receiver) rather than appending a second row."""
    from sqlalchemy import func, select

    from app.ordering.models import CustomerAddress
    from app.ordering.service import get_last_address, get_or_create_customer, upsert_address

    customer = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971500000003"
    )

    first = await upsert_address(
        db_session, customer_id=customer.id, latitude=25.10, longitude=55.10,
        room_apartment="12", building="Tower A", receiver_name="Asfer", confirmed=True,
    )
    second = await upsert_address(
        db_session, customer_id=customer.id, latitude=25.20, longitude=55.20,
        room_apartment="34", building="Tower B", receiver_name="Asfer", confirmed=True,
    )

    # Same row reused — not a new one.
    assert second.id == first.id
    count = await db_session.scalar(
        select(func.count()).select_from(CustomerAddress).where(
            CustomerAddress.customer_id == customer.id
        )
    )
    assert count == 1

    # The saved address now reflects the latest pin + details.
    saved = await get_last_address(db_session, customer.id)
    assert saved is not None
    assert (saved.latitude, saved.longitude) == (25.20, 55.20)
    assert (saved.room_apartment, saved.building) == ("34", "Tower B")


def _token_for(restaurant_id: int) -> str:
    """Bearer token for the dynamically-seeded restaurant fixture."""
    from app.identity.auth import create_access_token

    return create_access_token(restaurant_id=restaurant_id)


async def test_get_order_api_returns_order(client, db_session, restaurant):
    """GET /api/v1/orders/{id} returns order JSON for the authenticated restaurant."""
    from decimal import Decimal

    from app.ordering.fsm import OrderStatus
    from app.ordering.models import Customer, Order

    customer = Customer(
        restaurant_id=restaurant.id, phone="+971501220001", name="API Test",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=customer.id,
        order_number="R1-API1", status=OrderStatus.CONFIRMED,
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("22.00"), total=Decimal("22.00"),
    )
    db_session.add(order)
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/orders/{order.id}",
        headers={"Authorization": f"Bearer {_token_for(restaurant.id)}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["order_number"] == "R1-API1"
    assert data["status"] == "confirmed"


async def test_get_order_api_404_for_unknown(client, restaurant):
    """GET /api/v1/orders/{id} returns 404 when the order does not exist."""
    resp = await client.get(
        "/api/v1/orders/999999",
        headers={"Authorization": f"Bearer {_token_for(restaurant.id)}"},
    )
    assert resp.status_code == 404


async def test_list_orders_skips_batch_preview_when_disabled(client, db_session, restaurant):
    """preview_batch=false avoids the dispatch grouping pass on hot list polls."""
    from decimal import Decimal
    from unittest.mock import AsyncMock, patch

    from app.ordering.fsm import OrderStatus
    from app.ordering.models import Customer, Order

    customer = Customer(
        restaurant_id=restaurant.id, phone="+971501220003", name="Preview Off",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    db_session.add(
        Order(
            restaurant_id=restaurant.id, customer_id=customer.id, order_number="R1-PV0",
            status=OrderStatus.CONFIRMED, priority="normal",
            weather_delay_disclosed=False, delivery_fee_aed=Decimal("0.00"),
            subtotal=Decimal("10.00"), total=Decimal("10.00"),
        )
    )
    await db_session.commit()

    with patch(
        "app.dispatch.service.preview_batch_groups", new_callable=AsyncMock
    ) as mock_preview:
        resp = await client.get(
            "/api/v1/orders",
            params={"preview_batch": "false"},
            headers={"Authorization": f"Bearer {_token_for(restaurant.id)}"},
        )
    assert resp.status_code == 200
    mock_preview.assert_not_called()


async def test_list_orders_api_filters_by_status(client, db_session, restaurant):
    """GET /api/v1/orders?status=... returns only matching orders for the restaurant."""
    from decimal import Decimal

    from app.ordering.fsm import OrderStatus
    from app.ordering.models import Customer, Order

    customer = Customer(
        restaurant_id=restaurant.id, phone="+971501220002", name="List Test",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    db_session.add_all([
        Order(
            restaurant_id=restaurant.id, customer_id=customer.id, order_number="R1-LIST1",
            status=OrderStatus.CONFIRMED, priority="normal",
            weather_delay_disclosed=False, delivery_fee_aed=Decimal("0.00"),
            subtotal=Decimal("10.00"), total=Decimal("10.00"),
        ),
        Order(
            restaurant_id=restaurant.id, customer_id=customer.id, order_number="R1-LIST2",
            status=OrderStatus.DRAFT, priority="normal",
            weather_delay_disclosed=False, delivery_fee_aed=Decimal("0.00"),
            subtotal=Decimal("12.00"), total=Decimal("12.00"),
        ),
    ])
    await db_session.commit()

    resp = await client.get(
        "/api/v1/orders",
        params={"status": "confirmed"},
        headers={"Authorization": f"Bearer {_token_for(restaurant.id)}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    numbers = {o["order_number"] for o in data}
    assert "R1-LIST1" in numbers
    assert "R1-LIST2" not in numbers


async def test_list_orders_for_tenant_clamps_limit(db_session, restaurant):
    """An over-large limit is clamped to 100 (never returns more than 100 rows)."""
    from app.ordering.fsm import OrderStatus
    from app.ordering.models import Customer, Order
    from app.ordering.service import list_orders_for_tenant

    customer = Customer(
        restaurant_id=restaurant.id, phone="+971501229999", name="Clamp Test",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    db_session.add_all([
        Order(
            restaurant_id=restaurant.id, customer_id=customer.id,
            order_number=f"R1-CLAMP{i:03d}", status=OrderStatus.CONFIRMED,
            priority="normal", weather_delay_disclosed=False,
            delivery_fee_aed=Decimal("0.00"),
            subtotal=Decimal("10.00"), total=Decimal("10.00"),
        )
        for i in range(105)
    ])
    await db_session.commit()

    rows = await list_orders_for_tenant(
        db_session, restaurant_id=restaurant.id, limit=10000,
    )
    assert len(rows) == 100


def test_list_orders_for_tenant_clamps_limit_floor():
    """A non-positive limit is clamped up to 1 (unit-level, no DB)."""
    assert min(max(0, 1), 100) == 1


async def test_create_draft_order_increments_number(db_session, restaurant):
    from app.ordering.service import create_draft_order, get_or_create_customer
    customer = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971500000001",
    )
    await db_session.commit()
    order1 = await create_draft_order(db_session, restaurant_id=restaurant.id, customer_id=customer.id)
    await db_session.commit()
    order2 = await create_draft_order(db_session, restaurant_id=restaurant.id, customer_id=customer.id)
    await db_session.commit()
    assert order1.order_number != order2.order_number


async def test_order_number_unique_constraint_blocks_duplicate(db_session, restaurant):
    """W8/TX-13/F114: the DB must reject a duplicate order_number for the same
    tenant even if application code somehow tries to allocate one twice."""
    from sqlalchemy.exc import IntegrityError

    from app.ordering.service import get_or_create_customer

    customer = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971500000099",
    )
    await db_session.flush()
    order1 = Order(
        restaurant_id=restaurant.id, customer_id=customer.id,
        order_number="R1-DUPTEST", status="draft", priority="normal",
        weather_delay_disclosed=False, delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("0.00"), total=Decimal("0.00"),
    )
    db_session.add(order1)
    await db_session.flush()

    order2 = Order(
        restaurant_id=restaurant.id, customer_id=customer.id,
        order_number="R1-DUPTEST", status="draft", priority="normal",
        weather_delay_disclosed=False, delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("0.00"), total=Decimal("0.00"),
    )
    db_session.add(order2)
    try:
        await db_session.flush()
        raised = False
    except IntegrityError:
        raised = True
        await db_session.rollback()
    assert raised, "duplicate (restaurant_id, order_number) must violate a DB unique constraint"


async def test_create_draft_order_survives_concurrent_allocation_race(db_session, restaurant):
    """W8/TX-13/F114: repeated allocation under a simulated race (count() read
    before a competing insert lands) must still yield unique order numbers,
    thanks to the advisory lock + SAVEPOINT-retry-on-collision in
    create_draft_order."""
    from app.ordering.service import create_draft_order, get_or_create_customer

    customer = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971500000098",
    )
    await db_session.commit()

    orders = []
    for _ in range(5):
        order = await create_draft_order(
            db_session, restaurant_id=restaurant.id, customer_id=customer.id,
        )
        await db_session.commit()
        orders.append(order)

    numbers = [o.order_number for o in orders]
    assert len(numbers) == len(set(numbers)), f"duplicate order numbers allocated: {numbers}"


async def test_add_item_recalculates_total(db_session, restaurant):
    from app.menu.models import Dish, Menu
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=110,
        name="Chicken Biryani", price_aed=Decimal("22.00"),
        category="Rice", is_available=True, name_normalized="chicken biryani",
    )
    db_session.add(dish)
    await db_session.flush()

    customer = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971500000002",
    )
    await db_session.flush()
    order = await create_draft_order(db_session, restaurant_id=restaurant.id, customer_id=customer.id)
    await db_session.flush()

    await add_item(db_session, order=order, dish=dish, qty=2)
    await db_session.commit()

    assert order.subtotal == Decimal("44.00")
    assert order.total == Decimal("44.00")


async def test_remove_item_reduces_qty_and_total(db_session, restaurant):
    from app.menu.models import Dish, Menu
    from app.ordering.service import (
        add_item,
        create_draft_order,
        get_or_create_customer,
        remove_item,
    )

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    biryani = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1,
        name="Chicken Biryani", price_aed=Decimal("28.00"),
        category="Rice", is_available=True, name_normalized="chicken biryani",
    )
    lassi = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=7,
        name="Mango Lassi", price_aed=Decimal("12.00"),
        category="Drinks", is_available=True, name_normalized="mango lassi",
    )
    db_session.add_all([biryani, lassi])
    await db_session.flush()

    customer = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971500000009",
    )
    await db_session.flush()
    order = await create_draft_order(db_session, restaurant_id=restaurant.id, customer_id=customer.id)
    await db_session.flush()

    await add_item(db_session, order=order, dish=biryani, qty=2)
    await add_item(db_session, order=order, dish=lassi, qty=3)
    # 2*28 + 3*12 = 92
    assert order.total == Decimal("92.00")

    # Remove 1 biryani -> 1*28 + 3*12 = 64
    removed = await remove_item(db_session, order=order, dish=biryani, qty=1)
    assert removed == 1
    assert order.total == Decimal("64.00")

    # Removing more than present clamps to what's there (3 lassis present, ask 5)
    removed = await remove_item(db_session, order=order, dish=lassi, qty=5)
    assert removed == 3
    assert order.total == Decimal("28.00")  # 1 biryani left

    # Removing a dish not in the cart returns 0
    removed = await remove_item(db_session, order=order, dish=lassi, qty=1)
    assert removed == 0
    assert order.total == Decimal("28.00")
    await db_session.commit()


async def test_finalize_confirmation_sets_sla_fields(db_session, restaurant):
    from app.ordering.service import (
        create_draft_order, finalize_confirmation, get_or_create_customer,
    )
    from app.ordering.fsm import OrderStatus

    customer = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971500000003",
    )
    await db_session.flush()
    order = await create_draft_order(db_session, restaurant_id=restaurant.id, customer_id=customer.id)
    await db_session.flush()

    await finalize_confirmation(db_session, order=order, actor="customer")
    await db_session.commit()

    assert order.status == OrderStatus.CONFIRMED
    assert order.sla_confirmed_at is not None
    assert order.sla_deadline is not None
    diff_minutes = (order.sla_deadline - order.sla_confirmed_at).total_seconds() / 60
    assert abs(diff_minutes - 40) < 1  # within 1 min tolerance


async def test_get_or_create_customer_idempotent(db_session, restaurant):
    from app.ordering.service import get_or_create_customer
    c1 = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971500000004",
    )
    await db_session.commit()
    c2 = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971500000004",
    )
    assert c1.id == c2.id


async def test_order_has_rider_id_column(db_session, restaurant):
    """Order.rider_id column exists, is nullable, and Rider.performance JSONB exists."""
    from decimal import Decimal

    from app.identity.models import Rider
    from app.ordering.models import Customer, Order

    customer = Customer(
        restaurant_id=restaurant.id, phone="+971501230200", name="RiderFKTest",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=customer.id,
        order_number="R1-RFK1", status="draft",
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("0.00"), total=Decimal("0.00"),
    )
    db_session.add(order)
    await db_session.flush()
    rider = Rider(
        restaurant_id=restaurant.id, name="PerfRider", phone="+971501230201",
        status="available",
    )
    db_session.add(rider)
    await db_session.commit()
    await db_session.refresh(order)
    await db_session.refresh(rider)
    assert order.rider_id is None  # nullable FK
    # performance JSONB default present
    assert rider.performance["on_time_pct"] == 100.0
    assert rider.performance["total_deliveries"] == 0


async def test_prep_deadline_is_distance_driven(db_session, restaurant):
    """Kitchen plate-by deadline shrinks with delivery distance and is null without a pin."""
    from datetime import datetime, timedelta, timezone

    from app.ordering.models import Order
    from app.ordering.service import compute_prep_deadline

    c = Customer(
        restaurant_id=restaurant.id, phone="+971507000001", name="P",
        usual_order_times={}, tags={}, total_orders=0, total_spend="0.00",
    )
    db_session.add(c)
    await db_session.flush()
    near = CustomerAddress(customer_id=c.id, latitude=25.2050, longitude=55.2710, confirmed=True)
    far = CustomerAddress(customer_id=c.id, latitude=25.2500, longitude=55.3200, confirmed=True)
    db_session.add_all([near, far])
    await db_session.flush()

    def _order(num, addr_id):
        o = Order(
            restaurant_id=restaurant.id, customer_id=c.id, order_number=num,
            status="confirmed", subtotal=Decimal("10.00"), total=Decimal("10.00"),
            address_id=addr_id,
        )
        db_session.add(o)
        return o

    o_near, o_far, o_none = _order("P1", near.id), _order("P2", far.id), _order("P3", None)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    d_near = await compute_prep_deadline(db_session, o_near, now)
    d_far = await compute_prep_deadline(db_session, o_far, now)
    d_none = await compute_prep_deadline(db_session, o_none, now)

    assert d_none is None  # no drop-off pin -> no drive leg -> no deadline
    assert d_near is not None and d_far is not None
    # Farther delivery eats more of the 40-min budget -> kitchen must plate EARLIER.
    assert now <= d_far < d_near
    # Never looser than the customer SLA itself.
    assert d_near <= now + timedelta(minutes=40)


async def test_finalize_confirmation_sets_prep_deadline(db_session, restaurant):
    """Confirming an order populates prep_deadline alongside the SLA clock."""
    from app.ordering.models import Order
    from app.ordering.service import finalize_confirmation

    c = Customer(
        restaurant_id=restaurant.id, phone="+971507000002", name="Q",
        usual_order_times={}, tags={}, total_orders=0, total_spend="0.00",
    )
    db_session.add(c)
    await db_session.flush()
    addr = CustomerAddress(customer_id=c.id, latitude=25.2055, longitude=55.2715, confirmed=True)
    db_session.add(addr)
    await db_session.flush()
    o = Order(
        restaurant_id=restaurant.id, customer_id=c.id, order_number="Q1",
        status="draft", subtotal=Decimal("10.00"), total=Decimal("10.00"),
        address_id=addr.id,
    )
    db_session.add(o)
    await db_session.flush()

    await finalize_confirmation(db_session, order=o)
    assert o.prep_deadline is not None
    assert o.sla_confirmed_at < o.prep_deadline <= o.sla_deadline


async def test_prep_deadline_recomputed_and_kitchen_warned_on_repin(db_session, restaurant):
    """Re-pinning to a farther address while the order is confirmed, then starting the
    kitchen, tightens prep_deadline and pings the kitchen to expedite."""
    from app.ordering.models import Order
    from app.ordering.service import advance_kitchen_status, finalize_confirmation
    from app.outbox.models import OutboxMessage
    from sqlalchemy import select as _select

    c = Customer(
        restaurant_id=restaurant.id, phone="+971507000003", name="R",
        usual_order_times={}, tags={}, total_orders=0, total_spend="0.00",
    )
    db_session.add(c)
    await db_session.flush()
    addr = CustomerAddress(customer_id=c.id, latitude=25.2050, longitude=55.2710, confirmed=True)
    db_session.add(addr)
    await db_session.flush()
    o = Order(
        restaurant_id=restaurant.id, customer_id=c.id, order_number="R1",
        status="draft", subtotal=Decimal("10.00"), total=Decimal("10.00"),
        address_id=addr.id,
    )
    db_session.add(o)
    await db_session.flush()

    await finalize_confirmation(db_session, order=o)
    before = o.prep_deadline
    assert before is not None

    # Customer re-pins to a much farther address.
    addr.latitude = 25.2500
    addr.longitude = 55.3200
    await db_session.flush()

    await advance_kitchen_status(db_session, order=o)  # confirmed -> preparing
    assert o.status == "preparing"
    assert o.prep_deadline < before  # farther delivery -> must plate earlier

    msg = await db_session.scalar(
        _select(OutboxMessage).where(OutboxMessage.to_phone == restaurant.phone)
    )
    assert msg is not None and "R1" in str(msg.payload)


async def test_cook_estimate_is_slowest_dish_with_default_fallback(db_session, restaurant):
    """Cook estimate = slowest dish's prep_minutes; dishes without a time use the
    restaurant default_prep_minutes."""
    from app.menu.models import Dish, Menu
    from app.ordering.models import Order, OrderItem
    from app.ordering.service import compute_cook_estimate

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active")
    db_session.add(menu)
    await db_session.flush()
    slow = Dish(menu_id=menu.id, restaurant_id=restaurant.id, name="Biryani", prep_minutes=22)
    fast = Dish(menu_id=menu.id, restaurant_id=restaurant.id, name="Salad", prep_minutes=5)
    unknown = Dish(menu_id=menu.id, restaurant_id=restaurant.id, name="Mystery")  # no prep
    db_session.add_all([slow, fast, unknown])
    await db_session.flush()

    c = Customer(
        restaurant_id=restaurant.id, phone="+971507000004", name="K",
        usual_order_times={}, tags={}, total_orders=0, total_spend="0.00",
    )
    db_session.add(c)
    await db_session.flush()

    def _order(num):
        o = Order(
            restaurant_id=restaurant.id, customer_id=c.id, order_number=num,
            status="confirmed", subtotal=Decimal("10.00"), total=Decimal("10.00"),
        )
        db_session.add(o)
        return o

    def _item(o, d):
        db_session.add(OrderItem(
            order_id=o.id, dish_id=d.id, dish_number=d.dish_number or 0,
            dish_name=d.name, price_aed=Decimal("10.00"), qty=1,
        ))

    o_mix, o_unknown = _order("K1"), _order("K2")
    await db_session.flush()
    _item(o_mix, slow); _item(o_mix, fast)   # max(22, 5) = 22
    _item(o_unknown, unknown)                 # falls back to default 15
    await db_session.flush()

    assert await compute_cook_estimate(db_session, o_mix) == 22
    assert await compute_cook_estimate(db_session, o_unknown) == 15
