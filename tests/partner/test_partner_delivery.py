"""Phase 4: delivery status OUT to POS (webhooks + poll)."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.cod.service import record_collection
from app.dispatch.delivery import advance_delivery
from app.dispatch.models import Batch, BatchOrder, RiderLocation
from app.dispatch.service import run_dispatch_engine
from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, CustomerAddress, Order
from app.partner.integration import apply_partner_settings
from app.partner.webhooks.models import PartnerWebhookDelivery
from tests.partner.test_partner_orders import _seed_confirmed_order

pytestmark = pytest.mark.asyncio


async def _seed_restaurant(db_session) -> Restaurant:
    existing = await db_session.scalar(
        select(Restaurant).where(Restaurant.phone == "+971501234567")
    )
    if existing is not None:
        return existing
    rest = Restaurant(
        name="Biryani House",
        phone="+971501234567",
        password_hash="x",
        lat=25.2048,
        lng=55.2708,
        settings={"dispatch_engine": "greedy"},
    )
    db_session.add(rest)
    await db_session.flush()
    return rest


async def _enable_partner(db_session, restaurant: Restaurant) -> None:
    apply_partner_settings(
        restaurant,
        {
            "partner_enabled": True,
            "partner_webhook_url": "https://pos.example.com/hooks",
            "partner_webhook_secret": "sec",
            "pos_store_id": "CRT-1",
        },
    )
    await db_session.commit()


async def _api_key(client, auth_headers) -> str:
    return (
        await client.post(
            "/api/v1/api-keys", json={"label": "POS"}, headers=auth_headers
        )
    ).json()["api_key"]


async def _ready_order_with_address(db_session, *, restaurant_id: int) -> Order:
    order = await _seed_confirmed_order(db_session, restaurant_id=restaurant_id)
    order = await db_session.get(Order, order.id)
    order.status = "ready"
    order.sla_confirmed_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    order.sla_deadline = order.sla_confirmed_at + timedelta(minutes=40)
    order.promised_eta = order.sla_deadline
    await db_session.commit()
    return order


@pytest.mark.asyncio
async def test_manager_cancel_fires_order_cancelled_webhook(db_session):
    from app.ordering.service import cancel_order

    rest = await _seed_restaurant(db_session)
    await _enable_partner(db_session, rest)
    order = await _ready_order_with_address(db_session, restaurant_id=rest.id)
    order = await db_session.get(Order, order.id)
    order.status = "assigned"
    await db_session.commit()

    await cancel_order(db_session, order=order, actor="manager", reason="out of stock")
    await db_session.commit()

    row = await db_session.scalar(
        select(PartnerWebhookDelivery).where(
            PartnerWebhookDelivery.event_type == "order.cancelled",
            PartnerWebhookDelivery.restaurant_id == rest.id,
        )
    )
    assert row is not None
    data = row.payload["data"]
    assert data["order_id"] == order.id
    assert data["status"] == "cancelled"
    assert data["cancelled_by"] == "manager"
    assert data["cancellation_reason"] == "out of stock"


@pytest.mark.asyncio
async def test_dispatch_fires_rider_assigned_webhook(db_session):
    rest = await _seed_restaurant(db_session)
    await _enable_partner(db_session, rest)
    rider = Rider(
        restaurant_id=rest.id,
        name="Ahmed",
        phone="+971500000001",
        status="available",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 5},
    )
    db_session.add(rider)
    await db_session.flush()
    db_session.add(
        RiderLocation(
            rider_id=rider.id,
            restaurant_id=rest.id,
            latitude=25.2048,
            longitude=55.2708,
            ts=datetime.now(timezone.utc),
        )
    )
    order = await _ready_order_with_address(db_session, restaurant_id=rest.id)

    await run_dispatch_engine(db_session, restaurant_id=rest.id)
    await db_session.commit()

    row = await db_session.scalar(
        select(PartnerWebhookDelivery).where(
            PartnerWebhookDelivery.event_type == "order.rider_assigned",
            PartnerWebhookDelivery.restaurant_id == rest.id,
        )
    )
    assert row is not None
    data = row.payload["data"]
    assert data["order_id"] == order.id
    assert data["status"] == "assigned"
    assert data["rider"]["name"] == "Ahmed"


@pytest.mark.asyncio
async def test_picked_up_fires_webhook(db_session):
    rest = await _seed_restaurant(db_session)
    await _enable_partner(db_session, rest)
    order = await _ready_order_with_address(db_session, restaurant_id=rest.id)
    rider = Rider(
        restaurant_id=rest.id,
        name="Omar",
        phone="+971500000002",
        status="on_delivery",
    )
    db_session.add(rider)
    await db_session.flush()
    order.status = "assigned"
    order.rider_id = rider.id
    batch = Batch(restaurant_id=rest.id, rider_id=rider.id, status="planned", route={})
    db_session.add(batch)
    await db_session.flush()
    db_session.add(BatchOrder(batch_id=batch.id, order_id=order.id, sequence=1))
    await db_session.commit()

    await advance_delivery(db_session, order_id=order.id, to_status="picked_up")
    await db_session.commit()

    row = await db_session.scalar(
        select(PartnerWebhookDelivery).where(
            PartnerWebhookDelivery.event_type == "order.picked_up"
        )
    )
    assert row is not None
    assert row.payload["data"]["status"] == "picked_up"


@pytest.mark.asyncio
async def test_delivered_fires_webhook_with_cod(db_session):
    rest = await _seed_restaurant(db_session)
    await _enable_partner(db_session, rest)
    order = await _ready_order_with_address(db_session, restaurant_id=rest.id)
    rider = Rider(
        restaurant_id=rest.id,
        name="Khalid",
        phone="+971500000003",
        status="on_delivery",
    )
    db_session.add(rider)
    await db_session.flush()
    order.status = "picked_up"
    order.rider_id = rider.id
    batch = Batch(restaurant_id=rest.id, rider_id=rider.id, status="picked_up", route={})
    db_session.add(batch)
    await db_session.flush()
    db_session.add(BatchOrder(batch_id=batch.id, order_id=order.id, sequence=1))
    await db_session.commit()

    await advance_delivery(db_session, order_id=order.id, to_status="arriving")
    await advance_delivery(db_session, order_id=order.id, to_status="delivered")
    await record_collection(
        db_session,
        restaurant_id=rest.id,
        order_id=order.id,
        rider_id=rider.id,
        amount=Decimal("110.00"),
    )
    await db_session.commit()

    row = await db_session.scalar(
        select(PartnerWebhookDelivery).where(
            PartnerWebhookDelivery.event_type == "order.delivered"
        )
    )
    assert row is not None
    data = row.payload["data"]
    assert data["status"] == "delivered"
    assert data["cod_collected"] == 110.0
    assert data["delivered_at"] is not None


@pytest.mark.asyncio
async def test_get_delivery_poll_endpoint(client, auth_headers, db_session):
    rest = await _seed_restaurant(db_session)
    await _enable_partner(db_session, rest)
    order = await _ready_order_with_address(db_session, restaurant_id=rest.id)
    rider = Rider(
        restaurant_id=rest.id,
        name="Poll Rider",
        phone="+971500000004",
        status="on_delivery",
    )
    db_session.add(rider)
    await db_session.flush()
    order.status = "assigned"
    order.rider_id = rider.id
    batch = Batch(
        restaurant_id=rest.id,
        rider_id=rider.id,
        status="planned",
        route={},
        total_est_min=18,
    )
    db_session.add(batch)
    await db_session.flush()
    db_session.add(BatchOrder(batch_id=batch.id, order_id=order.id, sequence=1))
    await db_session.commit()

    key = await _api_key(client, auth_headers)
    resp = await client.get(
        f"/api/v1/partner/orders/{order.id}/delivery",
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "assigned"
    assert body["rider"]["name"] == "Poll Rider"
    assert body["batch_id"] == batch.id
    assert body["eta_minutes"] is not None


@pytest.mark.asyncio
async def test_order_late_webhook_on_sla_breach(db_session):
    from app.sla.monitor import _fire_event

    rest = await _seed_restaurant(db_session)
    await _enable_partner(db_session, rest)
    cust = Customer(restaurant_id=rest.id, phone="+971500000055", name="Late")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=rest.id,
        customer_id=cust.id,
        order_number="R1-LATE",
        status="assigned",
        subtotal=Decimal("50.00"),
        delivery_fee_aed=Decimal("0.00"),
        total=Decimal("50.00"),
        sla_confirmed_at=datetime.now(timezone.utc) - timedelta(minutes=45),
        weather_delay_disclosed=False,
    )
    db_session.add(order)
    await db_session.commit()

    now = datetime.now(timezone.utc)
    await _fire_event(db_session, order=order, event_type="breach_40", now=now)
    await db_session.commit()

    row = await db_session.scalar(
        select(PartnerWebhookDelivery).where(
            PartnerWebhookDelivery.event_type == "order.late"
        )
    )
    assert row is not None
    data = row.payload["data"]
    assert data["sla_breach"] is True
    assert data["coupon_code"]
    assert data["coupon_discount_aed"] == 10.0


@pytest.mark.asyncio
async def test_rider_location_endpoint(client, auth_headers, db_session):
    rest = await _seed_restaurant(db_session)
    rider = Rider(
        restaurant_id=rest.id,
        name="GPS Rider",
        phone="+971500000006",
        status="on_delivery",
    )
    db_session.add(rider)
    await db_session.flush()
    ts = datetime.now(timezone.utc)
    db_session.add(
        RiderLocation(
            rider_id=rider.id,
            restaurant_id=rest.id,
            latitude=25.11,
            longitude=55.22,
            ts=ts,
        )
    )
    await db_session.commit()

    key = await _api_key(client, auth_headers)
    resp = await client.get(
        f"/api/v1/partner/riders/{rider.id}/location",
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["latitude"] == 25.11
    assert body["longitude"] == 55.22

    resp2 = await client.get(
        f"/api/v1/partner/riders/{rider.id}/location",
        headers={"X-API-Key": key},
    )
    assert resp2.status_code == 429