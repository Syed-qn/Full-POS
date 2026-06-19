from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.dispatch.delivery import advance_delivery
from app.dispatch.models import Batch, BatchOrder
from app.identity.auth import create_access_token
from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, CustomerAddress, Order


async def _seed_tracking_order(db_session):
    restaurant = Restaurant(
        name="Track House",
        phone="+971500000001",
        password_hash="x",
        lat=25.2048,
        lng=55.2708,
    )
    db_session.add(restaurant)
    await db_session.flush()

    rider = Rider(
        restaurant_id=restaurant.id,
        name="Ali",
        phone="+971500000099",
        status="on_delivery",
        performance={"on_time_pct": 95.0, "avg_delivery_min": 22, "total_deliveries": 10},
    )
    db_session.add(rider)
    await db_session.flush()

    customer = Customer(
        restaurant_id=restaurant.id,
        phone="+971501234999",
        name="Test Customer",
        usual_order_times={},
        tags={},
        total_orders=1,
        total_spend=Decimal("25.00"),
    )
    db_session.add(customer)
    await db_session.flush()

    addr = CustomerAddress(
        customer_id=customer.id,
        latitude=25.2100,
        longitude=55.2750,
        confirmed=True,
        receiver_name="Test Customer",
    )
    db_session.add(addr)
    await db_session.flush()

    order = Order(
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        order_number="T001",
        status="picked_up",
        priority="normal",
        rider_id=rider.id,
        address_id=addr.id,
        subtotal=Decimal("25.00"),
        delivery_fee_aed=Decimal("5.00"),
        total=Decimal("30.00"),
        weather_delay_disclosed=False,
        sla_deadline=datetime.now(timezone.utc) + timedelta(minutes=40),
    )
    db_session.add(order)
    await db_session.flush()

    batch = Batch(restaurant_id=restaurant.id, rider_id=rider.id, status="picked_up", route={"stops": []})
    db_session.add(batch)
    await db_session.flush()
    db_session.add(BatchOrder(batch_id=batch.id, order_id=order.id, sequence=1))
    await db_session.commit()
    return restaurant, rider, order


async def test_live_tracking_start_update_public_and_stop(client, db_session):
    restaurant, rider, order = await _seed_tracking_order(db_session)
    headers = {"Authorization": f"Bearer {create_access_token(restaurant_id=restaurant.id)}"}

    start = await client.post(
        f"/api/v1/orders/{order.id}/tracking/start",
        headers=headers,
    )
    assert start.status_code == 200
    started = start.json()
    assert started["success"] is True
    assert started["tracking_token"]
    assert started["rider_token"]

    public_before = await client.get(f"/api/v1/track/{started['tracking_token']}")
    assert public_before.status_code == 200
    assert public_before.json()["location"] is None

    update = await client.post(
        f"/api/v1/orders/{order.id}/location",
        headers={"Authorization": f"Bearer {started['rider_token']}"},
        json={
            "latitude": 25.2055,
            "longitude": 55.2750,
            "accuracy": 10,
            "speed": 25,
            "heading": 180,
        },
    )
    assert update.status_code == 200
    assert update.json()["success"] is True

    manager_view = await client.get(
        f"/api/v1/orders/{order.id}/location",
        headers=headers,
    )
    assert manager_view.status_code == 200
    assert manager_view.json()["latitude"] == 25.2055
    assert manager_view.json()["status"] == "picked_up"

    public_view = await client.get(f"/api/v1/track/{started['tracking_token']}/location")
    assert public_view.status_code == 200
    assert public_view.json()["longitude"] == 55.275

    rider_view = await client.get(f"/api/v1/rider-track/{started['rider_token']}")
    assert rider_view.status_code == 200
    assert rider_view.json()["orderId"] == order.id

    stop = await client.post(
        f"/api/v1/orders/{order.id}/tracking/stop",
        headers={"Authorization": f"Bearer {started['rider_token']}"},
    )
    assert stop.status_code == 200

    expired = await client.get(f"/api/v1/track/{started['tracking_token']}")
    assert expired.status_code == 410


async def test_live_tracking_expires_when_order_delivered(client, db_session):
    restaurant, _, order = await _seed_tracking_order(db_session)
    headers = {"Authorization": f"Bearer {create_access_token(restaurant_id=restaurant.id)}"}
    start = await client.post(
        f"/api/v1/orders/{order.id}/tracking/start",
        headers=headers,
    )
    started = start.json()

    await advance_delivery(db_session, order_id=order.id, to_status="arriving")
    await advance_delivery(db_session, order_id=order.id, to_status="delivered")
    await db_session.commit()

    expired = await client.get(f"/api/v1/track/{started['tracking_token']}")
    assert expired.status_code == 410
