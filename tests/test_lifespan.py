"""Tests for app startup / shutdown lifespan and the /health endpoint."""


async def test_app_health_check_via_client(client):
    """/health returns {"status": "ok"} — confirms the lifespan completed startup."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
