"""A kitchen login can reach the board and nothing else.

The dashboard hides what a role may not open, but hiding is not a lock: a
kitchen terminal is a browser, and anyone can type a path into it. What
actually stops them is the server refusing the token, which is what this file
pins down — for the screens an operator would mind most, not just one endpoint.
"""
import pytest

from tests.staff.test_rbac import store_key


async def _kitchen_headers(client, auth_headers) -> dict[str, str]:
    created = await client.post(
        "/api/v1/staff",
        json={"name": "Cook Rafi", "role": "kitchen", "pin": "3391"},
        headers=auth_headers,
    )
    staff_id = created.json()["id"]
    login = await client.post(
        "/api/v1/staff/login",
        json={
            "store": await store_key(client, auth_headers),
            "staff_id": staff_id,
            "pin": "3391",
        },
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.anyio
async def test_kitchen_cannot_read_the_manager_screens(client, auth_headers):
    """Stock, costs and the customer book are the ones worth being sure about.

    403 and not 401: the cook IS authenticated, and a 401 would trip the
    frontend auth interceptor and sign a working shift out mid-service.
    """
    kitchen = await _kitchen_headers(client, auth_headers)

    for path in (
        "/api/v1/ingredients",
        "/api/v1/ingredients/reports/actual-vs-theoretical",
        "/api/v1/vendors",
        "/api/v1/purchase-orders",
        "/api/v1/branch-transfers",
    ):
        resp = await client.get(path, headers=kitchen)
        assert resp.status_code == 403, f"{path} answered {resp.status_code}"


@pytest.mark.anyio
async def test_kitchen_cannot_move_stock(client, auth_headers):
    """Reading is one thing; a write from the board would be worse."""
    kitchen = await _kitchen_headers(client, auth_headers)

    resp = await client.post(
        "/api/v1/ingredients",
        json={"name": "Chicken", "unit": "kg", "current_stock": "10.000"},
        headers=kitchen,
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_the_owner_still_sees_all_of_it(client, auth_headers):
    """Positive control. Without this the test above passes just as well on a
    broken endpoint that refuses everybody."""
    for path in ("/api/v1/ingredients", "/api/v1/vendors", "/api/v1/branch-transfers"):
        resp = await client.get(path, headers=auth_headers)
        assert resp.status_code == 200, f"{path} answered {resp.status_code}"


@pytest.mark.anyio
async def test_the_kitchen_can_still_work_its_own_board(client, auth_headers):
    """The lock must not reach the one surface the cook is there to use."""
    kitchen = await _kitchen_headers(client, auth_headers)

    resp = await client.get("/api/v1/kds/stations", headers=kitchen)
    assert resp.status_code == 200, resp.text
