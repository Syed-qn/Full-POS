# tests/audit/test_health.py
"""GET /api/v1/health — external uptime-monitor surface.

Checks DB connectivity via a trivial SELECT 1 and reports overall status,
distinct from the pre-existing bare `/health` liveness ping.
"""


async def test_health_ok_when_db_reachable(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert "timestamp" in body
    # ISO-8601 timestamp, parseable
    from datetime import datetime

    datetime.fromisoformat(body["timestamp"])


async def test_health_no_auth_required(client):
    # An uptime monitor polls anonymously — must not require a bearer token.
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
