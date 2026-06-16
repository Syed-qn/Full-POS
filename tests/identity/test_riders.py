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
