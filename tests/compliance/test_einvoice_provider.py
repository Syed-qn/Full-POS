"""An unknown ASP provider must refuse, not quietly file through the mock.

`get_asp()` took a provider name and returned MockEInvoiceASP regardless. The day
an accredited ASP is contracted and `asp_provider` is set to their name, every
transmission would still have gone to the mock, while the stored row recorded
that provider, status "accepted", and a fabricated MOCK-AE reference. Nothing
filed with the FTA; everything on screen saying filed.
"""

import pytest

from app.compliance.einvoice import MockEInvoiceASP, UnknownASPError, get_asp


def test_mock_still_resolves():
    assert isinstance(get_asp("mock"), MockEInvoiceASP)
    assert isinstance(get_asp(""), MockEInvoiceASP)


def test_unknown_provider_refuses_instead_of_faking_success():
    with pytest.raises(UnknownASPError) as exc:
        get_asp("cleartax")
    assert "cleartax" in str(exc.value)
    assert "Nothing was transmitted" in str(exc.value)


@pytest.mark.anyio
async def test_transmit_with_unbuilt_provider_returns_422_and_stores_nothing(
    client, auth_headers, seed_biryani_menu
):
    r = await client.patch(
        "/api/v1/compliance/tax-settings",
        headers=auth_headers,
        json={
            "e_invoice_enabled": True,
            "trn": "100123456700003",
            "legal_name": "X LLC",
            "asp_provider": "pagero",
        },
    )
    assert r.status_code == 200, r.text

    resp = await client.post(
        "/api/v1/compliance/e-invoice/transmit",
        headers=auth_headers,
        json={"order_id": 1},
    )
    assert resp.status_code == 422, resp.text
    assert "pagero" in resp.json()["detail"]

    # No row may be left behind claiming a filing happened.
    rows = await client.get(
        "/api/v1/compliance/e-invoice/transmissions", headers=auth_headers
    )
    assert rows.status_code == 200
    assert all(t["asp_provider"] != "pagero" for t in rows.json())


@pytest.mark.anyio
async def test_readiness_speaks_in_sentences(client, auth_headers):
    await client.patch(
        "/api/v1/compliance/tax-settings",
        headers=auth_headers,
        json={"trn": None, "legal_name": None, "e_invoice_enabled": False},
    )
    r = await client.get("/api/v1/compliance/e-invoice/readiness", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"] == "Not ready to send yet."
    joined = " ".join(body["blockers"])
    assert "TRN" in joined
    assert "legal name" in joined
    assert "Switch e-invoicing on" in joined
    # The mock is never a live filing route, however complete the settings are.
    assert body["is_live"] is False


@pytest.mark.anyio
async def test_readiness_says_plainly_that_the_mock_files_nothing(client, auth_headers):
    await client.patch(
        "/api/v1/compliance/tax-settings",
        headers=auth_headers,
        json={
            "trn": "100123456700003",
            "legal_name": "X LLC",
            "e_invoice_enabled": True,
            "asp_provider": "mock",
        },
    )
    r = await client.get("/api/v1/compliance/e-invoice/readiness", headers=auth_headers)
    body = r.json()
    assert body["blockers"] == []
    assert body["is_live"] is False
    assert "nothing reaches the Federal Tax Authority" in body["summary"]
