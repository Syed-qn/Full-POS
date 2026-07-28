"""Controls around a stock count.

The count itself replacing stock on hand is correct and standard. What was
missing was everything around it: WHY it differed, what the difference COST,
and a tolerance tight enough to notice. A 15% default let a real loss through
as normal, and the money side of a variance was never recorded at all — so a
shortfall could be counted away and food cost would look healthy.
"""
from decimal import Decimal

import pytest


async def _ingredient(client, auth_headers, **over):
    body = {
        "name": over.pop("name", "Basmati"),
        "unit": "kg",
        "current_stock": "100.000",
        "low_stock_threshold": "5.000",
        "par_level": "120.000",
        "cost_per_unit_aed": "6.0000",
    }
    body.update(over)
    resp = await client.post("/api/v1/ingredients", json=body, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.anyio
async def test_count_records_why_and_what_it_cost(client, auth_headers):
    ing = await _ingredient(client, auth_headers)

    resp = await client.post(
        f"/api/v1/ingredients/{ing}/stock-count",
        json={"counted_qty": "94.000", "reason_code": "shrinkage", "reason": "walk-in short"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()

    assert Decimal(body["variance"]) == Decimal("-6.000")
    # 6 kg missing at AED 6.00 is a 36 dirham loss. Recording only the kilos is
    # how shrinkage stays invisible in food cost.
    assert Decimal(body["variance_value_aed"]) == Decimal("-36.00")
    assert body["reason_code"] == "shrinkage"

    report = await client.get("/api/v1/ingredients/reports/variance", headers=auth_headers)
    assert report.status_code == 200
    row = report.json()[0]
    assert row["reason_code"] == "shrinkage"
    assert row["reason"] == "walk-in short"
    assert Decimal(row["variance_value_aed"]) == Decimal("-36.00")


@pytest.mark.anyio
async def test_a_count_up_is_a_gain_not_a_loss(client, auth_headers):
    """Sign matters: counting MORE than expected is money found, not lost."""
    ing = await _ingredient(client, auth_headers, name="Chicken")
    resp = await client.post(
        f"/api/v1/ingredients/{ing}/stock-count",
        json={"counted_qty": "105.000", "reason_code": "count_error"},
        headers=auth_headers,
    )
    assert Decimal(resp.json()["variance_value_aed"]) == Decimal("30.00")


@pytest.mark.anyio
async def test_unknown_reason_code_is_kept_as_other_not_rejected(client, auth_headers):
    """A count is real work someone already did. Losing it to a bad string
    would be worse than filing it under "other"."""
    ing = await _ingredient(client, auth_headers, name="Saffron")
    resp = await client.post(
        f"/api/v1/ingredients/{ing}/stock-count",
        json={"counted_qty": "99.000", "reason_code": "not-a-real-code"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["reason_code"] == "other"


@pytest.mark.anyio
async def test_default_tolerance_is_two_percent_not_fifteen(client, auth_headers):
    """The old 15% default would have waved this through as normal."""
    ing = await _ingredient(client, auth_headers, name="Onion")
    resp = await client.post(
        f"/api/v1/ingredients/{ing}/stock-count",
        json={"counted_qty": "95.000"},  # 5% down
        headers=auth_headers,
    )
    body = resp.json()
    assert body["threshold_pct"] == pytest.approx(2.0)
    assert body["flagged"] is True

    alerts = await client.get(
        "/api/v1/ingredients/reports/anomaly-alerts", headers=auth_headers
    )
    assert alerts.status_code == 200
    rows = [a for a in alerts.json() if a["ingredient_id"] == ing]
    assert rows, "a 5% shortfall must raise an alert under a 2% tolerance"
    # Counted DOWN is the theft bucket, not a neutral count difference.
    assert rows[0]["alert_type"] == "theft_loss"


@pytest.mark.anyio
async def test_within_tolerance_does_not_cry_wolf(client, auth_headers):
    """2% has to be a real threshold, not one that flags everything."""
    ing = await _ingredient(client, auth_headers, name="Flour")
    resp = await client.post(
        f"/api/v1/ingredients/{ing}/stock-count",
        json={"counted_qty": "99.000"},  # 1% down
        headers=auth_headers,
    )
    assert resp.json()["flagged"] is False

    alerts = await client.get(
        "/api/v1/ingredients/reports/anomaly-alerts", headers=auth_headers
    )
    assert [a for a in alerts.json() if a["ingredient_id"] == ing] == []


@pytest.mark.anyio
async def test_per_ingredient_tolerance_overrides_the_default(client, auth_headers):
    """A cheap high-turnover item should not page anyone at 2%."""
    ing = await _ingredient(
        client, auth_headers, name="Ice", count_variance_threshold_pct="10.00"
    )
    resp = await client.post(
        f"/api/v1/ingredients/{ing}/stock-count",
        json={"counted_qty": "95.000"},  # 5% down — over the default, under this one
        headers=auth_headers,
    )
    body = resp.json()
    assert body["threshold_pct"] == pytest.approx(10.0)
    assert body["flagged"] is False

    alerts = await client.get(
        "/api/v1/ingredients/reports/anomaly-alerts", headers=auth_headers
    )
    assert [a for a in alerts.json() if a["ingredient_id"] == ing] == []


@pytest.mark.anyio
async def test_count_without_a_reason_still_works(client, auth_headers):
    """Existing callers pass no reason code; they must not start failing."""
    ing = await _ingredient(client, auth_headers, name="Sugar")
    resp = await client.post(
        f"/api/v1/ingredients/{ing}/stock-count",
        json={"counted_qty": "98.000"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["reason_code"] is None
