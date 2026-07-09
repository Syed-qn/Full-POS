"""Category 12 — offline, backup, reliability full wiring tests."""

from decimal import Decimal
from pathlib import Path

import pytest


@pytest.mark.anyio
async def test_backup_create_verify_export(client, auth_headers, tmp_path, monkeypatch):
    monkeypatch.setenv("APP_BACKUP_DIR", str(tmp_path))

    create = await client.post(
        "/api/v1/reliability/backups?kind=manual",
        headers=auth_headers,
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["status"] == "completed"
    assert body["checksum"]
    assert Path(body["storage_path"]).exists()

    listing = await client.get("/api/v1/reliability/backups", headers=auth_headers)
    assert listing.status_code == 200
    assert len(listing.json()) >= 1

    verify = await client.post(
        f"/api/v1/reliability/backups/{body['id']}/verify",
        headers=auth_headers,
    )
    assert verify.status_code == 200
    assert verify.json()["ok"] is True

    preview = await client.post(
        f"/api/v1/reliability/backups/{body['id']}/restore-preview",
        headers=auth_headers,
    )
    assert preview.status_code == 200
    assert preview.json()["restore_mode"] == "preview_only"

    daily = await client.post(
        "/api/v1/reliability/backups/daily",
        headers=auth_headers,
    )
    assert daily.status_code == 200

    export = await client.post(
        "/api/v1/reliability/export",
        headers=auth_headers,
    )
    assert export.status_code == 200
    assert export.json()["backup_job_id"]

    readiness = await client.get(
        "/api/v1/audit-log/backup-readiness",
        headers=auth_headers,
    )
    assert readiness.status_code == 200
    assert readiness.json().get("last_backup_id") is not None


@pytest.mark.anyio
async def test_devices_failover_and_network(client, auth_headers):
    reg = await client.post(
        "/api/v1/reliability/devices",
        headers=auth_headers,
        json={
            "device_id": "term-primary-1",
            "name": "Front POS",
            "device_type": "pos",
            "role": "primary",
        },
    )
    assert reg.status_code == 201
    standby = await client.post(
        "/api/v1/reliability/devices",
        headers=auth_headers,
        json={
            "device_id": "term-backup-1",
            "name": "Backup POS",
            "device_type": "pos",
            "role": "standby",
        },
    )
    assert standby.status_code == 201

    hb = await client.post(
        "/api/v1/reliability/devices/term-primary-1/heartbeat",
        headers=auth_headers,
    )
    assert hb.status_code == 200

    fo = await client.post(
        "/api/v1/reliability/devices/term-backup-1/failover",
        headers=auth_headers,
    )
    assert fo.status_code == 200
    assert fo.json()["is_failover_active"] is True
    assert fo.json()["role"] == "primary"

    net = await client.get(
        "/api/v1/reliability/network-status",
        headers=auth_headers,
    )
    assert net.status_code == 200
    assert net.json()["devices_total"] >= 2


@pytest.mark.anyio
async def test_offline_payment_and_errors(client, auth_headers, restaurant, db_session):
    from app.ordering.models import Customer, Order

    cust = Customer(
        restaurant_id=restaurant.id,
        phone="+971500012001",
        name="Off",
        total_orders=0,
        total_spend=Decimal("0"),
    )
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number="C12-OFF-1",
        status="confirmed",
        subtotal=Decimal("25"),
        total=Decimal("25"),
    )
    db_session.add(order)
    await db_session.commit()

    pay = await client.post(
        "/api/v1/reliability/offline-payments",
        headers=auth_headers,
        json={
            "client_payment_id": "offline-pay-abc",
            "amount_aed": "25.00",
            "tender_type": "cash",
            "order_id": order.id,
            "device_id": "term-1",
        },
    )
    assert pay.status_code == 201, pay.text
    assert pay.json()["status"] == "applied"

    # idempotent
    pay2 = await client.post(
        "/api/v1/reliability/offline-payments",
        headers=auth_headers,
        json={
            "client_payment_id": "offline-pay-abc",
            "amount_aed": "25.00",
            "tender_type": "cash",
            "order_id": order.id,
        },
    )
    assert pay2.status_code == 201
    assert pay2.json()["id"] == pay.json()["id"]

    err = await client.post(
        "/api/v1/reliability/errors",
        headers=auth_headers,
        json={"message": "printer offline", "source": "desktop", "level": "warn"},
    )
    assert err.status_code == 201

    errors = await client.get(
        "/api/v1/reliability/errors",
        headers=auth_headers,
    )
    assert errors.status_code == 200
    assert len(errors.json()) >= 1

    ack = await client.post(
        f"/api/v1/reliability/errors/{err.json()['id']}/ack",
        headers=auth_headers,
    )
    assert ack.status_code == 200
    assert ack.json()["acknowledged"] is True


@pytest.mark.anyio
async def test_health_uptime_components(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "uptime_components" in body or "db" in body


@pytest.mark.anyio
async def test_printer_failover_on_failed_status(db_session, restaurant):
    from app.kds.models import KitchenStation
    from app.kds.printer_status import record_printer_heartbeat
    from app.kds.service import _resolve_print_station

    primary = KitchenStation(
        restaurant_id=restaurant.id,
        name="Grill",
        station_type="grill",
    )
    db_session.add(primary)
    await db_session.flush()
    fallback = KitchenStation(
        restaurant_id=restaurant.id,
        name="Backup printer",
        station_type="main",
    )
    db_session.add(fallback)
    await db_session.flush()
    primary.fallback_station_id = fallback.id
    await db_session.flush()

    await record_printer_heartbeat(
        db_session,
        restaurant_id=restaurant.id,
        station_id=primary.id,
        healthy=False,
    )
    await record_printer_heartbeat(
        db_session,
        restaurant_id=restaurant.id,
        station_id=fallback.id,
        healthy=True,
    )
    await db_session.commit()

    sid, via_fb, original = await _resolve_print_station(
        db_session, restaurant_id=restaurant.id, station_id=primary.id
    )
    assert via_fb is True
    assert sid == fallback.id
    assert original == primary.id
