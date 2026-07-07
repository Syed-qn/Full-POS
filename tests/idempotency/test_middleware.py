# tests/idempotency/test_middleware.py
import pytest


@pytest.mark.anyio
async def test_duplicate_idempotency_key_returns_cached_response(
    client, auth_headers, restaurant
):
    headers = {**auth_headers, "Idempotency-Key": "test-key-123"}
    payload = {"name": "Rider One", "phone": "+971500000001"}

    first = await client.post("/api/v1/riders", json=payload, headers=headers)
    assert first.status_code == 201
    first_body = first.json()

    second = await client.post("/api/v1/riders", json=payload, headers=headers)
    assert second.status_code == 201
    assert second.json() == first_body  # replay returns the SAME rider, not a second one

    # sanity: no second rider was actually created
    listing = await client.get("/api/v1/riders", headers=auth_headers)
    assert len(listing.json()) == 1


@pytest.mark.anyio
async def test_different_idempotency_key_creates_second_resource(
    client, auth_headers, restaurant
):
    payload = {"name": "Rider Two", "phone": "+971500000002"}

    first = await client.post(
        "/api/v1/riders",
        json=payload,
        headers={**auth_headers, "Idempotency-Key": "key-a"},
    )
    second = await client.post(
        "/api/v1/riders",
        json={**payload, "phone": "+971500000003"},
        headers={**auth_headers, "Idempotency-Key": "key-b"},
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]


@pytest.mark.anyio
async def test_missing_idempotency_key_is_not_deduped(client, auth_headers, restaurant):
    payload = {"name": "Rider Three", "phone": "+971500000004"}

    first = await client.post("/api/v1/riders", json=payload, headers=auth_headers)
    second = await client.post(
        "/api/v1/riders",
        json={**payload, "phone": "+971500000005"},
        headers=auth_headers,
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
