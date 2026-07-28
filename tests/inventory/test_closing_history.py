"""The End of day snapshot button wrote data no screen could read.

A row per ingredient per day was going into stock_closing_snapshots, and every
existing reader took a single target_date — so seeing a trend meant one request
per day and the UI simply never asked. Pressing the button looked like nothing
happened.
"""
from decimal import Decimal

import pytest


@pytest.mark.anyio
async def test_history_is_empty_before_any_snapshot(client, auth_headers):
    resp = await client.get(
        "/api/v1/ingredients/reports/closing-history", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.anyio
async def test_snapshot_shows_up_in_history_with_its_value(client, auth_headers):
    for name, stock, cost in (("Rice", "30.000", "20.0000"), ("Chicken", "30.000", "10.0000")):
        created = await client.post(
            "/api/v1/ingredients",
            json={
                "name": name, "unit": "kg", "current_stock": stock,
                "low_stock_threshold": "5.000", "cost_per_unit_aed": cost,
            },
            headers=auth_headers,
        )
        assert created.status_code == 201

    snap = await client.post(
        "/api/v1/ingredients/reports/closing-snapshot", headers=auth_headers
    )
    assert snap.status_code == 200

    resp = await client.get(
        "/api/v1/ingredients/reports/closing-history", headers=auth_headers
    )
    rows = resp.json()
    assert len(rows) == 1
    # 30 x 20 + 30 x 10 = 900. The whole point of the row is the money.
    assert Decimal(str(rows[0]["total_value_aed"])) == Decimal("900.00")
    assert rows[0]["items"] == 2


@pytest.mark.anyio
async def test_pressing_it_twice_in_a_day_does_not_duplicate(client, auth_headers):
    """Idempotent per day. Two presses must not read as two days of closing."""
    await client.post(
        "/api/v1/ingredients",
        json={"name": "Flour", "unit": "kg", "current_stock": "10.000",
              "low_stock_threshold": "1.000", "cost_per_unit_aed": "2.0000"},
        headers=auth_headers,
    )
    await client.post("/api/v1/ingredients/reports/closing-snapshot", headers=auth_headers)
    await client.post("/api/v1/ingredients/reports/closing-snapshot", headers=auth_headers)

    rows = (
        await client.get(
            "/api/v1/ingredients/reports/closing-history", headers=auth_headers
        )
    ).json()
    assert len(rows) == 1
    assert Decimal(str(rows[0]["total_value_aed"])) == Decimal("20.00")


@pytest.mark.anyio
async def test_another_restaurant_sees_none_of_it(client, auth_headers):
    """Closing valuation is exactly the figure a competitor would want."""
    await client.post(
        "/api/v1/ingredients",
        json={"name": "Saffron", "unit": "g", "current_stock": "5.000",
              "low_stock_threshold": "1.000", "cost_per_unit_aed": "100.0000"},
        headers=auth_headers,
    )
    await client.post("/api/v1/ingredients/reports/closing-snapshot", headers=auth_headers)

    await client.post(
        "/api/v1/auth/signup",
        json={"name": "Other Cafe", "email": "other@cafe.ae", "phone": "+971509999999",
              "password": "hunter2!", "lat": 25.2, "lng": 55.2},
    )
    other = await client.post(
        "/api/v1/auth/login",
        json={"email": "other@cafe.ae", "password": "hunter2!"},
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    resp = await client.get(
        "/api/v1/ingredients/reports/closing-history", headers=other_headers
    )
    assert resp.status_code == 200
    assert resp.json() == []

    # Positive control: the owner still sees their own, so an empty list above
    # means isolation and not a broken endpoint.
    mine = await client.get(
        "/api/v1/ingredients/reports/closing-history", headers=auth_headers
    )
    assert len(mine.json()) == 1
