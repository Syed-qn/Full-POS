"""Serving-size variants on a dish: persistence, schema validation, activation guard."""


async def _upload(client, auth_headers):
    files = [("files", ("menu.jpg", b"\xff\xd8", "image/jpeg"))]
    return (await client.post("/api/v1/menus", files=files, headers=auth_headers)).json()


async def test_dish_persists_variants(client, auth_headers):
    menu = await _upload(client, auth_headers)
    body = {
        "dish_number": 900,
        "name": "Chicken Biryani",
        "price_aed": "18.00",
        "category": "Biryani",
        "description": "Fragrant basmati, special spices",
        "variants": [
            {"name": "1 serve", "price_aed": "18.00"},
            {"name": "4 serve", "price_aed": "60.00"},
        ],
    }
    resp = await client.post(
        f"/api/v1/menus/{menu['id']}/dishes", json=body, headers=auth_headers
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert [v["name"] for v in created["variants"]] == ["1 serve", "4 serve"]
    assert created["variants"][1]["price_aed"] == "60.00"

    # Reload via GET to prove it round-tripped through JSONB.
    reloaded = (
        await client.get(f"/api/v1/menus/{menu['id']}", headers=auth_headers)
    ).json()
    dish = next(d for d in reloaded["dishes"] if d["dish_number"] == 900)
    assert [v["name"] for v in dish["variants"]] == ["1 serve", "4 serve"]


async def test_patch_dish_sets_variants(client, auth_headers):
    menu = await _upload(client, auth_headers)
    dish_id = menu["dishes"][0]["id"]
    resp = await client.patch(
        f"/api/v1/menus/{menu['id']}/dishes/{dish_id}",
        json={"variants": [{"name": "Small", "price_aed": "12.50"}]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["variants"] == [
        {"name": "Small", "price_aed": "12.50", "dish_number": None}
    ]


async def test_duplicate_variant_names_rejected(client, auth_headers):
    menu = await _upload(client, auth_headers)
    body = {
        "dish_number": 901,
        "name": "Biryani",
        "price_aed": "18.00",
        "variants": [
            {"name": "Regular", "price_aed": "18.00"},
            {"name": "regular", "price_aed": "20.00"},
        ],
    }
    resp = await client.post(
        f"/api/v1/menus/{menu['id']}/dishes", json=body, headers=auth_headers
    )
    assert resp.status_code == 422


async def test_nonpositive_variant_price_rejected(client, auth_headers):
    menu = await _upload(client, auth_headers)
    body = {
        "dish_number": 902,
        "name": "Biryani",
        "price_aed": "18.00",
        "variants": [{"name": "Regular", "price_aed": "0"}],
    }
    resp = await client.post(
        f"/api/v1/menus/{menu['id']}/dishes", json=body, headers=auth_headers
    )
    assert resp.status_code == 422


async def test_activate_blocked_if_variant_missing_price(client, auth_headers, db_session):
    from app.menu.models import Dish

    menu = await _upload(client, auth_headers)
    dish_id = menu["dishes"][0]["id"]
    # Simulate a saved variant that lost its price (e.g. extraction gap).
    dish = await db_session.get(Dish, dish_id)
    dish.variants = [{"name": "Family", "price_aed": None, "dish_number": None}]
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/menus/{menu['id']}/activate", headers=auth_headers
    )
    assert resp.status_code == 422
    assert "incomplete" in resp.json()["detail"].lower()


async def test_activate_ok_with_complete_variants(client, auth_headers, db_session):
    from app.menu.models import Dish

    menu = await _upload(client, auth_headers)
    dish_id = menu["dishes"][0]["id"]
    dish = await db_session.get(Dish, dish_id)
    dish.variants = [
        {"name": "1 serve", "price_aed": "18.00", "dish_number": None},
        {"name": "4 serve", "price_aed": "60.00", "dish_number": None},
    ]
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/menus/{menu['id']}/activate", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"
