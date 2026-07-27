"""Shared test helpers."""


async def store_key(client, auth_headers) -> str:
    """Branch key for the restaurant behind ``auth_headers``.

    Staff sign-in is scoped to one restaurant, so every /staff/login body needs
    the store the terminal is paired with. Codes are random per restaurant, so
    tests read the real one back instead of hard-coding it.
    """
    resp = await client.get("/api/v1/staff/store-identity", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["store_code"]
