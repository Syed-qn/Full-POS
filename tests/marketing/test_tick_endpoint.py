"""The POST /api/v1/marketing/tick heartbeat is guarded by a shared secret and
needs no manager JWT (it's called by an external cron, not the dashboard)."""

from types import SimpleNamespace

from pydantic import SecretStr


def _patch_secret(monkeypatch, value: str):
    monkeypatch.setattr(
        "app.marketing.router.get_settings",
        lambda: SimpleNamespace(marketing_tick_secret=SecretStr(value)),
    )


async def test_tick_503_when_secret_unconfigured(client, monkeypatch):
    _patch_secret(monkeypatch, "")
    resp = await client.post("/api/v1/marketing/tick")
    assert resp.status_code == 503


async def test_tick_403_on_wrong_secret(client, monkeypatch):
    _patch_secret(monkeypatch, "topsecret")
    resp = await client.post(
        "/api/v1/marketing/tick", headers={"X-Tick-Secret": "nope"}
    )
    assert resp.status_code == 403


async def test_tick_runs_with_correct_secret(client, monkeypatch):
    _patch_secret(monkeypatch, "topsecret")
    resp = await client.post(
        "/api/v1/marketing/tick", headers={"X-Tick-Secret": "topsecret"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"queued": 0, "suppressed": 0, "restaurants": 0}
