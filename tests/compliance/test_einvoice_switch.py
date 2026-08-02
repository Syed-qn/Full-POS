"""The e-invoicing switch actually switches something off.

It was stored, echoed back to the readiness panel, and checked nowhere: ticking
or unticking it changed nothing about what Transmit did. Harmless against the
mock provider, but a transmission through an accredited ASP is a legal filing to
the FTA, and an off switch that does not switch anything off is exactly the
control someone reaches for during an incident.
"""

import pytest


async def _set_enabled(client, auth_headers, enabled: bool):
    r = await client.patch(
        "/api/v1/compliance/tax-settings",
        headers=auth_headers,
        json={"e_invoice_enabled": enabled, "trn": "100123456700003", "legal_name": "X LLC"},
    )
    assert r.status_code == 200, r.text


@pytest.mark.anyio
async def test_transmit_refused_while_switched_off(client, auth_headers, seed_biryani_menu):
    await _set_enabled(client, auth_headers, False)

    resp = await client.post(
        "/api/v1/compliance/e-invoice/transmit",
        headers=auth_headers,
        json={"order_id": 1},
    )
    assert resp.status_code == 409, resp.text
    assert "switched off" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_switching_it_on_gets_past_the_guard(client, auth_headers):
    await _set_enabled(client, auth_headers, True)

    resp = await client.post(
        "/api/v1/compliance/e-invoice/transmit",
        headers=auth_headers,
        json={"order_id": 999999},
    )
    # Past the switch, so the failure is now about the missing order rather than
    # the guard. 409 here would mean the switch still blocks when it should not.
    assert resp.status_code == 404, resp.text
