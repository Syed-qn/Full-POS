async def _upload(client, auth_headers):
    files = [("files", ("menu.jpg", b"\xff\xd8", "image/jpeg"))]
    return (await client.post("/api/v1/menus", files=files, headers=auth_headers)).json()


async def test_activate_menu(client, auth_headers):
    menu = await _upload(client, auth_headers)
    resp = await client.post(
        f"/api/v1/menus/{menu['id']}/activate", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"


async def test_activate_supersedes_previous(client, auth_headers):
    m1 = await _upload(client, auth_headers)
    await client.post(f"/api/v1/menus/{m1['id']}/activate", headers=auth_headers)
    m2 = await _upload(client, auth_headers)
    await client.post(f"/api/v1/menus/{m2['id']}/activate", headers=auth_headers)

    m1_after = (
        await client.get(f"/api/v1/menus/{m1['id']}", headers=auth_headers)
    ).json()
    assert m1_after["status"] == "superseded"


async def test_activate_blocked_when_missing_price(client, auth_headers, db_session):
    from app.menu.models import Dish

    menu = await _upload(client, auth_headers)
    # null a price directly in DB to simulate extraction gap
    dish_id = menu["dishes"][0]["id"]
    dish = await db_session.get(Dish, dish_id)
    dish.price_aed = None
    await db_session.flush()

    resp = await client.post(
        f"/api/v1/menus/{menu['id']}/activate", headers=auth_headers
    )
    assert resp.status_code == 422
    assert "incomplete" in resp.json()["detail"].lower() or "price" in resp.json()["detail"].lower()
