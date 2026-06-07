"""Tests for POST /api/v1/dispatch/trigger (spec §4.3)."""


async def test_dispatch_trigger_requires_auth(client):
    """Unauthenticated request must be rejected with 401."""
    resp = await client.post("/api/v1/dispatch/trigger")
    assert resp.status_code == 401


async def test_dispatch_trigger_runs_and_returns_ok(client, auth_headers):
    """Authenticated request runs the dispatch engine and returns success."""
    resp = await client.post("/api/v1/dispatch/trigger", headers=auth_headers)
    # Engine runs fine even with no ready orders — returns dispatch summary.
    assert resp.status_code == 200
    body = resp.json()
    assert "assigned" in body
    assert "unassigned" in body
    assert "needs_retry" in body
    # With no ready orders both counts should be zero.
    assert body["assigned"] == 0
    assert body["unassigned"] == 0
