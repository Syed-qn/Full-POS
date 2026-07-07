import pytest

from app.kds.printer_status import get_printer_status, record_printer_heartbeat


@pytest.mark.anyio
async def test_record_and_get_printer_status(db_session, restaurant):
    from app.kds.models import KitchenStation

    station = KitchenStation(restaurant_id=restaurant.id, name="Grill")
    db_session.add(station)
    await db_session.flush()
    await db_session.commit()

    await record_printer_heartbeat(
        db_session, restaurant_id=restaurant.id, station_id=station.id, healthy=True,
    )
    await db_session.commit()

    statuses = await get_printer_status(db_session, restaurant_id=restaurant.id)
    assert len(statuses) == 1
    assert statuses[0]["station_id"] == station.id
    assert statuses[0]["healthy"] is True
    assert statuses[0]["last_heartbeat_at"] is not None


@pytest.mark.anyio
async def test_repeated_heartbeat_updates_existing_row_not_duplicates(db_session, restaurant):
    from app.kds.models import KitchenStation

    station = KitchenStation(restaurant_id=restaurant.id, name="Fryer")
    db_session.add(station)
    await db_session.flush()
    await db_session.commit()

    await record_printer_heartbeat(
        db_session, restaurant_id=restaurant.id, station_id=station.id, healthy=True,
    )
    await db_session.commit()
    await record_printer_heartbeat(
        db_session, restaurant_id=restaurant.id, station_id=station.id, healthy=False,
    )
    await db_session.commit()

    statuses = await get_printer_status(db_session, restaurant_id=restaurant.id)
    assert len(statuses) == 1
    assert statuses[0]["healthy"] is False


@pytest.mark.anyio
async def test_printer_heartbeat_and_status_router(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.kds.models import KitchenStation

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    station = KitchenStation(restaurant_id=restaurant.id, name="Grill")
    db_session.add(station)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/kds/stations/{station.id}/printer-heartbeat",
        json={"healthy": True},
        headers=auth_headers,
    )
    assert resp.status_code in (200, 201, 204)

    status_resp = await client.get("/api/v1/kds/printer-status", headers=auth_headers)
    assert status_resp.status_code == 200
    body = status_resp.json()
    assert any(s["station_id"] == station.id and s["healthy"] is True for s in body)


@pytest.mark.anyio
async def test_printer_heartbeat_rejects_station_of_other_restaurant(client, auth_headers, db_session):
    from app.identity.models import Restaurant
    from app.kds.models import KitchenStation

    other = Restaurant(
        name="Other Place", email="other-printer@biryani.ae", phone="+971500011122",
        password_hash="x", lat=25.2048, lng=55.2708,
    )
    db_session.add(other)
    await db_session.flush()
    station = KitchenStation(restaurant_id=other.id, name="Other Station")
    db_session.add(station)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/kds/stations/{station.id}/printer-heartbeat",
        json={"healthy": True},
        headers=auth_headers,
    )
    assert resp.status_code == 404
