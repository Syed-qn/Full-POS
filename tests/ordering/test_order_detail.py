# tests/ordering/test_order_detail.py
from datetime import timedelta
from decimal import Decimal

import pytest

from app.ordering.detail_schemas import OrderDetailOut
from app.ordering.models import Customer, CustomerAddress, Order, OrderItem
from app.ordering.service import get_order_detail


async def _seed_full_order(db_session, restaurant_id):
    """Seed: menu + customer + address + confirmed order with one item."""
    from app.menu.models import Dish, Menu

    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()

    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=110,
        name="Chicken Biryani", price_aed=Decimal("22.00"),
        category="Rice", is_available=True,
    )
    db_session.add(dish)
    await db_session.flush()

    customer = Customer(
        restaurant_id=restaurant_id, phone="+971501112233",
        name="Sara Al Rashid", total_orders=1,
        total_spend=Decimal("22.00"),
    )
    db_session.add(customer)
    await db_session.flush()

    addr = CustomerAddress(
        customer_id=customer.id, room_apartment="Apt 404",
        building="Marina Tower", receiver_name="Sara Al Rashid",
        confirmed=True,
    )
    db_session.add(addr)
    await db_session.flush()

    order = Order(
        restaurant_id=restaurant_id, customer_id=customer.id,
        order_number="R1-0099", status="delivered",
        address_id=addr.id, subtotal=Decimal("22.00"),
        delivery_fee_aed=Decimal("0.00"), total=Decimal("22.00"),
    )
    db_session.add(order)
    await db_session.flush()

    item = OrderItem(
        order_id=order.id, dish_id=dish.id, dish_number=110,
        dish_name="Chicken Biryani", price_aed=Decimal("22.00"), qty=1,
    )
    db_session.add(item)
    await db_session.commit()
    return order, customer, addr


async def test_get_order_detail_returns_correct_shape(db_session, restaurant):
    order, customer, addr = await _seed_full_order(db_session, restaurant.id)

    detail = await get_order_detail(db_session, restaurant_id=restaurant.id, order_id=order.id)

    assert isinstance(detail, OrderDetailOut)
    assert detail.order_number == "R1-0099"
    assert detail.status == "delivered"
    assert len(detail.items) == 1
    assert detail.items[0].dish_number == 110
    assert detail.items[0].dish_name == "Chicken Biryani"
    assert detail.items[0].line_total == Decimal("22.00")
    assert detail.customer.name == "Sara Al Rashid"
    assert detail.customer.phone == "+971501112233"
    assert detail.address is not None
    assert detail.address.room_apartment == "Apt 404"
    assert detail.address.building == "Marina Tower"


async def test_get_order_detail_no_rider_returns_null(db_session, restaurant):
    order, _, _ = await _seed_full_order(db_session, restaurant.id)

    detail = await get_order_detail(db_session, restaurant_id=restaurant.id, order_id=order.id)

    assert detail.rider is None
    assert detail.route == []


async def test_get_order_detail_timeline_from_audit_log(db_session, restaurant):
    from app.audit.service import record_audit

    order, _, _ = await _seed_full_order(db_session, restaurant.id)
    await record_audit(
        db_session, actor="manager", restaurant_id=restaurant.id,
        entity="order", entity_id=str(order.id),
        action="status_change", after={"status": "confirmed"},
    )
    await db_session.commit()

    detail = await get_order_detail(db_session, restaurant_id=restaurant.id, order_id=order.id)

    assert len(detail.timeline) >= 1
    assert detail.timeline[0].action == "status_change"
    assert detail.timeline[0].actor == "manager"
    # ts must be timezone-aware (UTC) so the dashboard converts to Asia/Dubai
    # instead of rendering naive-UTC as browser-local time.
    assert detail.timeline[0].ts.tzinfo is not None
    assert detail.timeline[0].ts.utcoffset() == timedelta(0)


