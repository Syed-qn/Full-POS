"""The Inventory screen has no Refresh button, so the push must actually fire.

A missing announcement here is invisible in the UI — the page simply shows
yesterday's figures and nobody can tell it is stale, which is the failure mode
removing the button introduced.
"""
import asyncio

import pytest

from app.realtime import bus


@pytest.fixture(autouse=True)
def _memory_backend():
    bus.set_realtime_redis(None)
    bus._local.clear()
    yield
    bus._local.clear()


def _listen(restaurant_id: int) -> asyncio.Queue:
    """Attach an in-process subscriber the way a parked terminal would."""
    q: asyncio.Queue = asyncio.Queue(maxsize=bus._QUEUE_MAX)
    bus._local.setdefault(int(restaurant_id), set()).add(q)
    return q


async def _my_restaurant_id(client, auth_headers) -> int:
    """The id the TOKEN resolves to. The `restaurant` fixture seeds a different
    row than `auth_headers` signs up, so using it would listen on a channel
    nothing publishes to and the test would pass for the wrong reason."""
    resp = await client.get("/api/v1/me", headers=auth_headers)
    assert resp.status_code == 200
    return int(resp.json()["id"])


async def _drain(q: asyncio.Queue) -> list[dict]:
    """Events are published from a fire-and-forget task, so yield first."""
    for _ in range(10):
        if not q.empty():
            break
        await asyncio.sleep(0.02)
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


@pytest.mark.anyio
async def test_restock_announces_inventory_to_this_branch(client, auth_headers):
    created = await client.post(
        "/api/v1/ingredients",
        json={"name": "Basmati", "unit": "kg", "current_stock": "1.000",
              "low_stock_threshold": "5.000"},
        headers=auth_headers,
    )
    assert created.status_code == 201
    ingredient_id = created.json()["id"]

    rid = await _my_restaurant_id(client, auth_headers)
    q = _listen(rid)
    resp = await client.post(
        f"/api/v1/ingredients/{ingredient_id}/restock",
        json={"quantity": "4.000"},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    events = await _drain(q)
    assert [e["topic"] for e in events] == ["inventory"]
    assert events[0]["restaurant_id"] == rid
    # Content stays off the wire: the terminal refetches through its own
    # authenticated call, so the stream can never widen what it may read.
    assert "current_stock" not in events[0]


@pytest.mark.anyio
async def test_reading_locations_announces_nothing(client, auth_headers):
    """GET /locations commits, because it seeds the default stock areas.

    Announcing there would make every terminal's refetch trigger another
    announcement, and the tills would refetch each other in a loop for as long
    as the page stayed open.
    """
    await client.get("/api/v1/ingredients/locations", headers=auth_headers)  # seed once
    rid = await _my_restaurant_id(client, auth_headers)
    q = _listen(rid)
    resp = await client.get("/api/v1/ingredients/locations", headers=auth_headers)
    assert resp.status_code == 200
    assert await _drain(q) == []


@pytest.mark.anyio
async def test_another_branch_does_not_hear_it(client, auth_headers):
    """The channel is built from the caller's token, never a request field."""
    created = await client.post(
        "/api/v1/ingredients",
        json={"name": "Saffron", "unit": "g", "current_stock": "10.000",
              "low_stock_threshold": "1.000"},
        headers=auth_headers,
    )
    ingredient_id = created.json()["id"]

    rid = await _my_restaurant_id(client, auth_headers)
    other = _listen(rid + 9999)
    mine = _listen(rid)
    resp = await client.post(
        f"/api/v1/ingredients/{ingredient_id}/waste",
        json={"quantity": "1.000", "reason": "spilled"},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    assert [e["topic"] for e in await _drain(mine)] == ["inventory"]
    assert other.empty()


@pytest.mark.anyio
async def test_purchase_order_announces_inventory(client, auth_headers):
    """Receiving goods changes stock, so the stock page must hear about it."""
    ingredient_id = (await client.post(
        "/api/v1/ingredients",
        json={"name": "Chilli", "unit": "kg", "current_stock": "0.000",
              "low_stock_threshold": "1.000"},
        headers=auth_headers,
    )).json()["id"]
    vendor = await client.post(
        "/api/v1/vendors", json={"name": "Spice Co"}, headers=auth_headers
    )
    assert vendor.status_code == 201

    rid = await _my_restaurant_id(client, auth_headers)
    q = _listen(rid)
    po = await client.post(
        "/api/v1/purchase-orders",
        json={
            "vendor_id": vendor.json()["id"],
            "lines": [
                {"ingredient_id": ingredient_id, "qty_ordered": "5.000",
                 "unit_cost_aed": "2.0000"}
            ],
        },
        headers=auth_headers,
    )
    assert po.status_code == 201
    assert [e["topic"] for e in await _drain(q)] == ["inventory"]
