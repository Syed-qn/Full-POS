"""preview_batch_groups: forecast which still-unassigned orders will batch together
(using the same SLA gate as greedy dispatch) so the order list can flag it BEFORE
a rider is assigned."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.dispatch.batch_plan import labels_from_batches
from app.dispatch.service import (
    _batch_plan_settings_from_restaurant,
    _build_preview_candidates,
    dry_plan_batches,
    preview_batch_groups,
)
from app.geo.factory import get_geo_provider
from app.identity.models import Restaurant, Rider  # noqa: F401 — used in ortools preview test
from app.ordering.models import Customer, CustomerAddress, Order


async def _seed_restaurant(db_session):
    r = Restaurant(
        name="R", phone="+9710000000", password_hash="x", lat=25.2048, lng=55.2708,
        settings={},
    )
    db_session.add(r)
    await db_session.flush()
    return r


async def _order(db_session, restaurant_id, lat, lon, num, *, status="confirmed", rider_id=None):
    c = Customer(
        restaurant_id=restaurant_id, phone=f"+97150{num:07d}", name="C",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(c)
    await db_session.flush()
    addr = CustomerAddress(customer_id=c.id, latitude=lat, longitude=lon, confirmed=True)
    db_session.add(addr)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    o = Order(
        restaurant_id=restaurant_id, customer_id=c.id, order_number=f"O{num}",
        status=status, priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"), subtotal=Decimal("10.00"), total=Decimal("10.00"),
        address_id=addr.id, rider_id=rider_id, sla_confirmed_at=now,
        sla_deadline=now + timedelta(minutes=40), promised_eta=now + timedelta(minutes=40),
    )
    db_session.add(o)
    await db_session.flush()
    return o


async def test_nearby_unassigned_orders_share_a_preview_label(db_session):
    r = await _seed_restaurant(db_session)
    o1 = await _order(db_session, r.id, 25.2000, 55.2700, 1, status="ready")
    o2 = await _order(db_session, r.id, 25.2003, 55.2702, 2, status="ready")  # ~40 m from o1
    far = await _order(db_session, r.id, 25.2600, 55.3300, 3, status="ready")  # several km away
    await db_session.commit()

    groups = await preview_batch_groups(db_session, restaurant_id=r.id)
    assert groups.get(o1.id) is not None
    assert groups[o1.id] == groups[o2.id]      # the two close orders share a batch
    assert far.id not in groups                # a lone order gets no preview label


async def test_assigned_orders_are_excluded_from_preview(db_session):
    r = await _seed_restaurant(db_session)
    rider = Rider(
        restaurant_id=r.id, name="Rider", phone="+971500009999", status="available",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 5},
    )
    db_session.add(rider)
    await db_session.flush()
    # Both nearby, but one is already assigned to a rider → not a preview candidate.
    o1 = await _order(db_session, r.id, 25.2000, 55.2700, 4, status="ready")
    await _order(db_session, r.id, 25.2003, 55.2702, 5, status="assigned", rider_id=rider.id)
    await db_session.commit()

    groups = await preview_batch_groups(db_session, restaurant_id=r.id)
    # o1 has no other UNASSIGNED neighbour → no batch forecast.
    assert o1.id not in groups


async def test_preview_respects_sla_not_just_proximity(db_session):
    """Two nearby orders but one under SLA pressure → no shared preview label."""
    r = await _seed_restaurant(db_session)
    r.settings = {
        "batch_proximity_km": 2.0,
        "sla_buffer_per_order_minutes": 10,
        "dispatch_engine": "greedy",
    }
    db_session.add(r)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    # Order 1: 28 min elapsed — mate would push over 30 internal
    o1 = await _order(db_session, r.id, 25.2000, 55.2700, 10, status="ready")
    o1.sla_confirmed_at = now - timedelta(minutes=28)
    o2 = await _order(db_session, r.id, 25.2003, 55.2702, 11, status="ready")
    o2.sla_confirmed_at = now - timedelta(minutes=28)
    await db_session.commit()

    groups = await preview_batch_groups(db_session, restaurant_id=r.id)
    # SLA gate splits — no batch label for either
    assert o1.id not in groups or o2.id not in groups or groups[o1.id] != groups[o2.id]


async def test_preview_matches_run_batch_plan(db_session):
    r = await _seed_restaurant(db_session)
    await _order(db_session, r.id, 25.2000, 55.2700, 20, status="ready")
    await _order(db_session, r.id, 25.2003, 55.2702, 21, status="ready")
    await db_session.commit()

    preview = await preview_batch_groups(db_session, restaurant_id=r.id)
    candidates = await _build_preview_candidates(db_session, r.id)
    settings = _batch_plan_settings_from_restaurant(r)
    batches = await dry_plan_batches(
        db_session,
        restaurant=r,
        restaurant_id=r.id,
        candidates=candidates,
        settings=settings,
        geo=get_geo_provider(),
        origin=(r.lat, r.lng),
    )
    assert preview == labels_from_batches(batches)


async def test_preview_excludes_preparing_beyond_prep_lead(db_session):
    """Preview pool must match dispatch: preparing only within prep_dispatch_lead_min."""
    from datetime import timedelta

    r = await _seed_restaurant(db_session)
    r.settings = {"prep_dispatch_lead_min": 8, "batch_proximity_km": 2.0}
    db_session.add(r)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    ready = await _order(db_session, r.id, 25.2000, 55.2700, 40, status="ready")
    far_prep = await _order(db_session, r.id, 25.2003, 55.2702, 41, status="preparing")
    far_prep.prep_deadline = now + timedelta(minutes=20)
    near_prep = await _order(db_session, r.id, 25.2001, 55.2701, 42, status="preparing")
    near_prep.prep_deadline = now + timedelta(minutes=5)
    await db_session.commit()

    preview = await preview_batch_groups(db_session, restaurant_id=r.id)
    candidates = await _build_preview_candidates(db_session, r.id)
    candidate_ids = {c.order_id for c in candidates}
    assert ready.id in candidate_ids
    assert near_prep.id in candidate_ids
    assert far_prep.id not in candidate_ids
    if ready.id in preview and near_prep.id in preview:
        assert preview[ready.id] == preview[near_prep.id]
    assert far_prep.id not in preview


async def test_preview_uses_ortools_when_engine_ortools(db_session):
    """Preview labels must follow the OR-Tools dry planner when engine=ortools."""
    r = await _seed_restaurant(db_session)
    r.settings = {"dispatch_engine": "ortools", "batch_proximity_km": 2.0}
    db_session.add(r)
    await db_session.flush()
    rider = Rider(
        restaurant_id=r.id,
        name="R1",
        phone="+971500000001",
        status="available",
        on_duty=True,
        performance={"on_time_pct": 100.0},
    )
    db_session.add(rider)
    await db_session.flush()
    await _order(db_session, r.id, 25.2000, 55.2700, 30, status="ready")
    await _order(db_session, r.id, 25.2003, 55.2702, 31, status="ready")
    await db_session.commit()

    preview = await preview_batch_groups(db_session, restaurant_id=r.id)
    candidates = await _build_preview_candidates(db_session, r.id)
    settings = _batch_plan_settings_from_restaurant(r)
    assert settings.engine == "ortools"
    batches = await dry_plan_batches(
        db_session,
        restaurant=r,
        restaurant_id=r.id,
        candidates=candidates,
        settings=settings,
        geo=get_geo_provider(),
        origin=(r.lat, r.lng),
    )
    assert preview == labels_from_batches(batches)


def _same_group(a: dict[int, str], oid_a: int, oid_b: int) -> bool:
    return a.get(oid_a) is not None and a.get(oid_a) == a.get(oid_b)


async def test_preview_matches_post_dispatch_batch_assignments(db_session):
    """P0: preview labels must match actual batch assignments after dispatch."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.dispatch.models import Batch, BatchOrder, RiderLocation
    from app.dispatch.service import run_dispatch_engine
    from app.identity.models import Rider

    r = await _seed_restaurant(db_session)
    r.settings = {
        "dispatch_engine": "ortools",
        "batch_proximity_km": 2.0,
        "batch_hold_seconds": 0,
        "sla_buffer_per_order_minutes": 10,
    }
    db_session.add(r)
    await db_session.flush()
    rider = Rider(
        restaurant_id=r.id,
        name="R1",
        phone="+971500000099",
        status="available",
        on_duty=True,
        performance={
            "on_time_pct": 100.0,
            "avg_delivery_min": 20,
            "total_deliveries": 0,
        },
    )
    db_session.add(rider)
    await db_session.flush()
    db_session.add(
        RiderLocation(
            rider_id=rider.id,
            restaurant_id=r.id,
            latitude=r.lat,
            longitude=r.lng,
            ts=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()
    o1 = await _order(db_session, r.id, 25.2000, 55.2700, 50, status="ready")
    o2 = await _order(db_session, r.id, 25.2003, 55.2702, 51, status="ready")
    o3 = await _order(db_session, r.id, 25.2600, 55.3300, 52, status="ready")
    await db_session.commit()

    preview = await preview_batch_groups(db_session, restaurant_id=r.id)
    assert _same_group(preview, o1.id, o2.id)
    assert o3.id not in preview

    await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    rows = (
        await db_session.execute(
            select(BatchOrder.order_id, BatchOrder.batch_id)
            .join(Batch, BatchOrder.batch_id == Batch.id)
            .where(Batch.restaurant_id == r.id)
        )
    ).all()
    batch_by_order = {oid: bid for oid, bid in rows}

    for oid_a, label_a in preview.items():
        for oid_b, label_b in preview.items():
            if oid_a >= oid_b:
                continue
            same_preview = label_a == label_b
            same_batch = batch_by_order.get(oid_a) == batch_by_order.get(oid_b)
            assert same_preview == same_batch
