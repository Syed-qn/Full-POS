"""List orders endpoint must stay within dashboard latency budget."""
import time
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.ordering.fsm import OrderStatus
from app.ordering.models import Customer, Order


def _token_for(restaurant_id: int) -> str:
    from app.identity.auth import create_access_token

    return create_access_token(restaurant_id=restaurant_id)


@pytest.mark.asyncio
async def test_list_orders_p95_under_budget_with_preview_cache(client, db_session, restaurant):
    """50 seeded orders + mocked planner — hot list path stays under 250 ms."""
    customer = Customer(
        restaurant_id=restaurant.id,
        phone="+971501240000",
        name="Perf",
        usual_order_times={},
        tags={},
        total_orders=0,
        total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    db_session.add_all(
        [
            Order(
                restaurant_id=restaurant.id,
                customer_id=customer.id,
                order_number=f"R1-PERF{i:03d}",
                status=OrderStatus.READY,
                priority="normal",
                weather_delay_disclosed=False,
                delivery_fee_aed=Decimal("0.00"),
                subtotal=Decimal("10.00"),
                total=Decimal("10.00"),
            )
            for i in range(50)
        ]
    )
    await db_session.commit()

    headers = {"Authorization": f"Bearer {_token_for(restaurant.id)}"}
    with patch(
        "app.dispatch.service.preview_batch_groups",
        new_callable=AsyncMock,
        return_value={},
    ):
        start = time.perf_counter()
        resp = await client.get("/api/v1/orders", params={"limit": 50}, headers=headers)
        elapsed_ms = (time.perf_counter() - start) * 1000

    assert resp.status_code == 200
    assert len(resp.json()) == 50
    assert elapsed_ms < 250, f"list_orders took {elapsed_ms:.1f}ms"