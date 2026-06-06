async def test_upload_menu_returns_drafts(client, auth_headers):
    files = [("files", ("menu.jpg", b"\xff\xd8\xff fake", "image/jpeg"))]
    resp = await client.post("/api/v1/menus", files=files, headers=auth_headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "pending_confirmation"
    assert body["version"] == 1
    numbers = [d["dish_number"] for d in body["dishes"]]
    assert 110 in numbers and 111 in numbers


async def test_upload_requires_auth(client):
    files = [("files", ("menu.jpg", b"x", "image/jpeg"))]
    resp = await client.post("/api/v1/menus", files=files)
    assert resp.status_code == 401


async def test_second_upload_increments_version(client, auth_headers):
    files = [("files", ("menu.jpg", b"\xff\xd8", "image/jpeg"))]
    await client.post("/api/v1/menus", files=files, headers=auth_headers)
    resp = await client.post("/api/v1/menus", files=files, headers=auth_headers)
    assert resp.json()["version"] == 2
