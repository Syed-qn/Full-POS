"""updated_since pull-sync filter on the menu-dishes and order-list endpoints — the
desktop client (Task 8) uses this to only pull rows changed since its last cursor."""
from datetime import datetime, timedelta, timezone

import pytest


@pytest.mark.anyio
async def test_updated_since_filters_out_older_dishes(client, auth_headers, active_menu_with_dish):
    cutoff = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()

    resp = await client.get(
        "/api/v1/menu/dishes", params={"updated_since": cutoff}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json() == []  # existing dish is older than the cutoff, filtered out

    resp_all = await client.get("/api/v1/menu/dishes", headers=auth_headers)
    assert resp_all.status_code == 200
    assert len(resp_all.json()) >= 1  # without the filter, the dish is still there


@pytest.mark.anyio
async def test_updated_since_filters_out_older_orders(db_session, restaurant):
    """Service-level check (mirrors tests/ordering/test_manual_order.py's direct-model
    style) — avoids depending on the manual-order HTTP flow's geocoding for a filter
    that only touches the SELECT's WHERE clause."""
    from app.ordering.models import Customer, Order
    from app.ordering.service import list_orders_for_tenant

    customer = Customer(restaurant_id=restaurant.id, phone="+971501111111", name="Ali")
    db_session.add(customer)
    await db_session.flush()
    db_session.add(
        Order(
            restaurant_id=restaurant.id,
            customer_id=customer.id,
            order_number="R1-0001",
            status="draft",
        )
    )
    await db_session.commit()

    cutoff = datetime.now(timezone.utc) + timedelta(seconds=1)

    filtered = await list_orders_for_tenant(
        db_session, restaurant_id=restaurant.id, updated_since=cutoff
    )
    assert filtered == []  # existing order is older than the cutoff, filtered out

    unfiltered = await list_orders_for_tenant(db_session, restaurant_id=restaurant.id)
    assert len(unfiltered) >= 1  # without the filter, the order is still there
