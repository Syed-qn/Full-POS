"""Phase 2: kitchen status IN from POS → dispatch engine."""
from decimal import Decimal

import pytest

from tests.partner.test_partner_orders import _seed_confirmed_order

pytestmark = pytest.mark.asyncio


async def _api_key(client, auth_headers) -> str:
    return (
        await client.post(
            "/api/v1/api-keys", json={"label": "POS"}, headers=auth_headers
        )
    ).json()["api_key"]


@pytest.mark.asyncio
async def test_pos_preparing_advances_from_confirmed(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant

    rest = (
        await db_session.scalars(select(Restaurant).where(Restaurant.phone == "+971501234567"))
    ).one()
    order = await _seed_confirmed_order(db_session, restaurant_id=rest.id)
    key = await _api_key(client, auth_headers)

    resp = await client.post(
        f"/api/v1/partner/orders/{order.id}/status",
        headers={"X-API-Key": key},
        json={"status": "preparing"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "preparing"
    assert body["rider_assigned"] is False


@pytest.mark.asyncio
async def test_pos_ready_triggers_kitchen_to_ready(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant

    rest = (
        await db_session.scalars(select(Restaurant).where(Restaurant.phone == "+971501234567"))
    ).one()
    order = await _seed_confirmed_order(db_session, restaurant_id=rest.id)
    key = await _api_key(client, auth_headers)

    resp = await client.post(
        f"/api/v1/partner/orders/{order.id}/status",
        headers={"X-API-Key": key},
        json={"status": "ready"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_pos_ready_from_preparing_single_step(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.ordering.models import Order

    rest = (
        await db_session.scalars(select(Restaurant).where(Restaurant.phone == "+971501234567"))
    ).one()
    order = await _seed_confirmed_order(db_session, restaurant_id=rest.id)
    order = await db_session.get(Order, order.id)
    order.status = "preparing"
    await db_session.commit()
    key = await _api_key(client, auth_headers)

    resp = await client.post(
        f"/api/v1/partner/orders/{order.id}/status",
        headers={"X-API-Key": key},
        json={"status": "ready"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_pos_cancel_from_confirmed(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant

    rest = (
        await db_session.scalars(select(Restaurant).where(Restaurant.phone == "+971501234567"))
    ).one()
    order = await _seed_confirmed_order(db_session, restaurant_id=rest.id)
    key = await _api_key(client, auth_headers)

    resp = await client.post(
        f"/api/v1/partner/orders/{order.id}/status",
        headers={"X-API-Key": key},
        json={"status": "cancelled", "reason": "out of stock"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_pos_cannot_advance_delivered_order(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.ordering.models import Order

    rest = (
        await db_session.scalars(select(Restaurant).where(Restaurant.phone == "+971501234567"))
    ).one()
    order = await _seed_confirmed_order(db_session, restaurant_id=rest.id)
    order = await db_session.get(Order, order.id)
    order.status = "delivered"
    order.total = Decimal("110.00")
    await db_session.commit()
    key = await _api_key(client, auth_headers)

    resp = await client.post(
        f"/api/v1/partner/orders/{order.id}/status",
        headers={"X-API-Key": key},
        json={"status": "ready"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_pos_ready_with_available_rider_dispatches_without_error(
    client, auth_headers, db_session
):
    """Regression: when a rider is available, marking READY synchronously
    auto-dispatches and overshoots the order to ASSIGNED. The kitchen-advance
    loop must stop at that point instead of trying to advance an ASSIGNED order
    (which previously raised 'Cannot advance kitchen status from assigned')."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.dispatch.models import RiderLocation
    from app.identity.models import Restaurant, Rider
    from app.ordering.models import Order

    rest = (
        await db_session.scalars(select(Restaurant).where(Restaurant.phone == "+971501234567"))
    ).one()
    rider = Rider(
        restaurant_id=rest.id,
        name="Ahmed",
        phone="+971500000123",
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
    order = await _seed_confirmed_order(db_session, restaurant_id=rest.id)
    order = await db_session.get(Order, order.id)
    order.sla_confirmed_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    order.sla_deadline = order.sla_confirmed_at + timedelta(minutes=40)
    order.promised_eta = order.sla_deadline
    await db_session.commit()
    key = await _api_key(client, auth_headers)

    resp = await client.post(
        f"/api/v1/partner/orders/{order.id}/status",
        headers={"X-API-Key": key},
        json={"status": "ready"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "assigned"
    assert body["rider_assigned"] is True


@pytest.mark.asyncio
async def test_pos_status_survives_notification_failure(client, auth_headers, db_session):
    """Regression: a WhatsApp notification failure in deliver_pending must NOT 500
    the POS kitchen action — the order already transitioned, notifications are
    best-effort. (Prod hit HTTP 500 on 'ready' because deliver_pending raised.)"""
    from unittest.mock import AsyncMock, patch

    from sqlalchemy import select

    from app.identity.models import Restaurant

    rest = (
        await db_session.scalars(select(Restaurant).where(Restaurant.phone == "+971501234567"))
    ).one()
    order = await _seed_confirmed_order(db_session, restaurant_id=rest.id)
    key = await _api_key(client, auth_headers)

    with patch(
        "app.outbox.service.deliver_pending",
        new=AsyncMock(side_effect=RuntimeError("whatsapp send blew up")),
    ):
        resp = await client.post(
            f"/api/v1/partner/orders/{order.id}/status",
            headers={"X-API-Key": key},
            json={"status": "preparing"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "preparing"


@pytest.mark.asyncio
async def test_pos_accepted_is_noop_when_already_confirmed(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant

    rest = (
        await db_session.scalars(select(Restaurant).where(Restaurant.phone == "+971501234567"))
    ).one()
    order = await _seed_confirmed_order(db_session, restaurant_id=rest.id)
    key = await _api_key(client, auth_headers)

    resp = await client.post(
        f"/api/v1/partner/orders/{order.id}/status",
        headers={"X-API-Key": key},
        json={"status": "accepted"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmed"