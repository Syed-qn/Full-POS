"""Category 7 — delivery management full wiring tests."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest


@pytest.mark.anyio
async def test_zone_fee_overrides_distance_tiers():
    from app.geo.fees import zone_fee_aed
    from app.ordering.fees import calculate_fee

    zones = [
        {
            "name": "Marina",
            "center_lat": 25.08,
            "center_lng": 55.14,
            "radius_km": 2.0,
            "fee_aed": 7.5,
        }
    ]
    # Point inside marina zone
    fee = zone_fee_aed(25.08, 55.14, zones)
    assert fee == Decimal("7.50")
    # calculate_fee with zone kwargs
    z = calculate_fee(
        1.0,
        None,
        drop_lat=25.08,
        drop_lon=55.14,
        restaurant_settings={"delivery_zones": zones},
    )
    assert z == Decimal("7.50")


@pytest.mark.anyio
async def test_manual_assign_ready_order(db_session, restaurant):
    from app.dispatch.service import assign_order
    from app.identity.models import Rider
    from app.ordering.models import Customer, Order

    rider = Rider(
        restaurant_id=restaurant.id,
        name="Manual Rider",
        phone="+971500007701",
        status="available",
        on_duty=True,
        performance={},
    )
    db_session.add(rider)
    cust = Customer(
        restaurant_id=restaurant.id,
        phone="+971500007702",
        name="C",
        total_orders=0,
        total_spend=Decimal("0"),
    )
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number="C7-ASN-1",
        status="ready",
        subtotal=Decimal("40"),
        total=Decimal("40"),
    )
    db_session.add(order)
    await db_session.flush()

    updated = await assign_order(
        db_session,
        restaurant_id=restaurant.id,
        order_id=order.id,
        rider_id=rider.id,
    )
    assert updated.status == "assigned"
    assert updated.rider_id == rider.id
    rider2 = await db_session.get(type(rider), rider.id)
    assert rider2 is not None
    assert rider2.status == "on_delivery"


@pytest.mark.anyio
async def test_cod_reconcile_expected_from_delivered(db_session, restaurant):
    from app.cod.service import reconcile_shift, record_collection
    from app.identity.models import Rider
    from app.ordering.models import Customer, Order

    rider = Rider(
        restaurant_id=restaurant.id,
        name="COD Rider",
        phone="+971500007710",
        status="available",
        on_duty=True,
        performance={},
    )
    db_session.add(rider)
    cust = Customer(
        restaurant_id=restaurant.id,
        phone="+971500007711",
        name="C",
        total_orders=0,
        total_spend=Decimal("0"),
    )
    db_session.add(cust)
    await db_session.flush()
    today = datetime.now(timezone.utc)
    o1 = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number="C7-COD-1",
        status="delivered",
        subtotal=Decimal("30"),
        total=Decimal("30"),
        wallet_applied_aed=Decimal("5"),
        rider_id=rider.id,
        delivered_at=today,
    )
    o2 = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number="C7-COD-2",
        status="delivered",
        subtotal=Decimal("20"),
        total=Decimal("20"),
        rider_id=rider.id,
        delivered_at=today,
    )
    db_session.add_all([o1, o2])
    await db_session.flush()
    # Only collected partial (o1 door due = 25)
    await record_collection(
        db_session,
        restaurant_id=restaurant.id,
        order_id=o1.id,
        rider_id=rider.id,
        amount=Decimal("25.00"),
    )
    rec = await reconcile_shift(
        db_session,
        restaurant_id=restaurant.id,
        rider_id=rider.id,
        shift_date=today.date(),
    )
    # expected = 25 + 20 = 45, collected = 25, variance = -20
    assert rec.expected_total_aed == Decimal("45.00")
    assert rec.collected_total_aed == Decimal("25.00")
    assert rec.variance_aed == Decimal("-20.00")
    assert rec.status == "variance"


@pytest.mark.anyio
async def test_otp_gate_blocks_deliver(db_session, restaurant):
    from app.dispatch.delivery import InvalidTransitionError, advance_delivery
    from app.dispatch.delivery_proof import generate_delivery_otp, verify_delivery_otp
    from app.ordering.models import Customer, Order

    cust = Customer(
        restaurant_id=restaurant.id,
        phone="+971500007720",
        name="C",
        total_orders=0,
        total_spend=Decimal("0"),
    )
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number="C7-OTP-1",
        status="arriving",
        subtotal=Decimal("10"),
        total=Decimal("10"),
        otp_required_at_deliver=True,
    )
    db_session.add(order)
    await db_session.flush()
    otp = await generate_delivery_otp(db_session, order=order)
    with pytest.raises(InvalidTransitionError):
        await advance_delivery(db_session, order_id=order.id, to_status="delivered")
    await verify_delivery_otp(
        db_session, restaurant_id=restaurant.id, order_id=order.id, otp=otp
    )
    done = await advance_delivery(db_session, order_id=order.id, to_status="delivered")
    assert done.status == "delivered"


@pytest.mark.anyio
async def test_category7_http_assign_and_reconcile(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant, Rider
    from app.ordering.models import Customer, Order

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    rider = Rider(
        restaurant_id=restaurant.id,
        name="HTTP Rider",
        phone="+971500007730",
        status="available",
        on_duty=True,
        performance={},
    )
    db_session.add(rider)
    cust = Customer(
        restaurant_id=restaurant.id,
        phone="+971500007731",
        name="HTTP C",
        total_orders=0,
        total_spend=Decimal("0"),
    )
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number="C7-HTTP-1",
        status="ready",
        subtotal=Decimal("15"),
        total=Decimal("15"),
    )
    db_session.add(order)
    await db_session.flush()

    resp = await client.post(
        f"/api/v1/orders/{order.id}/assign",
        headers=auth_headers,
        json={"rider_id": rider.id},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "assigned"

    kpis = await client.get("/api/v1/dispatch/kpis", headers=auth_headers)
    assert kpis.status_code == 200
    assert "avg_delivery_minutes" in kpis.json()

    recon = await client.post(
        f"/api/v1/cod/shift/{rider.id}/reconcile",
        headers=auth_headers,
        json={"shift_date": date.today().isoformat()},
    )
    assert recon.status_code == 200, recon.text
    assert recon.json()["status"] in ("balanced", "variance")
