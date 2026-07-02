"""Order cancellation endpoint (POST /api/v1/orders/{id}/cancel).

Restaurant/manager may cancel through ``arriving``. Pre-cook → cancelled;
restaurant cancel during preparing → cancelled (no resale). Customer cancel during
preparing → on_resale (service tests). Delivered rejects with 422.
"""
from decimal import Decimal

from sqlalchemy import select

from app.menu.models import Dish, Menu
from app.ordering.models import Order


def _token(restaurant_id: int) -> str:
    from app.identity.auth import create_access_token

    return create_access_token(restaurant_id=restaurant_id)


async def _seed_menu(db_session, restaurant_id: int) -> Menu:
    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id,
        dish_number=101, name="Chicken Biryani", price_aed=Decimal("22.00"),
        category="Rice", is_available=True, name_normalized="chicken biryani",
    ))
    await db_session.commit()
    return menu


async def _make_order(db_session, restaurant_id: int, phone: str) -> Order:
    from app.ordering.service import create_manual_order

    menu = await _seed_menu(db_session, restaurant_id)
    dish = await db_session.scalar(select(Dish).where(Dish.menu_id == menu.id))
    order = await create_manual_order(
        db_session,
        restaurant_id=restaurant_id,
        customer_phone=phone,
        customer_name="Test Buyer",
        items=[{"dish_id": dish.id, "qty": 1, "notes": None}],
        apt_room="1A",
        building="Tower",
        receiver_name="Test Buyer",
        address_notes=None,
        delivery_fee_aed=Decimal("0.00"),
    )
    await db_session.commit()
    return order


async def test_cancel_confirmed_order_returns_cancelled(client, db_session, restaurant):
    order = await _make_order(db_session, restaurant.id, "+971509993001")
    assert order.status == "confirmed"

    resp = await client.post(
        f"/api/v1/orders/{order.id}/cancel",
        json={"reason": "customer changed mind"},
        headers={"Authorization": f"Bearer {_token(restaurant.id)}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    await db_session.refresh(order)
    assert order.status == "cancelled"
    assert order.cancelled_at is not None
    assert order.cancellation_reason == "customer changed mind"


async def test_cancel_preparing_via_endpoint_is_cancelled_not_resold(client, db_session, restaurant):
    """The cancel ENDPOINT is restaurant/manager-initiated. A restaurant cancel of a
    cooking order goes to 'cancelled' (food assumed unavailable/unfit) and must NOT be
    resold. Resale is customer-initiated only."""
    order = await _make_order(db_session, restaurant.id, "+971509993002")
    order.status = "preparing"  # already cooking
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/orders/{order.id}/cancel",
        headers={"Authorization": f"Bearer {_token(restaurant.id)}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    # NO resale copy — restaurant cancellation never resells.
    resale = await db_session.scalar(
        select(Order).where(Order.resale_of_order_id == order.id)
    )
    assert resale is None


async def test_cancel_ready_order_returns_cancelled(client, db_session, restaurant):
    order = await _make_order(db_session, restaurant.id, "+971509993003")
    order.status = "ready"
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/orders/{order.id}/cancel",
        headers={"Authorization": f"Bearer {_token(restaurant.id)}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    await db_session.refresh(order)
    assert order.status == "cancelled"


async def test_cancel_assigned_order_releases_rider(client, db_session, restaurant):
    from app.dispatch.models import Batch, BatchOrder
    from app.identity.models import Rider

    order = await _make_order(db_session, restaurant.id, "+971509993005")
    rider = Rider(
        restaurant_id=restaurant.id, name="Rider", phone="+971500000099",
        status="on_delivery", performance={},
    )
    db_session.add(rider)
    await db_session.flush()
    order.status = "assigned"
    order.rider_id = rider.id
    batch = Batch(restaurant_id=restaurant.id, rider_id=rider.id, status="planned", route={})
    db_session.add(batch)
    await db_session.flush()
    db_session.add(BatchOrder(batch_id=batch.id, order_id=order.id, sequence=1))
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/orders/{order.id}/cancel",
        headers={"Authorization": f"Bearer {_token(restaurant.id)}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    await db_session.refresh(order)
    await db_session.refresh(rider)
    assert order.status == "cancelled"
    assert order.rider_id is None
    assert rider.status == "available"


async def test_cancel_arriving_order_returns_cancelled(client, db_session, restaurant):
    order = await _make_order(db_session, restaurant.id, "+971509993006")
    order.status = "arriving"
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/orders/{order.id}/cancel",
        headers={"Authorization": f"Bearer {_token(restaurant.id)}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


async def test_manager_cancel_notifies_customer_and_partner_webhook(
    client, db_session, restaurant
):
    from sqlalchemy import select

    from app.outbox.models import OutboxMessage
    from app.partner.integration import apply_partner_settings
    from app.partner.webhooks.models import PartnerWebhookDelivery

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

    order = await _make_order(db_session, restaurant.id, "+971509993008")
    order.status = "arriving"
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/orders/{order.id}/cancel",
        json={"reason": "kitchen issue"},
        headers={"Authorization": f"Bearer {_token(restaurant.id)}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    outbox = (
        await db_session.scalars(
            select(OutboxMessage).where(
                OutboxMessage.idempotency_key == f"cust-cancelled-{order.id}"
            )
        )
    ).first()
    assert outbox is not None
    assert "cancelled" in (outbox.payload or {}).get("body", "").lower()

    webhook = await db_session.scalar(
        select(PartnerWebhookDelivery).where(
            PartnerWebhookDelivery.restaurant_id == restaurant.id,
            PartnerWebhookDelivery.event_type == "order.cancelled",
        )
    )
    assert webhook is not None
    assert webhook.payload["data"]["order_id"] == order.id
    assert webhook.payload["data"]["status"] == "cancelled"
    assert webhook.payload["data"]["cancellation_reason"] == "kitchen issue"
    assert webhook.payload["data"]["cancelled_by"] == "manager"


async def test_cancel_delivered_order_is_422(client, db_session, restaurant):
    order = await _make_order(db_session, restaurant.id, "+971509993007")
    order.status = "delivered"
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/orders/{order.id}/cancel",
        headers={"Authorization": f"Bearer {_token(restaurant.id)}"},
    )
    assert resp.status_code == 422

    await db_session.refresh(order)
    assert order.status == "delivered"


async def test_cancel_unknown_order_is_404(client, restaurant):
    resp = await client.post(
        "/api/v1/orders/999999/cancel",
        headers={"Authorization": f"Bearer {_token(restaurant.id)}"},
    )
    assert resp.status_code == 404


async def test_cancel_requires_auth(client, db_session, restaurant):
    order = await _make_order(db_session, restaurant.id, "+971509993004")
    resp = await client.post(f"/api/v1/orders/{order.id}/cancel")
    assert resp.status_code == 401
