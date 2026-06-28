async def test_create_and_list_coupon(client, auth_headers):
    resp = await client.post(
        "/api/v1/coupons",
        headers=auth_headers,
        json={"discount_type": "fixed", "discount_value": "10.00", "kind": "multi_use"},
    )
    assert resp.status_code == 201, resp.text
    code = resp.json()["code"]
    assert resp.json()["status"] == "active"

    listed = await client.get("/api/v1/coupons", headers=auth_headers)
    assert listed.status_code == 200
    assert any(c["code"] == code for c in listed.json())


async def test_pause_coupon(client, auth_headers):
    created = await client.post(
        "/api/v1/coupons",
        headers=auth_headers,
        json={"discount_type": "percent", "discount_value": "15.00"},
    )
    code = created.json()["code"]
    paused = await client.post(f"/api/v1/coupons/{code}/pause", headers=auth_headers)
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"


async def test_create_rejects_bad_discount(client, auth_headers):
    resp = await client.post(
        "/api/v1/coupons",
        headers=auth_headers,
        json={"discount_type": "fixed", "discount_value": "0"},
    )
    assert resp.status_code == 422  # pydantic gt=0
