# tests/identity/test_signup_login.py
SIGNUP = {
    "name": "Biryani House",
    "phone": "+971501234567",
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


async def test_signup_duplicate_phone_409(client):
    await client.post("/api/v1/auth/signup", json=SIGNUP)
    resp = await client.post("/api/v1/auth/signup", json=SIGNUP)
    assert resp.status_code == 409


async def test_login_returns_token_and_me_works(client):
    await client.post("/api/v1/auth/signup", json=SIGNUP)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"phone": "+971501234567", "password": "hunter2!"},
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]

    me = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["name"] == "Biryani House"


async def test_login_wrong_password_401(client):
    await client.post("/api/v1/auth/signup", json=SIGNUP)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"phone": "+971501234567", "password": "nope"},
    )
    assert resp.status_code == 401


async def test_me_without_token_401(client):
    resp = await client.get("/api/v1/me")
    assert resp.status_code == 401