async def test_get_order_detail_chat_from_conversation(db_session, restaurant):
    from app.conversation.models import Conversation, Message

    order, customer, _ = await _seed_full_order(db_session, restaurant.id)

    conv = Conversation(
        restaurant_id=restaurant.id, phone=customer.phone,
        counterpart="customer", state={},
    )
    db_session.add(conv)
    await db_session.flush()

    db_session.add(Message(
        conversation_id=conv.id, direction="inbound",
        type="text", payload={"text": "I want biryani"}, ts=1717660800,
    ))
    # Outbound bot replies store the text under "body" (not "text") — the order
    # Chat must still render it, not the "[automated]" placeholder.
    db_session.add(Message(
        conversation_id=conv.id, direction="outbound",
        type="text", payload={"body": "Added 1x Chicken Biryani!"}, ts=1717660810,
    ))
    await db_session.commit()

    detail = await get_order_detail(db_session, restaurant_id=restaurant.id, order_id=order.id)

    assert len(detail.chat) == 2
    assert detail.chat[0].direction == "inbound"
    assert detail.chat[0].text == "I want biryani"
    assert detail.chat[1].direction == "outbound"
    assert detail.chat[1].text == "Added 1x Chicken Biryani!"


async def test_get_order_detail_no_conversation_returns_empty_chat(db_session, restaurant):
    order, _, _ = await _seed_full_order(db_session, restaurant.id)

    detail = await get_order_detail(db_session, restaurant_id=restaurant.id, order_id=order.id)

    assert detail.chat == []


async def test_get_order_detail_marketing_opted_in_flag(db_session, restaurant):
    from app.marketing.optout import record_opt_out

    order, customer, _ = await _seed_full_order(db_session, restaurant.id)
    await record_opt_out(db_session, restaurant_id=restaurant.id, phone=customer.phone)
    await db_session.commit()

    detail = await get_order_detail(db_session, restaurant_id=restaurant.id, order_id=order.id)

    assert detail.customer.marketing_opted_in is False


async def test_get_order_detail_wrong_tenant_raises(db_session, restaurant):
    order, _, _ = await _seed_full_order(db_session, restaurant.id)

    with pytest.raises(ValueError, match="Order not found"):
        await get_order_detail(db_session, restaurant_id=99999, order_id=order.id)


async def test_get_order_detail_unknown_id_raises(db_session, restaurant):
    with pytest.raises(ValueError, match="Order not found"):
        await get_order_detail(db_session, restaurant_id=restaurant.id, order_id=99999)


async def test_get_order_detail_route_from_rider_pings(db_session, restaurant):
    from datetime import datetime, timezone

    from app.dispatch.models import Assignment, RiderLocation
    from app.identity.models import Rider

    order, _, _ = await _seed_full_order(db_session, restaurant.id)

    # Seed a rider
    rider = Rider(
        restaurant_id=restaurant.id, name="Ahmed Hassan",
        phone="+971501999888", status="available", performance={},
    )
    db_session.add(rider)
    await db_session.flush()

    # Assign rider to order — use a past timestamp so pings fall before datetime.now()
    assigned_at = datetime(2026, 6, 9, 9, 35, tzinfo=timezone.utc)
    assignment = Assignment(
        order_id=order.id, rider_id=rider.id,
        assigned_at=assigned_at,
    )
    db_session.add(assignment)
    order.rider_id = rider.id

    # Seed GPS pings — both after assigned_at and before now (yesterday)
    db_session.add(RiderLocation(
        rider_id=rider.id, restaurant_id=restaurant.id,
        latitude=25.201, longitude=55.271,
        ts=datetime(2026, 6, 9, 9, 36, tzinfo=timezone.utc),
    ))
    db_session.add(RiderLocation(
        rider_id=rider.id, restaurant_id=restaurant.id,
        latitude=25.205, longitude=55.275,
        ts=datetime(2026, 6, 9, 9, 37, tzinfo=timezone.utc),
    ))
    await db_session.commit()

    detail = await get_order_detail(db_session, restaurant_id=restaurant.id, order_id=order.id)

    assert len(detail.route) == 2
    assert detail.route[0].latitude == 25.201
    assert detail.route[1].latitude == 25.205


# ---------------------------------------------------------------------------
# Helpers for API tests
# ---------------------------------------------------------------------------

def _token(restaurant_id: int) -> str:
    from app.identity.auth import create_access_token
    return create_access_token(restaurant_id=restaurant_id)


def _auth(restaurant_id: int) -> dict:
    return {"Authorization": f"Bearer {_token(restaurant_id)}"}


# ---------------------------------------------------------------------------
# API tests — GET /api/v1/orders/{id}/detail
# ---------------------------------------------------------------------------

