"""Server-side order list filters (date range, search, offset)."""
from datetime import datetime
from decimal import Decimal

import pytest

from app.ordering.fsm import OrderStatus
from app.ordering.models import Customer, Order
from app.ordering.service import list_orders_for_tenant


def _token_for(restaurant_id: int) -> str:
    from app.identity.auth import create_access_token

    return create_access_token(restaurant_id=restaurant_id)


@pytest.fixture
async def list_customer(db_session, restaurant):
    customer = Customer(
        restaurant_id=restaurant.id,
        phone="+971501230001",
        name="Filter Ali",
        usual_order_times={},
        tags={},
        total_orders=0,
        total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    return customer


async def _seed_order(
    db_session,
    *,
    restaurant_id: int,
    customer_id: int,
    number: str,
    created_at: datetime,
    status: str = OrderStatus.CONFIRMED,
) -> Order:
    order = Order(
        restaurant_id=restaurant_id,
        customer_id=customer_id,
        order_number=number,
        status=status,
        priority="normal",
        weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("10.00"),
        total=Decimal("10.00"),
        created_at=created_at,
    )
    db_session.add(order)
    await db_session.flush()
    return order


@pytest.mark.asyncio
async def test_list_orders_filters_by_dubai_date_range(db_session, restaurant, list_customer):
    # Naive UTC instants that map to Dubai calendar days (UTC+4).
    await _seed_order(
        db_session,
        restaurant_id=restaurant.id,
        customer_id=list_customer.id,
        number="R1-DAY",
        created_at=datetime(2026, 6, 10, 8, 0),
    )
    await _seed_order(
        db_session,
        restaurant_id=restaurant.id,
        customer_id=list_customer.id,
        number="R1-OLD",
        created_at=datetime(2026, 6, 9, 8, 0),
    )
    await _seed_order(
        db_session,
        restaurant_id=restaurant.id,
        customer_id=list_customer.id,
        number="R1-NEW",
        created_at=datetime(2026, 6, 11, 8, 0),
    )
    await db_session.commit()

    rows = await list_orders_for_tenant(
        db_session,
        restaurant_id=restaurant.id,
        from_date="2026-06-10",
        to_date="2026-06-10",
    )
    numbers = {o.order_number for o in rows}
    assert numbers == {"R1-DAY"}


@pytest.mark.asyncio
async def test_list_orders_search_matches_customer_name_and_number(db_session, restaurant, list_customer):
    await _seed_order(
        db_session,
        restaurant_id=restaurant.id,
        customer_id=list_customer.id,
        number="R1-FIND",
        created_at=datetime(2026, 6, 1, 10, 0),
    )
    other = Customer(
        restaurant_id=restaurant.id,
        phone="+971501230099",
        name="Other Person",
        usual_order_times={},
        tags={},
        total_orders=0,
        total_spend=Decimal("0.00"),
    )
    db_session.add(other)
    await db_session.flush()
    await _seed_order(
        db_session,
        restaurant_id=restaurant.id,
        customer_id=other.id,
        number="R1-OTHER",
        created_at=datetime(2026, 6, 1, 11, 0),
    )
    await db_session.commit()

    by_name = await list_orders_for_tenant(
        db_session, restaurant_id=restaurant.id, q="filter ali"
    )
    assert {o.order_number for o in by_name} == {"R1-FIND"}

    by_number = await list_orders_for_tenant(
        db_session, restaurant_id=restaurant.id, q="R1-FIND"
    )
    assert {o.order_number for o in by_number} == {"R1-FIND"}


@pytest.mark.asyncio
async def test_list_orders_offset_skips_rows(db_session, restaurant, list_customer):
    for i in range(3):
        await _seed_order(
            db_session,
            restaurant_id=restaurant.id,
            customer_id=list_customer.id,
            number=f"R1-OFF{i}",
            created_at=datetime(2026, 6, 1, 10 + i, 0),
        )
    await db_session.commit()

    page = await list_orders_for_tenant(
        db_session, restaurant_id=restaurant.id, limit=1, offset=1
    )
    assert len(page) == 1
    assert page[0].order_number == "R1-OFF1"


async def test_api_list_orders_accepts_filter_query_params(client, db_session, restaurant, list_customer):
    await _seed_order(
        db_session,
        restaurant_id=restaurant.id,
        customer_id=list_customer.id,
        number="R1-API",
        created_at=datetime(2026, 6, 15, 5, 0),
        status=OrderStatus.DELIVERED,
    )
    await db_session.commit()

    resp = await client.get(
        "/api/v1/orders",
        params={
            "status": "delivered",
            "from_date": "2026-06-15",
            "to_date": "2026-06-15",
            "q": "R1-API",
            "preview_batch": "false",
        },
        headers={"Authorization": f"Bearer {_token_for(restaurant.id)}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["order_number"] == "R1-API"