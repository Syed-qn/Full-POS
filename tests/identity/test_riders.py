async def test_create_and_list_riders(client, auth_headers):
    resp = await client.post(
        "/api/v1/riders",
        json={"name": "Ahmed", "phone": "+971509998888"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "available"

    listing = await client.get("/api/v1/riders", headers=auth_headers)
    assert [r["name"] for r in listing.json()] == ["Ahmed"]
    # New riders have no deliveries — both tallies start at 0.
    assert listing.json()[0]["delivered_24h"] == 0
    assert listing.json()[0]["delivered_lifetime"] == 0
    # No location shared yet → null position fields.
    assert listing.json()[0]["last_lat"] is None
    assert listing.json()[0]["last_location_at"] is None


async def test_create_rider_auto_sends_app_invite(client, auth_headers, db_session):
    """Adding a rider in ops automatically WhatsApps them the app link + pairing
    code — no separate manual invite step."""
    from sqlalchemy import select

    from app.outbox.models import OutboxMessage

    resp = await client.post(
        "/api/v1/riders",
        json={"name": "Bilal", "phone": "+971509997777"},
        headers=auth_headers,
    )
    assert resp.status_code == 201

    msg = await db_session.scalar(
        select(OutboxMessage).where(OutboxMessage.to_phone == "+971509997777")
    )
    assert msg is not None
    assert msg.idempotency_key.startswith("app-pair-")
    assert "pairing" in msg.payload["body"].lower()


async def test_rider_location_endpoint(client, auth_headers, db_session):
    from app.dispatch.rider_location import update_rider_location
    from app.identity.models import Rider

    rider = (
        await client.post(
            "/api/v1/riders",
            json={"name": "Ahmed", "phone": "+971509998888"},
            headers=auth_headers,
        )
    ).json()

    # No ping yet → 200 with null body.
    empty = await client.get(f"/api/v1/riders/{rider['id']}/location", headers=auth_headers)
    assert empty.status_code == 200
    assert empty.json() is None

    # Ingest a location ping the way the rider inbound flow does (client + this
    # session share one transaction, so the insert is visible to the next call).
    rider_row = await db_session.get(Rider, rider["id"])
    await update_rider_location(db_session, rider=rider_row, latitude=25.2, longitude=55.27)
    await db_session.commit()

    resp = await client.get(f"/api/v1/riders/{rider['id']}/location", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["lat"] == 25.2 and body["lng"] == 55.27
    assert "ts" in body

    # Also surfaced on the list endpoint's latest-position fields.
    listing = await client.get("/api/v1/riders", headers=auth_headers)
    assert listing.json()[0]["last_lat"] == 25.2

    # Unknown rider → 404.
    missing = await client.get("/api/v1/riders/999999/location", headers=auth_headers)
    assert missing.status_code == 404


async def test_list_riders_survives_missing_location_table(client, auth_headers, monkeypatch):
    from app.identity import service as identity_service

    rider = (
        await client.post(
            "/api/v1/riders",
            json={"name": "Ahmed", "phone": "+971509998888"},
            headers=auth_headers,
        )
    ).json()

    async def _no_locations(session, *, restaurant_id):
        return {}

    monkeypatch.setattr(identity_service, "_latest_rider_locations", _no_locations)

    listing = await client.get("/api/v1/riders", headers=auth_headers)
    assert listing.status_code == 200
    assert listing.json()[0]["id"] == rider["id"]
    assert listing.json()[0]["last_lat"] is None


async def test_geo_health_reports_provider_and_distance(client, auth_headers):
    # No params → provider config only.
    base = await client.get("/api/v1/geo/health", headers=auth_headers)
    assert base.status_code == 200
    body = base.json()
    assert "configured_provider" in body
    assert "google_key_present" in body
    assert "restaurant_location" in body
    assert "test" not in body

    # With a test pin → distance comparison block. Tests run the offline (fake)
    # provider, so road distance == straight-line and real-road-distance is False.
    with_pin = await client.get(
        "/api/v1/geo/health?lat=25.10&lng=55.15", headers=auth_headers
    )
    assert with_pin.status_code == 200
    test = with_pin.json()["test"]
    assert test["road_km"] >= 0
    assert test["straight_line_km"] >= 0
    assert test["using_real_road_distance"] is False


async def test_duplicate_rider_phone_409(client, auth_headers):
    body = {"name": "Ahmed", "phone": "+971509998888"}
    await client.post("/api/v1/riders", json=body, headers=auth_headers)
    resp = await client.post("/api/v1/riders", json=body, headers=auth_headers)
    assert resp.status_code == 409


async def test_deactivate_rider(client, auth_headers):
    rider = (
        await client.post(
            "/api/v1/riders",
            json={"name": "Ahmed", "phone": "+971509998888"},
            headers=auth_headers,
        )
    ).json()
    resp = await client.patch(
        f"/api/v1/riders/{rider['id']}",
        json={"status": "deactivated"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "deactivated"


async def test_update_delivery_settings(client, auth_headers):
    resp = await client.patch(
        "/api/v1/settings",
        json={"max_orders_per_batch": 4},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["settings"]["max_orders_per_batch"] == 4
    # untouched keys preserved
    assert resp.json()["settings"]["max_radius_km"] == 10


async def test_update_dispatch_and_kitchen_settings(client, auth_headers):
    """The dispatch engine + kitchen-timing tunables are settable via the settings PATCH."""
    resp = await client.patch(
        "/api/v1/settings",
        json={
            "dispatch_engine": "ortools",
            "prep_handling_minutes": 7,
            "batch_safety_minutes": 3,
            "default_prep_minutes": 18,
            "batch_expedite_radius_km": 2.0,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    sset = resp.json()["settings"]
    assert sset["dispatch_engine"] == "ortools"
    assert sset["prep_handling_minutes"] == 7
    assert sset["batch_safety_minutes"] == 3
    assert sset["default_prep_minutes"] == 18
    assert sset["batch_expedite_radius_km"] == 2.0


async def test_dispatch_engine_rejects_unknown_value(client, auth_headers):
    resp = await client.patch(
        "/api/v1/settings",
        json={"dispatch_engine": "magic"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_edit_rider_name_and_phone(client, auth_headers):
    rider = (
        await client.post(
            "/api/v1/riders",
            json={"name": "Ahmed", "phone": "+971509998888"},
            headers=auth_headers,
        )
    ).json()
    resp = await client.patch(
        f"/api/v1/riders/{rider['id']}",
        json={"name": "Ahmed Khan", "phone": "+971501112222"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Ahmed Khan"
    assert resp.json()["phone"] == "+971501112222"
    # status untouched by a profile edit
    assert resp.json()["status"] == "available"


async def test_edit_rider_phone_conflict_409(client, auth_headers):
    await client.post(
        "/api/v1/riders",
        json={"name": "Ahmed", "phone": "+971509998888"},
        headers=auth_headers,
    )
    rider2 = (
        await client.post(
            "/api/v1/riders",
            json={"name": "Bilal", "phone": "+971507776666"},
            headers=auth_headers,
        )
    ).json()
    # Editing rider2 to rider1's phone must conflict.
    resp = await client.patch(
        f"/api/v1/riders/{rider2['id']}",
        json={"phone": "+971509998888"},
        headers=auth_headers,
    )
    assert resp.status_code == 409


async def test_patch_rider_no_fields_422(client, auth_headers):
    rider = (
        await client.post(
            "/api/v1/riders",
            json={"name": "Ahmed", "phone": "+971509998888"},
            headers=auth_headers,
        )
    ).json()
    resp = await client.patch(
        f"/api/v1/riders/{rider['id']}", json={}, headers=auth_headers
    )
    assert resp.status_code == 422


async def test_update_restaurant_location(client, auth_headers):
    resp = await client.patch(
        "/api/v1/me",
        json={"name": "Spicy Restaurant", "lat": 25.1124, "lng": 55.1390},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["lat"] == 25.1124
    assert body["lng"] == 55.1390


async def test_update_restaurant_location_out_of_range_422(client, auth_headers):
    resp = await client.patch(
        "/api/v1/me",
        json={"name": "Spicy", "lat": 200, "lng": 55.0},
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_invalid_rider_status_422(client, auth_headers):
    rider = (
        await client.post(
            "/api/v1/riders",
            json={"name": "Ahmed", "phone": "+971509998888"},
            headers=auth_headers,
        )
    ).json()
    resp = await client.patch(
        f"/api/v1/riders/{rider['id']}",
        json={"status": "vanished"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
