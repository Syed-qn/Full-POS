# tests/audit/test_audit_log_router.py
"""GET /api/v1/audit-log — manager-role-gated, tenant-scoped query surface
over the append-only AuditLog table."""

from sqlalchemy import select

from app.audit.service import record_audit
from app.identity.models import Restaurant


async def _owned_restaurant(db_session):
    return await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )


async def test_audit_log_requires_manager_role(client):
    resp = await client.get("/api/v1/audit-log")
    assert resp.status_code == 401


async def test_audit_log_returns_tenant_scoped_rows(client, auth_headers, db_session):
    restaurant = await _owned_restaurant(db_session)
    await record_audit(
        db_session, actor="system", entity="order", entity_id="1",
        action="status_change", restaurant_id=restaurant.id,
        before={"status": "ready"}, after={"status": "assigned"},
    )
    await record_audit(
        db_session, actor="system", entity="order", entity_id="2",
        action="status_change", restaurant_id=999999,  # other tenant
        before={"status": "ready"}, after={"status": "assigned"},
    )
    await db_session.commit()

    resp = await client.get("/api/v1/audit-log", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["rows"], list)
    assert any(r["entity_id"] == "1" for r in body["rows"])
    assert all(r["entity_id"] != "2" for r in body["rows"])


async def test_audit_log_filters_by_entity_and_action(client, auth_headers, db_session):
    restaurant = await _owned_restaurant(db_session)
    await record_audit(
        db_session, actor="system", entity="order", entity_id="1",
        action="status_change", restaurant_id=restaurant.id,
    )
    await record_audit(
        db_session, actor="system", entity="drawer_session", entity_id="1",
        action="open", restaurant_id=restaurant.id,
    )
    await db_session.commit()

    resp = await client.get(
        "/api/v1/audit-log", params={"entity": "drawer_session"}, headers=auth_headers,
    )
    assert resp.status_code == 200
    rows = resp.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["entity"] == "drawer_session"

    resp2 = await client.get(
        "/api/v1/audit-log", params={"action": "status_change"}, headers=auth_headers,
    )
    assert resp2.json()["rows"][0]["action"] == "status_change"


async def test_audit_log_date_range_filter(client, auth_headers, db_session):
    restaurant = await _owned_restaurant(db_session)
    await record_audit(
        db_session, actor="system", entity="order", entity_id="1",
        action="status_change", restaurant_id=restaurant.id,
    )
    await db_session.commit()

    from datetime import date, timedelta

    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    resp = await client.get(
        "/api/v1/audit-log",
        params={"start_date": yesterday, "end_date": tomorrow},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert any(r["entity_id"] == "1" for r in resp.json()["rows"])

    resp2 = await client.get(
        "/api/v1/audit-log",
        params={"start_date": tomorrow, "end_date": tomorrow},
        headers=auth_headers,
    )
    assert resp2.json()["rows"] == []


async def test_audit_log_respects_limit(client, auth_headers, db_session):
    restaurant = await _owned_restaurant(db_session)
    for i in range(5):
        await record_audit(
            db_session, actor="system", entity="order", entity_id=str(i),
            action="status_change", restaurant_id=restaurant.id,
        )
    await db_session.commit()

    resp = await client.get(
        "/api/v1/audit-log", params={"limit": 2}, headers=auth_headers,
    )
    assert resp.status_code == 200
    assert len(resp.json()["rows"]) == 2
