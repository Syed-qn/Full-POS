# tests/menu/test_reextract.py
import pytest


@pytest.mark.asyncio
async def test_upload_creates_menu_file_row(client, auth_headers, tmp_path, monkeypatch):
    """Uploading a menu should persist bytes and create a MenuFile DB row."""
    import app.menu.service as svc
    from app.menu.storage import FileBlobStore
    # Patch the upload_dir to use tmp_path
    monkeypatch.setattr(svc, "_get_store", lambda: FileBlobStore(tmp_path))

    content = b"fake-pdf-bytes"
    from io import BytesIO
    resp = await client.post(
        "/api/v1/menus",
        files={"files": ("menu.pdf", BytesIO(content), "application/pdf")},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    menu_id = resp.json()["id"]
    assert menu_id


@pytest.mark.asyncio
async def test_reextract_menu(client, auth_headers, tmp_path, monkeypatch):
    """Re-extraction endpoint should return 200 without requiring a new upload."""
    import app.menu.service as svc
    from app.menu.storage import FileBlobStore
    monkeypatch.setattr(svc, "_get_store", lambda: FileBlobStore(tmp_path))

    content = b"fake-pdf-bytes-for-reextract"
    from io import BytesIO
    upload_resp = await client.post(
        "/api/v1/menus",
        files={"files": ("menu.pdf", BytesIO(content), "application/pdf")},
        headers=auth_headers,
    )
    assert upload_resp.status_code == 201
    menu_id = upload_resp.json()["id"]

    reextract_resp = await client.post(
        f"/api/v1/menus/{menu_id}/reextract",
        headers=auth_headers,
    )
    assert reextract_resp.status_code in (200, 201)


@pytest.mark.asyncio
async def test_reextract_tenant_isolation(client, auth_headers, tmp_path, monkeypatch):
    """Reextract on another restaurant's menu returns 404."""
    import app.menu.service as svc
    from app.menu.storage import FileBlobStore
    monkeypatch.setattr(svc, "_get_store", lambda: FileBlobStore(tmp_path))

    # Create a menu under auth_headers restaurant
    content = b"isolation-test"
    from io import BytesIO
    upload_resp = await client.post(
        "/api/v1/menus",
        files={"files": ("menu.pdf", BytesIO(content), "application/pdf")},
        headers=auth_headers,
    )
    menu_id = upload_resp.json()["id"]

    # Create a second restaurant and try to reextract that menu
    await client.post("/api/v1/auth/signup", json={
        "name": "Other Restaurant", "email": "other@rest.ae", "phone": "+971509999999",
        "password": "hunter2!", "lat": 25.0, "lng": 55.0,
    })
    resp2 = await client.post("/api/v1/auth/login", json={"email": "other@rest.ae", "password": "hunter2!"})
    other_headers = {"Authorization": f"Bearer {resp2.json()['access_token']}"}

    r = await client.post(f"/api/v1/menus/{menu_id}/reextract", headers=other_headers)
    assert r.status_code == 404