async def test_api_order_detail_returns_200(client, db_session, restaurant):
    order, _, _ = await _seed_full_order(db_session, restaurant.id)

    resp = await client.get(
        f"/api/v1/orders/{order.id}/detail",
        headers=_auth(restaurant.id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["order_number"] == "R1-0099"
    assert data["status"] == "delivered"
    assert len(data["items"]) == 1
    assert data["items"][0]["dish_name"] == "Chicken Biryani"
    assert "customer" in data
    assert "timeline" in data
    assert "chat" in data
    assert "route" in data


async def test_api_order_detail_unknown_id_returns_404(client, db_session, restaurant):
    resp = await client.get(
        "/api/v1/orders/99999/detail",
        headers=_auth(restaurant.id),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# API tests — PATCH /api/v1/ordering/customers/{id}
# ---------------------------------------------------------------------------

async def test_api_patch_customer_name(client, db_session, restaurant):
    order, customer, _ = await _seed_full_order(db_session, restaurant.id)

    resp = await client.patch(
        f"/api/v1/ordering/customers/{customer.id}",
        json={"name": "Updated Name"},
        headers=_auth(restaurant.id),
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"


async def test_api_patch_address(client, db_session, restaurant):
    order, customer, addr = await _seed_full_order(db_session, restaurant.id)

    resp = await client.patch(
        f"/api/v1/ordering/customers/{customer.id}/addresses/{addr.id}",
        json={"building": "New Tower"},
        headers=_auth(restaurant.id),
    )
    assert resp.status_code == 200
    assert resp.json()["building"] == "New Tower"


async def test_api_patch_customer_wrong_id_returns_404(client, db_session, restaurant):
    resp = await client.patch(
        "/api/v1/ordering/customers/99999",
        json={"name": "X"},
        headers=_auth(restaurant.id),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# API tests — POST /api/v1/orders/{id}/reassign
# ---------------------------------------------------------------------------

async def test_api_reassign_unknown_order_returns_404(client, db_session, restaurant):
    resp = await client.post(
        "/api/v1/orders/99999/reassign",
        json={"rider_id": 1},
        headers=_auth(restaurant.id),
    )
    assert resp.status_code == 404


async def test_api_reassign_delivers_notification_to_new_rider(client, db_session, restaurant, monkeypatch):
    """Reassign must actually DELIVER the rider notification (not leave it pending).
    Regression: the endpoint committed the outbox row but never flushed it, so on
    a beat-less deploy the rider got nothing."""
    from sqlalchemy import select

    from app.config import get_settings
    from app.dispatch.models import Batch, BatchOrder
    from app.identity.models import Rider
    from app.outbox.models import OutboxMessage

    monkeypatch.setattr(get_settings(), "outbox_sync_delivery", True)

    r1 = Rider(restaurant_id=restaurant.id, name="R1", phone="+971500000077",
               status="on_delivery", performance={})
    r2 = Rider(restaurant_id=restaurant.id, name="R2", phone="+971500000078",
               status="available", performance={})
    db_session.add_all([r1, r2])
    await db_session.flush()

    customer = Customer(restaurant_id=restaurant.id, phone="+971502223344", name="C",
                        total_orders=0, total_spend=Decimal("0.00"))
    db_session.add(customer)
    await db_session.flush()
    order = Order(restaurant_id=restaurant.id, customer_id=customer.id,
                  order_number="R1-7777", status="assigned", rider_id=r1.id,
                  subtotal=Decimal("10.00"), delivery_fee_aed=Decimal("0.00"), total=Decimal("10.00"))
    db_session.add(order)
    await db_session.flush()
    batch = Batch(restaurant_id=restaurant.id, rider_id=r1.id, status="planned", route={})
    db_session.add(batch)
    await db_session.flush()
    db_session.add(BatchOrder(batch_id=batch.id, order_id=order.id, sequence=1))
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/orders/{order.id}/reassign",
        json={"rider_id": r2.id},
        headers=_auth(restaurant.id),
    )
    assert resp.status_code == 200
    assert resp.json()["rider_name"] == "R2"

    rows = (
        await db_session.execute(
            select(OutboxMessage).where(OutboxMessage.to_phone == r2.phone)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "sent"  # delivered, not left pending


async def test_api_reassign_non_assigned_order_returns_422(client, db_session, restaurant):
    # _seed_full_order creates a delivered order — not reassignable.
    order, _, _ = await _seed_full_order(db_session, restaurant.id)
    from app.identity.models import Rider

    rider = Rider(
        restaurant_id=restaurant.id, name="R", phone="+971500000099",
        status="available", performance={},
    )
    db_session.add(rider)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/orders/{order.id}/reassign",
        json={"rider_id": rider.id},
        headers=_auth(restaurant.id),
    )
    assert resp.status_code == 422
    assert "assigned" in resp.json()["detail"].lower()
