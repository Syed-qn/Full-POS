import pytest


async def _upload(client, auth_headers):
    # A fresh upload lands in status "pending_confirmation" (see
    # app.menu.service.create_menu_from_upload) — unlike POST /menus/blank, which
    # creates the restaurant's first menu directly as "active" (app.menu.service.
    # ensure_active_menu). submit-for-approval only accepts a pending_confirmation
    # draft, so the approval-workflow tests must go through upload, not /menus/blank.
    files = [("files", ("menu.jpg", b"\xff\xd8", "image/jpeg"))]
    return (await client.post("/api/v1/menus", files=files, headers=auth_headers)).json()


@pytest.mark.anyio
async def test_submit_and_approve_menu_via_router(client, auth_headers):
    menu = await _upload(client, auth_headers)
    menu_id = menu["id"]
    assert menu["status"] == "pending_confirmation"

    submit = await client.post(f"/api/v1/menus/{menu_id}/submit-for-approval", headers=auth_headers)
    assert submit.status_code == 200, submit.text
    assert submit.json()["status"] == "pending_approval"

    approve = await client.post(f"/api/v1/menus/{menu_id}/approve", headers=auth_headers)
    assert approve.status_code == 200, approve.text
    assert approve.json()["status"] == "active"


@pytest.mark.anyio
async def test_approve_without_submit_rejected(client, auth_headers):
    blank = await client.post("/api/v1/menus/blank", headers=auth_headers)
    menu_id = blank.json()["id"]
    resp = await client.post(f"/api/v1/menus/{menu_id}/approve", headers=auth_headers)
    assert resp.status_code == 409
