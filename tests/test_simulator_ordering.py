"""
End-to-end smoke test: drive a full order conversation via POST /simulator/send
and GET /simulator/messages (Phase 2 simulator endpoints).
"""
from decimal import Decimal

import pytest

from app.identity.models import Restaurant


@pytest.fixture
async def restaurant(db_session) -> Restaurant:
    """Seed the restaurant the simulator resolves by phone."""
    row = Restaurant(
        name="Sim Restaurant",
        phone="+97141234567",
        password_hash="x",
        lat=25.2048,
        lng=55.2708,
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def _seed_full_menu(db_session, restaurant_id):
    from app.menu.models import Dish, Menu
    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=110,
        name="Chicken Biryani", price_aed=Decimal("22.00"),
        category="Rice", is_available=True, name_normalized="chicken biryani",
    ))
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=201,
        name="Mutton Karahi", price_aed=Decimal("35.00"),
        category="Curries", is_available=True, name_normalized="mutton karahi",
    ))
    await db_session.commit()


async def test_simulator_greeting_returns_menu(client, db_session, restaurant):
    """POST /simulator/send with 'hi' → bot replies with menu."""
    await _seed_full_menu(db_session, restaurant.id)

    resp = await client.post(
        "/simulator/send",
        json={
            "from_phone": "+971509111001",
            "restaurant_phone": "+97141234567",
            "text": "hi",
        },
    )
    assert resp.status_code == 200

    # Poll messages sent to this phone
    msgs_resp = await client.get("/simulator/messages")
    assert msgs_resp.status_code == 200
    messages = msgs_resp.json()
    bodies = [m.get("payload", {}).get("body", "") for m in messages]
    assert any("Chicken Biryani" in b for b in bodies)


async def test_simulator_order_dish_gets_confirmation(client, db_session, restaurant):
    """Greeting then dish name → confirmation message contains dish name."""
    await _seed_full_menu(db_session, restaurant.id)

    await client.post(
        "/simulator/send",
        json={
            "from_phone": "+971509111002",
            "restaurant_phone": "+97141234567",
            "text": "hi",
        },
    )

    resp = await client.post(
        "/simulator/send",
        json={
            "from_phone": "+971509111002",
            "restaurant_phone": "+97141234567",
            "text": "chicken biryani",
        },
    )
    assert resp.status_code == 200

    msgs_resp = await client.get("/simulator/messages")
    messages = msgs_resp.json()
    bodies = [m.get("payload", {}).get("body", "") for m in messages]
    assert any("Chicken Biryani" in b or "110" in b for b in bodies)


async def _drive_to_address_capture(client, db_session, restaurant, phone):
    """hi -> add a dish -> done, leaving the conversation at address_capture."""
    await _seed_full_menu(db_session, restaurant.id)
    for text in ("hi", "chicken biryani", "done"):
        await client.post(
            "/simulator/send",
            json={
                "from_phone": phone,
                "restaurant_phone": "+97141234567",
                "text": text,
            },
        )
    await client.get("/simulator/messages")  # drain


async def test_simulator_button_reply_reaches_engine(client, db_session, restaurant):
    """A button_reply payload reaches the engine as a BUTTON_REPLY inbound (200)."""
    from sqlalchemy import select

    from app.webhook.models import WebhookEvent

    resp = await client.post(
        "/simulator/send",
        json={
            "from_phone": "+971509111010",
            "restaurant_phone": "+97141234567",
            "button_reply": {"id": "confirm_order", "title": "Confirm order"},
        },
    )
    assert resp.status_code == 200

    event = (
        await db_session.execute(
            select(WebhookEvent).order_by(WebhookEvent.id.desc())
        )
    ).scalars().first()
    assert event.payload["type"] == "button_reply"
    assert event.payload["id"] == "confirm_order"


async def test_simulator_location_drives_address_flow(client, db_session, restaurant):
    """An in-radius location at address_capture -> bot asks for room/building."""
    phone = "+971509111011"
    await _drive_to_address_capture(client, db_session, restaurant, phone)

    resp = await client.post(
        "/simulator/send",
        json={
            "from_phone": phone,
            "restaurant_phone": "+97141234567",
            "location": {"latitude": 25.2048, "longitude": 55.2708},
        },
    )
    assert resp.status_code == 200

    messages = (await client.get("/simulator/messages")).json()
    bodies = [m.get("payload", {}).get("body", "") for m in messages]
    assert any("room/apartment" in b or "building" in b for b in bodies)


async def test_simulator_send_requires_exactly_one_payload(client, db_session, restaurant):
    """422 when none or multiple of text/button_reply/location are set."""
    # none
    resp = await client.post(
        "/simulator/send",
        json={"from_phone": "+971509111012", "restaurant_phone": "+97141234567"},
    )
    assert resp.status_code == 422

    # multiple
    resp = await client.post(
        "/simulator/send",
        json={
            "from_phone": "+971509111012",
            "restaurant_phone": "+97141234567",
            "text": "hi",
            "location": {"latitude": 25.2, "longitude": 55.2},
        },
    )
    assert resp.status_code == 422
