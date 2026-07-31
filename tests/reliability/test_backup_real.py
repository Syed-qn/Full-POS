"""Backups that are actually restorable.

The previous implementation dumped six hand-picked tables (orders capped at
5000), wrote them to a path nobody had configured, offered a "Full data export"
that produced no file, and had no restore at all. These tests pin down the
behaviour that replaced it: full tenant coverage, a real download, and a
round-trip that survives deleting live data.
"""

import json
from pathlib import Path
from urllib.parse import urlparse

import pytest


def _local_path(uri: str) -> Path:
    """Snapshots are addressed by URI now; tests read the file behind it."""
    assert uri.startswith("file://"), uri
    return Path(uri[7:].lstrip("/"))


@pytest.fixture
def backup_dir(tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("APP_BACKUP_DIR", str(tmp_path))
    get_settings.cache_clear()
    return tmp_path


@pytest.mark.anyio
async def test_storage_round_trips_a_path_containing_a_space(tmp_path, monkeypatch):
    # The real deployment lives in "C:\Users\user\Full POS". Path.as_uri()
    # percent-encodes that space, so a URI parser that skips unquote() writes a
    # file it can never read back — every Verify would report "file missing".
    from app.config import get_settings
    from app.reliability import storage

    spaced = tmp_path / "Full POS"
    spaced.mkdir()
    monkeypatch.setenv("APP_BACKUP_DIR", str(spaced))
    get_settings.cache_clear()

    uri = await storage.put_backup("probe.json", b'{"a":1}')
    assert "%20" in uri
    assert await storage.backup_exists(uri) is True
    assert await storage.get_backup(uri) == b'{"a":1}'


@pytest.mark.anyio
async def test_snapshot_covers_every_tenant_table_not_a_hand_picked_six(
    client, auth_headers, backup_dir
):
    resp = await client.post(
        "/api/v1/reliability/backups?kind=manual", headers=auth_headers
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    data = json.loads(_local_path(body["storage_path"]).read_bytes())
    assert data["format"] == 2
    names = set(data["tables"])

    # The restaurant row keys on `id`, not `restaurant_id` — without it a restore
    # has no tenant to attach anything to, and the old snapshot omitted it.
    assert data["tables"]["restaurants"], "tenant row itself must be captured"

    # Tables the old snapshot silently dropped. Absence here means the metadata
    # sweep stopped finding a whole bounded context.
    for missing_before in ("tables", "payment_transactions", "staff_members"):
        assert missing_before in names, f"{missing_before} not in snapshot"

    # Far more than the six tables the hand-written version carried.
    assert len(names) > 20, f"only {len(names)} tables captured"

    # Every column travels, not a curated subset.
    rest_row = data["tables"]["restaurants"][0]
    assert {"id", "name", "phone"} <= set(rest_row)


@pytest.mark.anyio
async def test_export_returns_a_url_that_actually_downloads_the_file(
    client, auth_headers, backup_dir
):
    export = await client.post("/api/v1/reliability/export", headers=auth_headers)
    assert export.status_code == 200, export.text
    body = export.json()

    # The old response handed back `download_path` — a server-side filesystem
    # path a browser cannot open, so pressing the button downloaded nothing.
    assert "download_path" not in body
    url = body["download_url"]
    assert urlparse(url).path.endswith(f"/backups/{body['backup_job_id']}/download")

    dl = await client.get(url, headers=auth_headers)
    assert dl.status_code == 200
    assert dl.headers["content-disposition"].startswith("attachment;")
    assert len(dl.content) == body["size_bytes"]
    assert json.loads(dl.content)["format"] == 2


@pytest.mark.anyio
async def test_listing_flags_a_backup_whose_file_has_been_deleted(
    client, auth_headers, backup_dir
):
    # The exact production failure: the job row outlives its file after a
    # container redeploy, and the dashboard kept showing "completed".
    created = (
        await client.post(
            "/api/v1/reliability/backups?kind=manual", headers=auth_headers
        )
    ).json()
    _local_path(created["storage_path"]).unlink()

    rows = (
        await client.get("/api/v1/reliability/backups", headers=auth_headers)
    ).json()
    row = next(r for r in rows if r["id"] == created["id"])
    assert row["status"] == "completed"
    assert row["file_present"] is False


@pytest.mark.anyio
async def test_backup_target_admits_when_storage_is_not_durable(
    client, auth_headers, backup_dir
):
    target = (
        await client.get("/api/v1/reliability/backup-target", headers=auth_headers)
    ).json()
    assert target["backend"] == "local"
    assert target["durable"] is False
    assert "volume" in target["note"].lower()


@pytest.mark.anyio
async def test_claiming_a_volume_does_not_make_the_badge_green(
    client, auth_headers, backup_dir, monkeypatch
):
    # APP_BACKUP_DIR_IS_VOLUME is an operator assertion. If the volume never
    # mounted, tmp_path sits on the same filesystem as / and the badge must stay
    # red — a green badge over disposable disk is the exact failure this screen
    # was built to stop. Skipped where st_dev cannot answer (Windows dev boxes).
    import os

    from app.config import get_settings

    if os.name != "posix":
        pytest.skip("mount detection is POSIX-only")

    monkeypatch.setenv("APP_BACKUP_DIR_IS_VOLUME", "true")
    get_settings.cache_clear()

    target = (
        await client.get("/api/v1/reliability/backup-target", headers=auth_headers)
    ).json()
    assert target["mount_verified"] is False
    assert target["durable"] is False
    assert "filesystem says" in target["note"]


@pytest.mark.anyio
async def test_unwritable_backup_dir_reports_instead_of_500ing(
    client, auth_headers, backup_dir, monkeypatch
):
    # Railway mounts a volume owned by root while the container runs as an
    # unprivileged user, so mkdir raises PermissionError. The endpoint whose job
    # is to report on storage health must not be the thing that crashes — it has
    # to say what went wrong and how to fix it.
    from pathlib import Path as _P

    def boom(self, *a, **k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(_P, "mkdir", boom)

    resp = await client.get("/api/v1/reliability/backup-target", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["durable"] is False
    assert "CANNOT WRITE" in body["note"]
    assert "RAILWAY_RUN_UID=0" in body["note"]


@pytest.mark.anyio
async def test_restore_is_refused_unless_explicitly_enabled(
    client, auth_headers, backup_dir
):
    created = (
        await client.post(
            "/api/v1/reliability/backups?kind=manual", headers=auth_headers
        )
    ).json()
    resp = await client.post(
        f"/api/v1/reliability/backups/{created['id']}/restore",
        headers=auth_headers,
        json={"confirm": "RESTORE 1"},
    )
    assert resp.status_code == 409
    assert "disabled" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_restore_rejects_a_wrong_confirmation_phrase(
    client, auth_headers, backup_dir, monkeypatch
):
    from app.config import get_settings

    monkeypatch.setenv("APP_BACKUP_RESTORE_ENABLED", "true")
    get_settings.cache_clear()

    created = (
        await client.post(
            "/api/v1/reliability/backups?kind=manual", headers=auth_headers
        )
    ).json()
    resp = await client.post(
        f"/api/v1/reliability/backups/{created['id']}/restore",
        headers=auth_headers,
        json={"confirm": "yes"},
    )
    assert resp.status_code == 409
    assert "confirmation must be exactly" in resp.json()["detail"]


@pytest.mark.anyio
async def test_restore_brings_back_data_deleted_after_the_backup(
    client, auth_headers, backup_dir, monkeypatch
):
    from app.config import get_settings

    monkeypatch.setenv("APP_BACKUP_RESTORE_ENABLED", "true")
    get_settings.cache_clear()

    made = await client.post(
        "/api/v1/tables",
        headers=auth_headers,
        json={"label": "T99", "seats": 4},
    )
    assert made.status_code in (200, 201), made.text

    created = (
        await client.post(
            "/api/v1/reliability/backups?kind=manual", headers=auth_headers
        )
    ).json()
    rid = json.loads(_local_path(created["storage_path"]).read_bytes())["restaurant_id"]

    # Lose the data the way a real incident would.
    table_id = made.json()["id"]
    gone = await client.delete(f"/api/v1/tables/{table_id}", headers=auth_headers)
    assert gone.status_code in (200, 204), gone.text
    after_delete = (await client.get("/api/v1/tables", headers=auth_headers)).json()
    assert not any(t["label"] == "T99" for t in after_delete)

    resp = await client.post(
        f"/api/v1/reliability/backups/{created['id']}/restore",
        headers=auth_headers,
        json={"confirm": f"RESTORE {rid}"},
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["restore_mode"] == "overwrite"
    # The restore takes its own snapshot first, so an unwanted restore is undoable.
    assert result["pre_restore_backup_id"] != created["id"]

    back = (await client.get("/api/v1/tables", headers=auth_headers)).json()
    assert any(t["label"] == "T99" for t in back), "restored table is missing"


@pytest.mark.anyio
async def test_restore_refuses_a_corrupted_snapshot(
    client, auth_headers, backup_dir, monkeypatch
):
    from app.config import get_settings

    monkeypatch.setenv("APP_BACKUP_RESTORE_ENABLED", "true")
    get_settings.cache_clear()

    created = (
        await client.post(
            "/api/v1/reliability/backups?kind=manual", headers=auth_headers
        )
    ).json()
    rid = json.loads(_local_path(created["storage_path"]).read_bytes())["restaurant_id"]

    # Tamper AFTER the checksum was recorded. Restoring this would write garbage
    # over live data, so the checksum gate must stop it before any DELETE runs.
    path = _local_path(created["storage_path"])
    payload = json.loads(path.read_bytes())
    payload["tables"]["restaurants"] = []
    path.write_bytes(json.dumps(payload).encode())

    resp = await client.post(
        f"/api/v1/reliability/backups/{created['id']}/restore",
        headers=auth_headers,
        json={"confirm": f"RESTORE {rid}"},
    )
    assert resp.status_code == 409
    assert "corrupt" in resp.json()["detail"].lower()
