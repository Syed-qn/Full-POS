"""The POST /api/v1/conversations/cart-tick heartbeat drives the abandoned-cart
sweep from an external cron (Render has no working Celery beat). It is guarded by
the same shared secret as the marketing tick and needs no manager JWT."""

from types import SimpleNamespace

from pydantic import SecretStr


def _patch_secret(monkeypatch, value: str):
    monkeypatch.setattr(
        "app.conversation.router.get_settings",
        lambda: SimpleNamespace(marketing_tick_secret=SecretStr(value)),
    )


async def test_cart_tick_503_when_secret_unconfigured(client, monkeypatch):
    _patch_secret(monkeypatch, "")
    resp = await client.post("/api/v1/conversations/cart-tick")
    assert resp.status_code == 503


async def test_cart_tick_403_on_wrong_secret(client, monkeypatch):
    _patch_secret(monkeypatch, "topsecret")
    resp = await client.post(
        "/api/v1/conversations/cart-tick", headers={"X-Tick-Secret": "nope"}
    )
    assert resp.status_code == 403


async def test_cart_tick_runs_with_correct_secret(client, monkeypatch):
    _patch_secret(monkeypatch, "topsecret")
    resp = await client.post(
        "/api/v1/conversations/cart-tick", headers={"X-Tick-Secret": "topsecret"}
    )
    assert resp.status_code == 200
    assert resp.json() == {"nudged": 0}
