async def test_simulator_index_returns_html(client):
    resp = await client.get("/simulator/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


async def test_simulator_send_queues_inbound_and_returns_ok(client):
    await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Test Restaurant",
            "email": "sim@rest.ae",
            "phone": "+97141234567",
            "password": "hunter2!",
            "lat": 25.2048,
            "lng": 55.2708,
        },
    )
    resp = await client.post(
        "/simulator/send",
        json={
            "from_phone": "+971509876543",
            "restaurant_phone": "+97141234567",
            "text": "Hi, I want to order",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_simulator_messages_returns_list(client):
    resp = await client.get("/simulator/messages")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
