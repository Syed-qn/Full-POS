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


async def test_second_upload_appends_into_active_menu(client, auth_headers):
    """Uploading a second menu is a BULK ADD: its dishes move into the existing active
    menu (500+20 style), rather than replacing it. The active menu grows; the uploaded
    draft is emptied and marked superseded."""
    m1 = await _upload(client, auth_headers)
    activated1 = (
        await client.post(f"/api/v1/menus/{m1['id']}/activate", headers=auth_headers)
    ).json()
    n1 = len(activated1["dishes"])
    assert n1 > 0

    m2 = await _upload(client, auth_headers)
    activated2 = (
        await client.post(f"/api/v1/menus/{m2['id']}/activate", headers=auth_headers)
    ).json()

    # The menu that now holds everything is m1 (the active one), NOT the m2 draft.
    assert activated2["id"] == m1["id"]
    assert activated2["status"] == "active"
    assert len(activated2["dishes"]) == n1 * 2  # both uploads' dishes in one menu
    # No duplicate dish numbers after the collision-safe renumber.
    nums = [d["dish_number"] for d in activated2["dishes"]]
    assert len(nums) == len(set(nums))

    # m2 is now an emptied, superseded draft.
    m2_after = (
        await client.get(f"/api/v1/menus/{m2['id']}", headers=auth_headers)
    ).json()
    assert m2_after["status"] == "superseded"
    assert m2_after["dishes"] == []


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
