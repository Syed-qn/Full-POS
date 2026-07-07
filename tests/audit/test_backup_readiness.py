# tests/audit/test_backup_readiness.py
"""backup_readiness(): a live sanity-count diagnostic, NOT a real backup
integration — reports row counts for core tenant tables so a manager can
tell "does this restaurant's data look intact right now"."""

from app.audit.backup_status import backup_readiness


async def test_backup_readiness_counts_core_tables(db_session, restaurant, seed_biryani_menu):
    result = await backup_readiness(db_session, restaurant_id=restaurant.id)
    assert result["orders_count"] == 0
    assert result["customers_count"] == 0
    assert result["dishes_count"] == 4
    assert "checked_at" in result

    from datetime import datetime

    datetime.fromisoformat(result["checked_at"])


async def test_backup_readiness_router_manager_only(client):
    resp = await client.get("/api/v1/audit-log/backup-readiness")
    assert resp.status_code == 401


async def test_backup_readiness_router_returns_counts(client, auth_headers):
    resp = await client.get("/api/v1/audit-log/backup-readiness", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "orders_count" in body
    assert "customers_count" in body
    assert "dishes_count" in body
    assert "checked_at" in body
