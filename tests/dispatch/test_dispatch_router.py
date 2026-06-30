"""Tests for dispatch HTTP endpoints (spec §4.3, §5.6)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.dispatch.models import Assignment
from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, CustomerAddress, Order


@pytest.fixture
async def seeded_assignment(db_session, client, auth_headers):
    """Restaurant from auth_headers with one dispatched assignment."""
    r = await db_session.scalar(
        select(Restaurant).where(Restaurant.phone == "+971501234567")
    )
    rd = Rider(
        restaurant_id=r.id,
        name="Rider",
        phone="+971501234568",
        status="available",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0},
    )
    db_session.add(rd)
    await db_session.flush()
    c = Customer(
        restaurant_id=r.id,
        phone="+971501234569",
        name="C",
        usual_order_times={},
        tags={},
        total_orders=0,
        total_spend=Decimal("0.00"),
    )
    db_session.add(c)
    await db_session.flush()
    addr = CustomerAddress(
        customer_id=c.id, latitude=25.2050, longitude=55.2710, confirmed=True
    )
    db_session.add(addr)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    sla_at = now - timedelta(minutes=5)
    o = Order(
        restaurant_id=r.id,
        customer_id=c.id,
        order_number="API1",
        status="ready",
        priority="normal",
        weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("10.00"),
        total=Decimal("10.00"),
        address_id=addr.id,
        sla_confirmed_at=sla_at,
        sla_deadline=sla_at + timedelta(minutes=40),
        promised_eta=sla_at + timedelta(minutes=40),
    )
    db_session.add(o)
    await db_session.flush()
    await db_session.commit()

    resp = await client.post("/api/v1/dispatch/trigger", headers=auth_headers)
    assert resp.status_code == 200
    await db_session.commit()
    return await db_session.scalar(select(Assignment))


async def test_dispatch_trigger_requires_auth(client):
    """Unauthenticated request must be rejected with 401."""
    resp = await client.post("/api/v1/dispatch/trigger")
    assert resp.status_code == 401


async def test_dispatch_trigger_runs_and_returns_ok(client, auth_headers):
    """Authenticated request runs the dispatch engine and returns success."""
    resp = await client.post("/api/v1/dispatch/trigger", headers=auth_headers)
    # Engine runs fine even with no ready orders — returns dispatch summary.
    assert resp.status_code == 200
    body = resp.json()
    assert "assigned" in body
    assert "unassigned" in body
    assert "needs_retry" in body
    # With no ready orders both counts should be zero.
    assert body["assigned"] == 0
    assert body["unassigned"] == 0


async def test_list_assignments_requires_auth(client):
    resp = await client.get("/api/v1/dispatch/assignments")
    assert resp.status_code == 401


async def test_list_assignments_explainability(client, auth_headers, seeded_assignment):
    resp = await client.get("/api/v1/dispatch/assignments", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) >= 1
    assert body[0]["algorithm_score"]["engine"] in ("ortools", "greedy")
    assert "route_sequence" in body[0]["algorithm_score"]
    assert seeded_assignment.order_id == body[0]["order_id"]


async def test_dispatch_kpis_requires_auth(client):
    resp = await client.get("/api/v1/dispatch/kpis")
    assert resp.status_code == 401


async def test_dispatch_kpis_returns_metrics(client, auth_headers, seeded_assignment):
    resp = await client.get("/api/v1/dispatch/kpis", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "batch_rate_pct" in body
    assert "avg_stops" in body
    assert "engine_fallback_pct" in body
    assert body["window"] == "today"


async def test_live_map_requires_auth(client):
    resp = await client.get("/api/v1/dispatch/live-map")
    assert resp.status_code == 401


async def test_live_map_returns_origin_and_rings(client, auth_headers):
    resp = await client.get("/api/v1/dispatch/live-map", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "origin" in body
    assert "batches" in body
    assert "sla_rings" in body
    assert body["origin"]["lat"] is not None


async def test_live_map_includes_active_batch_polyline(
    client, auth_headers, seeded_assignment, db_session
):
    """After dispatch, live-map must expose batch_id, rider_id, and stop coordinates."""
    resp = await client.get("/api/v1/dispatch/live-map", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["batches"]) >= 1
    batch = body["batches"][0]
    assert "batch_id" in batch
    assert "rider_id" in batch
    assert "stops" in batch
    assert len(batch["stops"]) >= 1
    stop = batch["stops"][0]
    assert "order_id" in stop
    assert "lat" in stop
    assert "lng" in stop
    assert "sequence" in stop


async def test_dispatch_kpis_numeric_types(client, auth_headers, seeded_assignment):
    """KPI fields must be numeric (not null strings) when assignments exist."""
    resp = await client.get("/api/v1/dispatch/kpis", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["batch_rate_pct"], (int, float))
    assert isinstance(body["avg_stops"], (int, float))
    assert isinstance(body["engine_fallback_pct"], (int, float))
