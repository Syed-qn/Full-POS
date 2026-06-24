"""Partner API: key management (manager JWT) + read-only customer pulls (X-API-Key).

Covers the key lifecycle, auth on the partner surface (missing/invalid/revoked),
tenant isolation, and incremental sync.
"""
import pytest
from sqlalchemy import select

from app.identity.models import Restaurant
from app.ordering.models import Customer
from app.partner.keys import KEY_PREFIX, generate_api_key, hash_api_key

pytestmark = pytest.mark.asyncio


async def _restaurant_id(db_session, phone: str) -> int:
    r = (
        await db_session.scalars(select(Restaurant).where(Restaurant.phone == phone))
    ).first()
    return r.id


async def _seed_customer(db_session, *, restaurant_id: int, phone: str, name: str | None) -> None:
    db_session.add(Customer(restaurant_id=restaurant_id, phone=phone, name=name))
    await db_session.commit()


def _key_header(key: str) -> dict:
    return {"X-API-Key": key}


# ── key generation unit ──────────────────────────────────────────────────────
def test_generate_api_key_shape():
    full, prefix, key_hash = generate_api_key()
    assert full.startswith(KEY_PREFIX)
    assert full.startswith(prefix)  # prefix is a leading fragment of the full key
    assert key_hash == hash_api_key(full)
    assert len(key_hash) == 64  # sha256 hex
    # Two mints never collide.
    assert generate_api_key()[0] != full


# ── key management (manager JWT) ─────────────────────────────────────────────
async def test_key_lifecycle_create_list_revoke(client, auth_headers):
    created = await client.post(
        "/api/v1/api-keys", json={"label": "Acme POS"}, headers=auth_headers
    )
    assert created.status_code == 201
    body = created.json()
    assert body["api_key"].startswith(KEY_PREFIX)  # full key shown ONCE
    assert body["label"] == "Acme POS"
    key_id = body["id"]

    listed = await client.get("/api/v1/api-keys", headers=auth_headers)
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["key_prefix"] == body["key_prefix"]
    assert "api_key" not in rows[0]  # never exposes the secret again

    revoked = await client.delete(f"/api/v1/api-keys/{key_id}", headers=auth_headers)
    assert revoked.status_code == 204
    after = (await client.get("/api/v1/api-keys", headers=auth_headers)).json()
    assert after[0]["revoked_at"] is not None


async def test_revoke_unknown_key_404(client, auth_headers):
    resp = await client.delete("/api/v1/api-keys/999999", headers=auth_headers)
    assert resp.status_code == 404


async def test_create_key_requires_manager_jwt(client):
    resp = await client.post("/api/v1/api-keys", json={"label": "x"})
    assert resp.status_code == 401


# ── partner data pulls (X-API-Key) ───────────────────────────────────────────
async def test_partner_customers_missing_or_bad_key_401(client, auth_headers):
    # auth_headers ensures a restaurant exists; no/invalid X-API-Key is rejected.
    assert (await client.get("/api/v1/partner/customers")).status_code == 401
    bad = await client.get("/api/v1/partner/customers", headers=_key_header("rk_live_nope"))
    assert bad.status_code == 401


async def test_partner_customers_pull(client, auth_headers, db_session):
    rid = await _restaurant_id(db_session, "+971501234567")
    await _seed_customer(db_session, restaurant_id=rid, phone="+971500000001", name="Ali")
    await _seed_customer(db_session, restaurant_id=rid, phone="+971500000002", name=None)

    key = (await client.post(
        "/api/v1/api-keys", json={"label": "POS"}, headers=auth_headers
    )).json()["api_key"]

    resp = await client.get("/api/v1/partner/customers", headers=_key_header(key))
    assert resp.status_code == 200
    body = resp.json()
    phones = {c["phone"] for c in body["items"]}
    assert phones == {"+971500000001", "+971500000002"}
    assert body["next_updated_since"] is not None


async def test_revoked_key_cannot_pull(client, auth_headers, db_session):
    rid = await _restaurant_id(db_session, "+971501234567")
    await _seed_customer(db_session, restaurant_id=rid, phone="+971500000003", name="Sara")
    created = (await client.post(
        "/api/v1/api-keys", json={"label": "POS"}, headers=auth_headers
    )).json()
    key = created["api_key"]
    # Works before revoke...
    assert (await client.get("/api/v1/partner/customers", headers=_key_header(key))).status_code == 200
    await client.delete(f"/api/v1/api-keys/{created['id']}", headers=auth_headers)
    # ...rejected after.
    assert (await client.get("/api/v1/partner/customers", headers=_key_header(key))).status_code == 401


async def test_tenant_isolation_key_only_sees_own_customers(client, auth_headers, db_session):
    # Restaurant A (from auth_headers) + its customer + key.
    rid_a = await _restaurant_id(db_session, "+971501234567")
    await _seed_customer(db_session, restaurant_id=rid_a, phone="+971500000010", name="A-cust")
    key_a = (await client.post(
        "/api/v1/api-keys", json={"label": "A"}, headers=auth_headers
    )).json()["api_key"]

    # Restaurant B: fresh signup + login + its own customer + key.
    await client.post("/api/v1/auth/signup", json={
        "name": "Other Diner", "phone": "+971509999999",
        "password": "hunter2!", "lat": 25.1, "lng": 55.2,
    })
    token_b = (await client.post("/api/v1/auth/login", json={
        "phone": "+971509999999", "password": "hunter2!",
    })).json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}
    rid_b = await _restaurant_id(db_session, "+971509999999")
    await _seed_customer(db_session, restaurant_id=rid_b, phone="+971500000020", name="B-cust")
    key_b = (await client.post(
        "/api/v1/api-keys", json={"label": "B"}, headers=headers_b
    )).json()["api_key"]

    a_phones = {c["phone"] for c in (await client.get(
        "/api/v1/partner/customers", headers=_key_header(key_a))).json()["items"]}
    b_phones = {c["phone"] for c in (await client.get(
        "/api/v1/partner/customers", headers=_key_header(key_b))).json()["items"]}

    assert "+971500000010" in a_phones and "+971500000020" not in a_phones
    assert "+971500000020" in b_phones and "+971500000010" not in b_phones
