"""The tills read the VAT rate from the server instead of hardcoding 5%.

Both till screens carried `const VAT_RATE = 0.05` and divided by a literal 1.05,
so changing the rate on the Tax profile page moved the tax records while the
customer's printed bill went on saying 5%: one sale, two VAT figures.
"""

import pytest


@pytest.mark.anyio
async def test_defaults_to_the_uae_standard(client, auth_headers):
    r = await client.get("/api/v1/orders/tax-config", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["vat_percent"] == 5.0
    assert body["pricing_mode"] == "exclusive"


@pytest.mark.anyio
async def test_reports_the_saved_rate_and_mode(client, auth_headers):
    patch = await client.patch(
        "/api/v1/compliance/tax-settings",
        headers=auth_headers,
        json={"default_vat_rate": 0.10, "tax_pricing_mode": "inclusive"},
    )
    assert patch.status_code == 200, patch.text

    r = await client.get("/api/v1/orders/tax-config", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["vat_percent"] == pytest.approx(10.0)
    assert body["pricing_mode"] == "inclusive"


@pytest.mark.anyio
async def test_a_genuine_zero_rate_survives(client, auth_headers):
    await client.patch(
        "/api/v1/compliance/tax-settings",
        headers=auth_headers,
        json={"default_vat_rate": 0.0},
    )
    r = await client.get("/api/v1/orders/tax-config", headers=auth_headers)
    assert r.json()["vat_percent"] == 0.0


@pytest.mark.anyio
async def test_route_is_not_swallowed_by_the_order_id_path(client, auth_headers):
    """"/orders/tax-config" must not be parsed as order id "tax-config"."""
    r = await client.get("/api/v1/orders/tax-config", headers=auth_headers)
    assert r.status_code == 200
    assert "vat_rate" in r.json()


@pytest.mark.anyio
async def test_requires_a_token(client):
    r = await client.get("/api/v1/orders/tax-config")
    assert r.status_code in (401, 403)
