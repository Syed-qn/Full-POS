# tests/identity/test_login_rate_limit.py
async def test_login_rate_limited_after_threshold(client, rate_limiter):
    # auth_rate_limit defaults to "5/minute"; the 6th+ attempt from the same
    # ip+phone inside the window is rejected with HTTP 429.
    body = {"email": "rl0@x.co", "password": "wrong"}
    statuses = []
    for _ in range(7):
        r = await client.post("/api/v1/auth/login", json=body)
        statuses.append(r.status_code)
    assert 429 in statuses
    # first 5 are 401 (bad creds) — limiter lets them through, then blocks
    assert statuses[:5] == [401, 401, 401, 401, 401]
    # the 429 response carries Retry-After
    last = await client.post("/api/v1/auth/login", json=body)
    assert last.status_code == 429
    assert "retry-after" in {k.lower() for k in last.headers}


async def test_login_rate_limit_scoped_per_email(client, rate_limiter):
    # Exhaust the bucket for email A.
    for _ in range(7):
        await client.post(
            "/api/v1/auth/login",
            json={"email": "rl-a@x.co", "password": "wrong"},
        )
    # A different email (same client ip) still has its own bucket → not 429.
    other = await client.post(
        "/api/v1/auth/login",
        json={"email": "rl-b@x.co", "password": "wrong"},
    )
    assert other.status_code == 401
