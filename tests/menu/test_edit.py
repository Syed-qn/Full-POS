async def _upload(client, auth_headers):
    files = [("files", ("menu.jpg", b"\xff\xd8", "image/jpeg"))]
    resp = await client.post("/api/v1/menus", files=files, headers=auth_headers)
    return resp.json()


async def test_add_dish(client, auth_headers):
    menu = await _upload(client, auth_headers)
    resp = await client.post(
        f"/api/v1/menus/{menu['id']}/dishes",
        json={"dish_number": 301, "name": "Falooda", "price_aed": "12.00",
              "category": "Desserts"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["dish_number"] == 301


async def test_patch_dish_price_and_name(client, auth_headers):
    menu = await _upload(client, auth_headers)
    dish = menu["dishes"][0]
    resp = await client.patch(
        f"/api/v1/menus/{menu['id']}/dishes/{dish['id']}",
        json={"price_aed": "24.00", "name": "Chicken Biryani (Large)"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["price_aed"] == "24.00"
    assert resp.json()["name"] == "Chicken Biryani (Large)"


async def test_delete_dish(client, auth_headers):
    menu = await _upload(client, auth_headers)
    dish = menu["dishes"][0]
    resp = await client.delete(
        f"/api/v1/menus/{menu['id']}/dishes/{dish['id']}", headers=auth_headers
    )
    assert resp.status_code == 204
    menu_after = (
        await client.get(f"/api/v1/menus/{menu['id']}", headers=auth_headers)
    ).json()
    assert dish["id"] not in [d["id"] for d in menu_after["dishes"]]


async def test_duplicate_dish_number_409(client, auth_headers):
    menu = await _upload(client, auth_headers)
    resp = await client.post(
        f"/api/v1/menus/{menu['id']}/dishes",
        json={"dish_number": 110, "name": "Clone", "price_aed": "9.00"},
        headers=auth_headers,
    )
    assert resp.status_code == 409
