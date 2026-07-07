from decimal import Decimal

import pytest

from app.aggregators.mock import MockAggregator
from app.aggregators.service import ingest_inbound_order, reconciliation


@pytest.mark.anyio
async def test_ingest_creates_order_with_aggregator_source(db_session, restaurant):
    payload = {
        "order_id": "TB-99887",
        "customer": {"phone": "+971500000900", "name": "Talabat Guest"},
        "items": [{"name": "Chicken Shawarma", "quantity": 2, "price": "18.00"}],
        "total": "36.00",
    }
    gw = MockAggregator("talabat")

    order = await ingest_inbound_order(db_session, restaurant_id=restaurant.id, provider="talabat", payload=payload, gateway=gw)
    await db_session.commit()

    assert order.aggregator_source == "talabat"
    assert order.aggregator_order_ref == "TB-99887"
    assert order.total == Decimal("36.00")


@pytest.mark.anyio
async def test_ingest_auto_provisions_unknown_dish(db_session, restaurant):
    payload = {
        "order_id": "DL-1",
        "customer": {"phone": "+971500000901", "name": "Deliveroo Guest"},
        "items": [{"name": "Mystery Wrap", "quantity": 1, "price": "22.00"}],
        "total": "22.00",
    }
    gw = MockAggregator("deliveroo")

    order = await ingest_inbound_order(db_session, restaurant_id=restaurant.id, provider="deliveroo", payload=payload, gateway=gw)
    await db_session.commit()

    from sqlalchemy import select

    from app.ordering.models import OrderItem

    items = (await db_session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))).all()
    assert items[0].dish_name == "Mystery Wrap"


@pytest.mark.anyio
async def test_reconciliation_sums_by_provider(db_session, restaurant):
    from datetime import date

    payload1 = {
        "order_id": "TB-1", "customer": {"phone": "+971500000902", "name": "A"},
        "items": [{"name": "Item A", "quantity": 1, "price": "10.00"}], "total": "10.00",
    }
    payload2 = {
        "order_id": "TB-2", "customer": {"phone": "+971500000903", "name": "B"},
        "items": [{"name": "Item B", "quantity": 1, "price": "15.00"}], "total": "15.00",
    }
    gw = MockAggregator("talabat")
    await ingest_inbound_order(db_session, restaurant_id=restaurant.id, provider="talabat", payload=payload1, gateway=gw)
    await db_session.commit()
    await ingest_inbound_order(db_session, restaurant_id=restaurant.id, provider="talabat", payload=payload2, gateway=gw)
    await db_session.commit()

    result = await reconciliation(db_session, restaurant_id=restaurant.id, start_date=date.today(), end_date=date.today())
    assert result["talabat"]["order_count"] == 2
    assert result["talabat"]["revenue_aed"] == Decimal("25.00")
