"""Catalog picker: listing must include catalogs SHARED into the business, not
just ones it owns.

A Meta business portfolio holds catalogs on two edges — ``owned_product_catalogs``
and ``client_product_catalogs`` (shared in from another business). Commerce Manager
shows both together, so querying only the owned edge made a real, selectable
catalog invisible in the dashboard picker (prod: the "Lims" portfolio showed two
catalogs in Commerce Manager but only one in ours).
"""

import httpx
import pytest


def _transport(owned: list[dict], client_owned: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/owned_product_catalogs"):
            return httpx.Response(200, json={"data": owned})
        if request.url.path.endswith("/client_product_catalogs"):
            return httpx.Response(200, json={"data": client_owned})
        return httpx.Response(404, json={"error": {"message": "unexpected"}})

    return httpx.MockTransport(handler)


@pytest.mark.anyio
async def test_lists_owned_and_shared_catalogs(monkeypatch):
    from app.identity import meta_embed

    transport = _transport(
        owned=[{"id": "111", "name": "Lims Catalog"}],
        client_owned=[{"id": "222", "name": "Meta Catlog Catalog"}],
    )
    real_client = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(meta_embed.httpx, "AsyncClient", patched)

    cats = await meta_embed.list_owned_catalogs("BIZ1", "tok")
    names = {c["name"] for c in cats}
    assert names == {"Lims Catalog", "Meta Catlog Catalog"}


@pytest.mark.anyio
async def test_dedupes_catalog_present_on_both_edges(monkeypatch):
    from app.identity import meta_embed

    transport = _transport(
        owned=[{"id": "111", "name": "Lims Catalog"}],
        client_owned=[{"id": "111", "name": "Lims Catalog"}],
    )
    real_client = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(meta_embed.httpx, "AsyncClient", patched)

    cats = await meta_embed.list_owned_catalogs("BIZ1", "tok")
    assert [c["id"] for c in cats] == ["111"]


@pytest.mark.anyio
async def test_one_failing_edge_does_not_lose_the_other(monkeypatch):
    """A 400 on the shared edge must not wipe out the owned results."""
    from app.identity import meta_embed

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/owned_product_catalogs"):
            return httpx.Response(200, json={"data": [{"id": "111", "name": "Lims Catalog"}]})
        return httpx.Response(400, json={"error": {"message": "nope"}})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(meta_embed.httpx, "AsyncClient", patched)

    cats = await meta_embed.list_owned_catalogs("BIZ1", "tok")
    assert [c["name"] for c in cats] == ["Lims Catalog"]


# ---------------------------------------------------------------------------
# switch_waba_catalog: a FAILED read must not be read as "no catalog attached".
#
# Prod (La Cafe, Aug 2026): fetch_waba_catalog_id errored (flaky network), returned
# "", so switch_waba_catalog believed nothing was linked, skipped the unlink, and
# went straight to linking. Meta refused with subcode 2388027 "WABA should have
# maximum one product catalogue" — because one WAS attached. Rollback then did
# nothing, since it also thought there was nothing to restore.
# ---------------------------------------------------------------------------

_ALREADY_LINKED = {
    "error": {
        "message": "Invalid parameter",
        "type": "OAuthException",
        "code": 100,
        "error_subcode": 2388027,
        "error_user_title": "WABA should have maximum one product catalogue",
    }
}


def _patch_client(monkeypatch, handler):
    from app.identity import meta_embed

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(meta_embed.httpx, "AsyncClient", patched)
    return meta_embed


@pytest.mark.anyio
async def test_read_failure_is_not_treated_as_no_catalog(monkeypatch):
    """Read errors, then Meta says one is already linked. We must discover the real
    catalog, unlink it, and complete the switch — not give up."""
    state = {"attached": "999", "reads": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/product_catalogs") and request.method == "GET":
            state["reads"] += 1
            if state["reads"] == 1:
                raise httpx.ConnectError("boom")  # transient failure
            return httpx.Response(
                200,
                json={"data": [{"id": state["attached"]}] if state["attached"] else []},
            )
        if path.endswith("/product_catalogs") and request.method == "DELETE":
            state["attached"] = ""
            return httpx.Response(200, json={"success": True})
        if path.endswith("/product_catalogs") and request.method == "POST":
            if state["attached"]:
                return httpx.Response(400, json=_ALREADY_LINKED)
            state["attached"] = "111"
            return httpx.Response(200, json={"success": True})
        return httpx.Response(404, json={"error": {"message": "unexpected"}})

    meta_embed = _patch_client(monkeypatch, handler)
    ok = await meta_embed.switch_waba_catalog("WABA1", "111", "tok")
    assert ok is True
    assert state["attached"] == "111"


@pytest.mark.anyio
async def test_never_unlinks_when_the_attached_catalog_is_unknown(monkeypatch):
    """If we can never confirm what is attached, fail loudly rather than deleting
    a link we cannot identify."""
    calls = {"delete": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            raise httpx.ConnectError("still down")
        if request.method == "DELETE":
            calls["delete"] += 1
            return httpx.Response(200, json={"success": True})
        return httpx.Response(400, json=_ALREADY_LINKED)

    meta_embed = _patch_client(monkeypatch, handler)
    ok = await meta_embed.switch_waba_catalog("WABA1", "111", "tok")
    assert ok is False
    assert calls["delete"] == 0


@pytest.mark.anyio
async def test_switch_is_idempotent_when_already_linked(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "111"}]})
        raise AssertionError("must not mutate when already the connected catalog")

    meta_embed = _patch_client(monkeypatch, handler)
    assert await meta_embed.switch_waba_catalog("WABA1", "111", "tok") is True
