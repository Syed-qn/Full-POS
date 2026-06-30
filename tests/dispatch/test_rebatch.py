"""Re-batch FSM tests (spec §5.4, Phase 4).

Planned (assigned, not picked_up) batches may absorb new ready orders via OR-Tools
re-solve. Picked_up batches are immutable. SLA breach projection triggers unbatch +
``batch_split_sla_risk`` audit.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.audit.models import AuditLog
from app.dispatch.models import Batch, BatchOrder
from app.dispatch.service import run_dispatch_engine, sweep_ready_once
from app.identity.models import Rider
from app.ordering.models import Customer, CustomerAddress, Order
from app.ordering.service import advance_kitchen_status
from app.outbox.models import OutboxMessage

# Reuse seed helpers from the dispatch engine test module.
from tests.dispatch.test_dispatch_engine import (
    _ping,
    _ready_order,
    _seed_restaurant,
)


async def _assigned_order(
    db_session,
    restaurant_id,
    lat,
    lon,
    num,
    *,
    minutes_since_sla: int = 5,
    rider_id: int | None = None,
):
    """Seed an assigned (in-flight, not picked_up) order with optional rider."""
    c = Customer(
        restaurant_id=restaurant_id,
        phone=f"+97151{num:07d}",
        name="C",
        usual_order_times={},
        tags={},
        total_orders=0,
        total_spend=Decimal("0.00"),
    )
    db_session.add(c)
    await db_session.flush()
    addr = CustomerAddress(
        customer_id=c.id, latitude=lat, longitude=lon, confirmed=True
    )
    db_session.add(addr)
    await db_session.flush()
    sla_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_since_sla)
    o = Order(
        restaurant_id=restaurant_id,
        customer_id=c.id,
        order_number=f"A{num}",
        status="assigned",
        priority="normal",
        weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("10.00"),
        total=Decimal("10.00"),
        address_id=addr.id,
        rider_id=rider_id,
        sla_confirmed_at=sla_at,
        sla_deadline=sla_at + timedelta(minutes=40),
        promised_eta=sla_at + timedelta(minutes=40),
    )
    db_session.add(o)
    await db_session.flush()
    return o


async def _planned_batch(
    db_session, restaurant_id, rider_id, orders: list[Order]
) -> Batch:
    """Materialise a planned multi-stop batch for pre-seeded assigned orders."""
    batch = Batch(
        restaurant_id=restaurant_id,
        rider_id=rider_id,
        status="planned",
        route={
            "stops": [
                {"order_id": o.id, "lat": 25.2050, "lon": 55.2710} for o in orders
            ]
        },
        total_est_min=25,
    )
    db_session.add(batch)
    await db_session.flush()
    for seq, o in enumerate(orders, start=1):
        db_session.add(
            BatchOrder(batch_id=batch.id, order_id=o.id, sequence=seq)
        )
    return batch


async def test_new_ready_inserts_into_planned_batch(db_session):
    """A new ready order joins an existing planned (assigned, not picked_up) batch."""
    r = await _seed_restaurant(db_session, dispatch_engine="ortools")
    rider = Rider(
        restaurant_id=r.id,
        name="R",
        phone="+971500000301",
        status="on_delivery",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0},
    )
    db_session.add(rider)
    await db_session.flush()
    await _ping(db_session, rider, r.id, 25.2048, 55.2708)

    o1 = await _assigned_order(
        db_session, r.id, 25.2050, 55.2710, 301, minutes_since_sla=5, rider_id=rider.id
    )
    o2 = await _assigned_order(
        db_session, r.id, 25.2052, 55.2712, 302, minutes_since_sla=4, rider_id=rider.id
    )
    await _planned_batch(db_session, r.id, rider.id, [o1, o2])
    await db_session.commit()

    o3 = await _ready_order(db_session, r.id, 25.2054, 55.2714, 303, minutes_since_sla=1)
    await db_session.commit()

    await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    await db_session.refresh(o3)
    bo1 = await db_session.scalar(
        select(BatchOrder).where(BatchOrder.order_id == o1.id)
    )
    bo3 = await db_session.scalar(
        select(BatchOrder).where(BatchOrder.order_id == o3.id)
    )
    assert bo1 is not None and bo3 is not None
    assert bo1.batch_id == bo3.batch_id
    assert o3.status == "assigned"
    assert o3.rider_id == rider.id

    batch = await db_session.get(Batch, bo3.batch_id)
    assert batch is not None
    assert batch.status == "planned"
    stop_count = await db_session.scalar(
        select(func.count(BatchOrder.id)).where(BatchOrder.batch_id == bo3.batch_id)
    )
    assert stop_count == 3


async def test_new_ready_via_kitchen_hook_inserts_into_planned_batch(db_session):
    """advance_kitchen_status(ready) triggers re-solve with movable orders."""
    r = await _seed_restaurant(db_session, dispatch_engine="ortools")
    rider = Rider(
        restaurant_id=r.id,
        name="R",
        phone="+971500000302",
        status="on_delivery",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0},
    )
    db_session.add(rider)
    await db_session.flush()
    await _ping(db_session, rider, r.id, 25.2048, 55.2708)

    o1 = await _assigned_order(
        db_session, r.id, 25.2050, 55.2710, 311, minutes_since_sla=5, rider_id=rider.id
    )
    await _planned_batch(db_session, r.id, rider.id, [o1])

    c = Customer(
        restaurant_id=r.id,
        phone="+971513333333",
        name="C",
        usual_order_times={},
        tags={},
        total_orders=0,
        total_spend=Decimal("0.00"),
    )
    db_session.add(c)
    await db_session.flush()
    addr = CustomerAddress(
        customer_id=c.id, latitude=25.2053, longitude=55.2713, confirmed=True
    )
    db_session.add(addr)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    o_prep = Order(
        restaurant_id=r.id,
        customer_id=c.id,
        order_number="P311",
        status="preparing",
        priority="normal",
        weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("10.00"),
        total=Decimal("10.00"),
        address_id=addr.id,
        sla_confirmed_at=now,
        sla_deadline=now + timedelta(minutes=40),
        promised_eta=now + timedelta(minutes=40),
    )
    db_session.add(o_prep)
    await db_session.commit()

    await advance_kitchen_status(db_session, order=o_prep)
    await db_session.refresh(o_prep)

    assert o_prep.status == "assigned"
    assert o_prep.rider_id == rider.id
    bo = await db_session.scalar(
        select(BatchOrder).where(BatchOrder.order_id == o_prep.id)
    )
    assert bo is not None


async def test_rebatch_noop_after_pickup(db_session):
    """Once a batch is picked_up, new ready orders do not join that run."""
    r = await _seed_restaurant(db_session, dispatch_engine="ortools")
    rider = Rider(
        restaurant_id=r.id,
        name="R",
        phone="+971500000303",
        status="on_delivery",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0},
    )
    db_session.add(rider)
    await db_session.flush()
    await _ping(db_session, rider, r.id, 25.2048, 55.2708)

    o1 = await _assigned_order(
        db_session, r.id, 25.2050, 55.2710, 321, minutes_since_sla=5, rider_id=rider.id
    )
    o1.status = "picked_up"
    batch = Batch(
        restaurant_id=r.id,
        rider_id=rider.id,
        status="picked_up",
        route={"stops": [{"order_id": o1.id, "lat": 25.2050, "lon": 55.2710}]},
    )
    db_session.add(batch)
    await db_session.flush()
    db_session.add(BatchOrder(batch_id=batch.id, order_id=o1.id, sequence=1))
    await db_session.commit()

    o2 = await _ready_order(db_session, r.id, 25.2052, 55.2712, 322, minutes_since_sla=1)
    await db_session.commit()

    await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    await db_session.refresh(o2)
    # No free rider — o2 stays ready (cannot join picked_up batch).
    assert o2.status == "ready"
    assert o2.rider_id is None
    assert (
        await db_session.scalar(
            select(BatchOrder).where(BatchOrder.order_id == o2.id)
        )
    ) is None


async def test_rebatch_splits_when_sla_risk(db_session, monkeypatch):
    """Third insert rejected when it would breach 40-min SLA; audit batch_split_sla_risk."""
    from app.dispatch import service as dispatch_service
    from app.dispatch.optimizer import OptPlan, OptRoute

    def _fake_optimize(**kwargs):
        orders = kwargs["orders"]
        locked = [o for o in orders if o.locked_rider_id is not None]
        ready = [o for o in orders if o.locked_rider_id is None]
        if len(locked) >= 2 and ready:
            rider_id = locked[0].locked_rider_id
            all_ids = [o.order_id for o in locked] + [ready[0].order_id]
            return OptPlan(
                routes=[
                    OptRoute(
                        rider_id=rider_id,
                        order_ids=all_ids,
                        projected_minutes={
                            o.order_id: 38.0 for o in locked
                        }
                        | {ready[0].order_id: 41.0},
                    )
                ],
                unassigned=[],
            )
        from app.dispatch.optimizer import optimize_dispatch as real_optimize

        return real_optimize(**kwargs)

    monkeypatch.setattr(dispatch_service, "optimize_dispatch", _fake_optimize)

    r = await _seed_restaurant(db_session, dispatch_engine="ortools")
    rider = Rider(
        restaurant_id=r.id,
        name="R",
        phone="+971500000304",
        status="on_delivery",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0},
    )
    db_session.add(rider)
    await db_session.flush()
    await _ping(db_session, rider, r.id, 25.2048, 55.2708)

    # Tight pair: solo each is ~39 min, but batched o1→o2 pushes o2 past 40 min.
    o1 = await _assigned_order(
        db_session, r.id, 25.2048, 55.2708, 331, minutes_since_sla=36, rider_id=rider.id
    )
    o2 = await _assigned_order(
        db_session,
        r.id,
        25.2048 + 0.0135,
        55.2708,
        332,
        minutes_since_sla=36,
        rider_id=rider.id,
    )
    await _planned_batch(db_session, r.id, rider.id, [o1, o2])
    await db_session.commit()

    # Nearby ready order would force a re-solve that breaches SLA for the batch.
    o3 = await _ready_order(
        db_session, r.id, 25.2050, 55.2710, 333, minutes_since_sla=1
    )
    await db_session.commit()

    await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    await db_session.refresh(o3)
    bo1 = await db_session.scalar(
        select(BatchOrder).where(BatchOrder.order_id == o1.id)
    )
    bo2 = await db_session.scalar(
        select(BatchOrder).where(BatchOrder.order_id == o2.id)
    )
    bo3 = await db_session.scalar(
        select(BatchOrder).where(BatchOrder.order_id == o3.id)
    )
    # The risky pair must be split — never all three on one multi-stop batch.
    if bo1 and bo2:
        assert bo1.batch_id != bo2.batch_id
    if bo3 is not None and bo1 and bo2:
        batch_ids = {bo1.batch_id, bo2.batch_id, bo3.batch_id}
        for bid in batch_ids:
            cnt = await db_session.scalar(
                select(func.count(BatchOrder.id)).where(BatchOrder.batch_id == bid)
            )
            assert cnt < 3

    audits = (
        await db_session.scalars(
            select(AuditLog).where(AuditLog.action == "batch_split_sla_risk")
        )
    ).all()
    assert audits, "expected batch_split_sla_risk audit when SLA forces unbatch"
    assert any(a.entity == "batch" for a in audits)


async def test_sweep_rebatch_with_movable_orders(db_session, monkeypatch):
    """Periodic sweep re-solves when ready + planned movable orders coexist."""
    from contextlib import asynccontextmanager

    import app.db as db_module

    @asynccontextmanager
    async def _test_session():
        yield db_session

    class _Factory:
        def __call__(self):
            return _test_session()

    factory = _Factory()
    monkeypatch.setattr(db_module, "async_session_factory", factory)
    monkeypatch.setattr(
        "app.dispatch.service.async_session_factory", factory, raising=False
    )

    r = await _seed_restaurant(db_session, dispatch_engine="ortools")
    rider = Rider(
        restaurant_id=r.id,
        name="R",
        phone="+971500000305",
        status="on_delivery",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0},
    )
    db_session.add(rider)
    await db_session.flush()
    await _ping(db_session, rider, r.id, 25.2048, 55.2708)

    o1 = await _assigned_order(
        db_session, r.id, 25.2050, 55.2710, 341, minutes_since_sla=5, rider_id=rider.id
    )
    await _planned_batch(db_session, r.id, rider.id, [o1])
    o2 = await _ready_order(db_session, r.id, 25.2052, 55.2712, 342, minutes_since_sla=1)
    await db_session.commit()

    swept = await sweep_ready_once()
    await db_session.commit()

    assert swept >= 1
    await db_session.refresh(o2)
    assert o2.status == "assigned"
    assert o2.rider_id == rider.id


async def test_resequence_enqueues_customer_eta_update(db_session):
    """Re-sequencing a planned batch notifies the customer when ETA shifts > 5 min."""
    r = await _seed_restaurant(db_session, dispatch_engine="ortools")
    rider = Rider(
        restaurant_id=r.id,
        name="R",
        phone="+971500000306",
        status="on_delivery",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0},
    )
    db_session.add(rider)
    await db_session.flush()
    await _ping(db_session, rider, r.id, 25.2048, 55.2708)

    # Far stop first in batch — adding a nearer ready order should resequence.
    o_far = await _assigned_order(
        db_session,
        r.id,
        25.2048 + 0.009,
        55.2708,
        351,
        minutes_since_sla=10,
        rider_id=rider.id,
    )
    o_far.promised_eta = o_far.sla_confirmed_at + timedelta(minutes=25)
    await _planned_batch(db_session, r.id, rider.id, [o_far])
    await db_session.commit()

    await _ready_order(db_session, r.id, 25.2050, 55.2710, 352, minutes_since_sla=2)
    await db_session.commit()

    await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    customer = await db_session.scalar(
        select(Customer).where(Customer.id == o_far.customer_id)
    )
    msgs = (
        await db_session.scalars(
            select(OutboxMessage).where(OutboxMessage.to_phone == customer.phone)
        )
    ).all()
    bodies = " ".join(str(m.payload.get("body", "")) for m in msgs)
    assert "arriving" in bodies.lower() or "update" in bodies.lower()