"""Phase 1: orders OUT to POS (webhook + poll + ack)."""
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.identity.models import Restaurant
from app.menu.models import Dish, Menu
from app.ordering.models import Customer, CustomerAddress, Order, OrderItem
from app.partner.integration import apply_partner_settings
from app.partner.orders_api import push_order_to_partner
from app.partner.webhooks.models import PartnerWebhookDelivery
from app.partner.webhooks.dispatch import flush_pending_partner_webhooks

pytestmark = pytest.mark.asyncio


async def _seed_dish(db_session, *, restaurant_id: int) -> Dish:
    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant_id,
        dish_number=110,
        name="Grill Mandi",
        price_aed=Decimal("100.00"),
        category="Main",
        is_available=True,
    )
    db_session.add(dish)
    await db_session.flush()
    return dish


async def _seed_confirmed_order(db_session, *, restaurant_id: int) -> Order:
    dish = await _seed_dish(db_session, restaurant_id=restaurant_id)
    cust = Customer(restaurant_id=restaurant_id, phone="+971500000099", name="Ali")
    db_session.add(cust)
    await db_session.flush()
    addr = CustomerAddress(
        customer_id=cust.id,
        room_apartment="101",
        building="Tower A",
        receiver_name="Ali",
        latitude=25.2,
        longitude=55.3,
        confirmed=True,
    )
    db_session.add(addr)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant_id,
        customer_id=cust.id,
        order_number="R1-0099",
        status="confirmed",
        address_id=addr.id,
        subtotal=Decimal("100.00"),
        delivery_fee_aed=Decimal("10.00"),
        total=Decimal("110.00"),
        sla_confirmed_at=datetime.now(timezone.utc),
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(
        OrderItem(
            order_id=order.id,
            dish_id=dish.id,
            dish_number=110,
            dish_name="Grill Mandi",
            price_aed=Decimal("100.00"),
            qty=1,
        )
    )
    await db_session.commit()
    return order


@pytest.mark.asyncio
async def test_push_order_creates_webhook_row(db_session, auth_headers, client):
    _ = client
    rest = (
        await db_session.scalars(select(Restaurant).where(Restaurant.phone == "+971501234567"))
    ).one()
    apply_partner_settings(
        rest,
        {
            "partner_enabled": True,
            "partner_webhook_url": "https://pos.example.com/hooks",
            "partner_webhook_secret": "sec",
            "pos_store_id": "CRT-1",
        },
    )
    await db_session.commit()
    order = await _seed_confirmed_order(db_session, restaurant_id=rest.id)

    delivery_id = await push_order_to_partner(db_session, order=order)
    await db_session.commit()
    assert delivery_id is not None
    await db_session.refresh(order)
    assert order.pos_push_status == "pending"
    row = await db_session.get(PartnerWebhookDelivery, delivery_id)
    assert row.event_type == "order.created"
    assert row.payload["data"]["order_number"] == "R1-0099"
    assert row.payload["data"]["items"][0]["name"] == "Grill Mandi"

    # Idempotent — second push does nothing.
    again = await push_order_to_partner(db_session, order=order)
    assert again is None


@pytest.mark.asyncio
async def test_finalize_confirmation_triggers_pos_push(db_session, auth_headers, client):
    """finalize_confirmation is the single hook for WhatsApp + manual confirms."""
    from app.ordering.fsm import OrderStatus
    from app.ordering.service import finalize_confirmation

    rest = (
        await db_session.scalars(select(Restaurant).where(Restaurant.phone == "+971501234567"))
    ).one()
    apply_partner_settings(
        rest,
        {
            "partner_enabled": True,
            "partner_webhook_url": "https://pos.example.com/hooks",
            "partner_webhook_secret": "sec",
        },
    )
    dish = await _seed_dish(db_session, restaurant_id=rest.id)
    cust = Customer(restaurant_id=rest.id, phone="+971500000088", name="Sara")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=rest.id,
        customer_id=cust.id,
        order_number="R1-0088",
        status=OrderStatus.PENDING_CONFIRMATION,
        subtotal=Decimal("50.00"),
        delivery_fee_aed=Decimal("0.00"),
        total=Decimal("50.00"),
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(
        OrderItem(
            order_id=order.id,
            dish_id=dish.id,
            dish_number=201,
            dish_name="Soup",
            price_aed=Decimal("50.00"),
            qty=1,
        )
    )
    await db_session.flush()

    await finalize_confirmation(db_session, order=order, actor="customer")
    await db_session.commit()

    assert order.status == "confirmed"
    assert order.pos_push_status == "pending"
    rows = (
        await db_session.scalars(
            select(PartnerWebhookDelivery).where(
                PartnerWebhookDelivery.restaurant_id == rest.id,
                PartnerWebhookDelivery.event_type == "order.created",
            )
        )
    ).all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_partner_poll_and_ack(client, auth_headers, db_session):
    rest = (
        await db_session.scalars(select(Restaurant).where(Restaurant.phone == "+971501234567"))
    ).one()
    order = await _seed_confirmed_order(db_session, restaurant_id=rest.id)
    order.pos_push_status = "pending"
    await db_session.commit()

    key = (await client.post(
        "/api/v1/api-keys", json={"label": "POS"}, headers=auth_headers
    )).json()["api_key"]
    hdr = {"X-API-Key": key}

    listed = await client.get("/api/v1/partner/orders", headers=hdr)
    assert listed.status_code == 200
    nums = {o["order_number"] for o in listed.json()["items"]}
    assert "R1-0099" in nums

    ack = await client.post(
        f"/api/v1/partner/orders/{order.id}/ack",
        headers=hdr,
        json={"pos_order_id": "POS-999"},
    )
    assert ack.status_code == 200
    assert ack.json()["pos_order_id"] == "POS-999"
    assert ack.json()["pos_push_status"] == "acked"

    listed2 = await client.get("/api/v1/partner/orders", headers=hdr)
    nums2 = {o["order_number"] for o in listed2.json()["items"]}
    assert "R1-0099" not in nums2


@pytest.mark.asyncio
async def test_flush_pending_schedules_delivery(db_session, auth_headers):
    _ = auth_headers
    rest = (
        await db_session.scalars(select(Restaurant).where(Restaurant.phone == "+971501234567"))
    ).one()
    apply_partner_settings(
        rest,
        {
            "partner_enabled": True,
            "partner_webhook_url": "https://pos.example.com/hooks",
            "partner_webhook_secret": "sec",
        },
    )
    order = await _seed_confirmed_order(db_session, restaurant_id=rest.id)
    await push_order_to_partner(db_session, order=order)
    await db_session.commit()

    with patch(
        "app.partner.webhooks.dispatch.schedule_partner_webhook_delivery",
        new_callable=AsyncMock,
    ) as mock_sched:
        n = await flush_pending_partner_webhooks(db_session, restaurant_id=rest.id)
    assert n == 1
    mock_sched.assert_awaited_once()