from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.ordering.service import list_orders_for_tenant


@pytest.mark.anyio
async def test_scheduled_only_filters_to_orders_with_scheduled_for(db_session, restaurant):
    from app.ordering.models import Customer, Order

    cust = Customer(restaurant_id=restaurant.id, phone="+971500000880", name="Scheduled Test")
    db_session.add(cust)
    await db_session.flush()
    scheduled = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="SCH-0001",
        status="draft", subtotal=Decimal("30.00"), total=Decimal("30.00"),
        scheduled_for=datetime.now(timezone.utc) + timedelta(hours=3),
    )
    immediate = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="SCH-0002",
        status="draft", subtotal=Decimal("20.00"), total=Decimal("20.00"),
    )
    db_session.add_all([scheduled, immediate])
    await db_session.commit()

    results = await list_orders_for_tenant(db_session, restaurant_id=restaurant.id, scheduled_only=True)
    order_numbers = {o.order_number for o in results}
    assert order_numbers == {"SCH-0001"}
