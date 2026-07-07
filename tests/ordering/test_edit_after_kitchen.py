import pytest
from sqlalchemy import select

from app.audit.models import AuditLog
from app.ordering.fsm import OrderStatus

from tests.ordering.test_partial_cancel import _order_items, _seed_confirmed_order_two_items


# ---------------------------------------------------------------------------
# Service-level tests
# ---------------------------------------------------------------------------


async def test_edit_order_item_changes_qty_and_recomputes_totals(db_session, restaurant):
    from app.ordering.service import edit_order_item

    order = await _seed_confirmed_order_two_items(db_session, restaurant.id)
    items = await _order_items(db_session, order.id)
    target = items[0]

    updated = await edit_order_item(
        db_session,
        restaurant_id=restaurant.id,
        order_id=order.id,
        order_item_id=target.id,
        new_qty=3,
        new_notes=None,
        actor="manager",
    )
    await db_session.commit()
    await db_session.refresh(order)

    assert updated.qty == 3

    other = [i for i in items if i.id != target.id][0]
    expected_subtotal = target.price_aed * 3 + other.price_aed * other.qty
    assert order.subtotal == expected_subtotal
    assert order.total == expected_subtotal + order.delivery_fee_aed


async def test_edit_order_item_changes_notes_only(db_session, restaurant):
    from app.ordering.service import edit_order_item

    order = await _seed_confirmed_order_two_items(db_session, restaurant.id)
    items = await _order_items(db_session, order.id)
    target = items[0]
    original_total = order.total

    updated = await edit_order_item(
        db_session,
        restaurant_id=restaurant.id,
        order_id=order.id,
        order_item_id=target.id,
        new_qty=None,
        new_notes="no onions",
        actor="manager",
    )
    await db_session.commit()
    await db_session.refresh(order)

    assert updated.notes == "no onions"
    assert order.total == original_total  # unchanged — notes-only edit


async def test_edit_order_item_produces_audit_log(db_session, restaurant):
    from app.ordering.service import edit_order_item

    order = await _seed_confirmed_order_two_items(db_session, restaurant.id)
    items = await _order_items(db_session, order.id)

    await edit_order_item(
        db_session,
        restaurant_id=restaurant.id,
        order_id=order.id,
        order_item_id=items[0].id,
        new_qty=2,
        new_notes=None,
        actor="manager",
    )
    await db_session.commit()

    logs = (await db_session.execute(select(AuditLog))).scalars().all()
    assert any(r.action == "order_item_edited" for r in logs)


async def test_edit_order_item_blocked_at_ready(db_session, restaurant):
    from app.ordering.service import edit_order_item

    order = await _seed_confirmed_order_two_items(db_session, restaurant.id)
    items = await _order_items(db_session, order.id)
    order.status = OrderStatus.READY
    await db_session.commit()

    with pytest.raises(ValueError, match="not allowed"):
        await edit_order_item(
            db_session,
            restaurant_id=restaurant.id,
            order_id=order.id,
            order_item_id=items[0].id,
            new_qty=2,
            new_notes=None,
            actor="manager",
        )


async def test_edit_order_item_rejects_non_positive_qty(db_session, restaurant):
    from app.ordering.service import edit_order_item

    order = await _seed_confirmed_order_two_items(db_session, restaurant.id)
    items = await _order_items(db_session, order.id)

    with pytest.raises(ValueError, match="[Qq]uantity"):
        await edit_order_item(
            db_session,
            restaurant_id=restaurant.id,
            order_id=order.id,
            order_item_id=items[0].id,
            new_qty=0,
            new_notes=None,
            actor="manager",
        )


# ---------------------------------------------------------------------------
# Router-level tests (RBAC)
# ---------------------------------------------------------------------------


async def test_non_manager_staff_cannot_edit_order_item(client, auth_headers, db_session):
    from app.identity.models import Restaurant

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    order = await _seed_confirmed_order_two_items(db_session, restaurant.id)
    items = await _order_items(db_session, order.id)

    staff_resp = await client.post(
        "/api/v1/staff", json={"name": "Cashier Nour", "role": "cashier", "pin": "9876"},
        headers=auth_headers,
    )
    staff_id = staff_resp.json()["id"]
    login = await client.post("/api/v1/staff/login", json={"staff_id": staff_id, "pin": "9876"})
    staff_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.patch(
        f"/api/v1/orders/{order.id}/items/{items[0].id}",
        json={"qty": 2},
        headers=staff_headers,
    )
    assert resp.status_code == 403


async def test_manager_role_staff_can_edit_order_item(client, auth_headers, db_session):
    from app.identity.models import Restaurant

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    order = await _seed_confirmed_order_two_items(db_session, restaurant.id)
    items = await _order_items(db_session, order.id)

    staff_resp = await client.post(
        "/api/v1/staff", json={"name": "Manager Fatima", "role": "manager", "pin": "6789"},
        headers=auth_headers,
    )
    staff_id = staff_resp.json()["id"]
    login = await client.post("/api/v1/staff/login", json={"staff_id": staff_id, "pin": "6789"})
    staff_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.patch(
        f"/api/v1/orders/{order.id}/items/{items[0].id}",
        json={"qty": 5, "notes": "extra spicy"},
        headers=staff_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    edited = [i for i in body["items"] if i["notes"] == "extra spicy"]
    assert len(edited) == 1
    assert edited[0]["qty"] == 5


async def test_edit_order_item_at_ready_returns_422(client, auth_headers, db_session):
    from app.identity.models import Restaurant

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    order = await _seed_confirmed_order_two_items(db_session, restaurant.id)
    items = await _order_items(db_session, order.id)
    order.status = OrderStatus.READY
    await db_session.commit()

    resp = await client.patch(
        f"/api/v1/orders/{order.id}/items/{items[0].id}",
        json={"qty": 2},
        headers=auth_headers,
    )
    assert resp.status_code == 422
