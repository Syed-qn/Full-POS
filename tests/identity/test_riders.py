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
