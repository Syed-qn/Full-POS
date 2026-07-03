"""Partner full lists: rider roster (all riders) and order history (all statuses)."""
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.identity.models import Restaurant, Rider

from tests.partner.test_partner_orders import _seed_confirmed_order

pytestmark = pytest.mark.asyncio


async def _api_key(client, auth_headers) -> str:
    return (
        await client.post(
            "/api/v1/api-keys", json={"label": "POS"}, headers=auth_headers
        )
    ).json()["api_key"]


async def _restaurant(db_session) -> Restaurant:
    return await db_session.scalar(
        select(Restaurant).where(Restaurant.phone == "+971501234567")
    )


async def test_partner_lists_full_rider_roster(client, auth_headers, db_session):
    """Roster returns every rider, incl. idle/off-duty ones (not just on-delivery)."""
    rest = await _restaurant(db_session)
    db_session.add_all([
        Rider(restaurant_id=rest.id, name="Zaid", phone="+971500000101",
              status="available", on_duty=True),
        Rider(restaurant_id=rest.id, name="Amir", phone="+971500000102",
              status="off_shift", on_duty=False,
              performance={"total_deliveries": 42}),
    ])
    await db_session.commit()
    key = await _api_key(client, auth_headers)

    resp = await client.get("/api/v1/partner/riders", headers={"X-API-Key": key})
    assert resp.status_code == 200
    items = resp.json()["items"]
    names = {r["name"]: r for r in items}
    assert "Zaid" in names and "Amir" in names
    # idle/off-duty rider IS present (roster != live-only)
    assert names["Amir"]["on_duty"] is False
    assert names["Amir"]["status"] == "off_shift"
    assert names["Amir"]["total_deliveries"] == 42
    assert names["Zaid"]["on_duty"] is True


async def test_partner_rider_roster_is_tenant_scoped(client, auth_headers, db_session):
    other = Restaurant(
        name="Other", email="o2@example.com", phone="+971509999888",
        password_hash="x", lat=25.2, lng=55.3, settings={},
    )
    db_session.add(other)
    await db_session.flush()
    db_session.add(
        Rider(restaurant_id=other.id, name="Foreign", phone="+971500000103")
    )
    await db_session.commit()
    key = await _api_key(client, auth_headers)

    resp = await client.get("/api/v1/partner/riders", headers={"X-API-Key": key})
    assert resp.status_code == 200
    assert all(r["name"] != "Foreign" for r in resp.json()["items"])


async def test_partner_orders_history_includes_all_statuses(
    client, auth_headers, db_session
):
    """status=all returns delivered/cancelled history, not just active confirmed."""
    from datetime import datetime, timezone

    from app.ordering.models import Order

    rest = await _restaurant(db_session)
    confirmed = await _seed_confirmed_order(db_session, restaurant_id=rest.id)
    # a second order, already delivered — must appear only in the 'all' view
    delivered = Order(
        restaurant_id=rest.id,
        customer_id=confirmed.customer_id,
        order_number="R1-0100",
        status="delivered",
        pos_push_status="acked",
        subtotal=Decimal("50.00"),
        delivery_fee_aed=Decimal("0.00"),
        total=Decimal("50.00"),
        sla_confirmed_at=datetime.now(timezone.utc),
    )
    db_session.add(delivered)
    await db_session.commit()
    await db_session.refresh(delivered)
    key = await _api_key(client, auth_headers)

    # default view (confirmed) → delivered order absent
    default = await client.get(
        "/api/v1/partner/orders", headers={"X-API-Key": key}
    )
    ids_default = {o["order_id"] for o in default.json()["items"]}
    assert confirmed.id in ids_default
    assert delivered.id not in ids_default

    # full history view → both present
    allv = await client.get(
        "/api/v1/partner/orders?status=all&unacked_only=false",
        headers={"X-API-Key": key},
    )
    ids_all = {o["order_id"] for o in allv.json()["items"]}
    assert confirmed.id in ids_all
    assert delivered.id in ids_all
