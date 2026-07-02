# tests/identity/test_signup_login.py
SIGNUP = {
    "name": "Biryani House",
    "email": "owner@biryani.ae",
    "password": "hunter2!",
    "lat": 25.2048,
    "lng": 55.2708,
}


async def test_signup_creates_restaurant_with_default_settings(client):
    resp = await client.post("/api/v1/auth/signup", json=SIGNUP)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Biryani House"
    assert body["settings"]["max_radius_km"] == 10
    assert "password" not in body and "password_hash" not in body


async def test_signup_duplicate_email_409(client):
    await client.post("/api/v1/auth/signup", json=SIGNUP)
    resp = await client.post("/api/v1/auth/signup", json=SIGNUP)
    assert resp.status_code == 409


async def test_login_returns_token_and_me_works(client):
    await client.post("/api/v1/auth/signup", json=SIGNUP)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@biryani.ae", "password": "hunter2!"},
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]

    me = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["name"] == "Biryani House"


async def test_login_still_returns_token_when_template_bootstrap_fails(
    client, monkeypatch
):
    async def fail_template_bootstrap(*args, **kwargs):
        raise RuntimeError("template provider unavailable")

    monkeypatch.setattr(
        "app.whatsapp.templates.ensure_utility_templates", fail_template_bootstrap
    )

    await client.post("/api/v1/auth/signup", json=SIGNUP)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@biryani.ae", "password": "hunter2!"},
    )

    assert resp.status_code == 200
    assert resp.json()["access_token"]


async def test_login_wrong_password_401(client):
    await client.post("/api/v1/auth/signup", json=SIGNUP)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@biryani.ae", "password": "nope"},
    )
    assert resp.status_code == 401


async def test_me_without_token_401(client):
    resp = await client.get("/api/v1/me")
    assert resp.status_code == 401


async def test_signup_rejects_out_of_range_coordinates(client):
    bad = {**SIGNUP, "lat": 999.0}
    resp = await client.post("/api/v1/auth/signup", json=bad)
    assert resp.status_code == 422


async def test_me_with_expired_token_401(client):
    import jwt as pyjwt
    from datetime import datetime, timedelta, timezone

    from app.config import get_settings

    s = get_settings()
    expired = pyjwt.encode(
        {"sub": "1", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        s.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    resp = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401


async def test_me_with_wrong_scheme_401(client):
    resp = await client.get("/api/v1/me", headers={"Authorization": "Token abc123"})
    assert resp.status_code == 401


async def test_me_with_missing_sub_token_401(client):
    import jwt as pyjwt
    from datetime import datetime, timedelta, timezone

    from app.config import get_settings

    s = get_settings()
    token = pyjwt.encode(
        {"exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        s.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    resp = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
