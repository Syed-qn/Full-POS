"""Delivery proof photo: rider uploads a photo URL for an in-flight order."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.dispatch.delivery_proof import DeliveryPhotoError, set_delivery_photo
from app.dispatch.models import Batch, BatchOrder
from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, Order


async def _seed(db_session, status="assigned", *, batched=True):
    r = Restaurant(name="R", phone="+9710000000", password_hash="x", lat=25.2, lng=55.2)
    db_session.add(r)
    await db_session.flush()
    rider = Rider(
        restaurant_id=r.id,
        name="X",
        phone="+971500000010",
        status="on_delivery",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0},
    )
    db_session.add(rider)
    await db_session.flush()
    c = Customer(
        restaurant_id=r.id,
        phone="+971501112233",
        name="C",
        usual_order_times={},
        tags={},
        total_orders=0,
        total_spend=Decimal("0.00"),
    )
    db_session.add(c)
    await db_session.flush()
    o = Order(
        restaurant_id=r.id,
        customer_id=c.id,
        order_number="O1",
        status=status,
        priority="normal",
        weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("10.00"),
        total=Decimal("10.00"),
        rider_id=rider.id,
        sla_deadline=datetime.now(timezone.utc) + timedelta(minutes=40),
    )
    db_session.add(o)
    await db_session.flush()
    if batched:
        batch = Batch(restaurant_id=r.id, rider_id=rider.id, status="picked_up", route={"stops": []})
        db_session.add(batch)
        await db_session.flush()
        db_session.add(BatchOrder(batch_id=batch.id, order_id=o.id, sequence=1))
    await db_session.commit()
    return r, rider, o


async def test_set_delivery_photo_on_assigned_order(db_session):
    r, rider, o = await _seed(db_session, status="assigned")
    updated = await set_delivery_photo(
        db_session, restaurant_id=r.id, order_id=o.id, photo_url="https://cdn.example/proof.jpg"
    )
    await db_session.commit()
    await db_session.refresh(o)
    assert updated.id == o.id
    assert o.delivery_photo_url == "https://cdn.example/proof.jpg"


async def test_set_delivery_photo_on_arriving_order(db_session):
    r, rider, o = await _seed(db_session, status="arriving")
    await set_delivery_photo(
        db_session, restaurant_id=r.id, order_id=o.id, photo_url="https://cdn.example/proof2.jpg"
    )
    await db_session.commit()
    await db_session.refresh(o)
    assert o.delivery_photo_url == "https://cdn.example/proof2.jpg"


async def test_set_delivery_photo_rejects_delivered_order(db_session):
    r, rider, o = await _seed(db_session, status="delivered")
    with pytest.raises(DeliveryPhotoError):
        await set_delivery_photo(
            db_session, restaurant_id=r.id, order_id=o.id, photo_url="https://cdn.example/late.jpg"
        )


async def test_set_delivery_photo_rejects_foreign_tenant(db_session):
    r, rider, o = await _seed(db_session, status="assigned")
    with pytest.raises(DeliveryPhotoError):
        await set_delivery_photo(
            db_session, restaurant_id=r.id + 999, order_id=o.id, photo_url="https://cdn.example/x.jpg"
        )


async def test_set_delivery_photo_rejects_missing_order(db_session):
    r, rider, o = await _seed(db_session, status="assigned")
    with pytest.raises(DeliveryPhotoError):
        await set_delivery_photo(
            db_session, restaurant_id=r.id, order_id=999999, photo_url="https://cdn.example/x.jpg"
        )
