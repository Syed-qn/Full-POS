import pytest

from app.identity.models import Restaurant


@pytest.fixture
async def restaurant(db_session) -> Restaurant:
    row = Restaurant(
        name="Test Restaurant",
        phone="+97141234567",
        password_hash="x",
        lat=25.2048,
        lng=55.2708,
    )
    db_session.add(row)
    await db_session.flush()
    return row


@pytest.fixture
async def active_menu_with_dish(client, auth_headers) -> dict:
    """Active menu with one dish, owned by the ``auth_headers`` tenant (via the real
    HTTP endpoints, same pattern as tests/menu/test_edit.py), for tests that need a
    logged-in restaurant with existing menu data."""
    blank = await client.post("/api/v1/menus/blank", headers=auth_headers)
    assert blank.status_code == 201, blank.text
    menu = blank.json()
    added = await client.post(
        f"/api/v1/menus/{menu['id']}/dishes",
        json={"dish_number": 1, "name": "Chai", "price_aed": "3.00", "category": "Drinks"},
        headers=auth_headers,
    )
    assert added.status_code == 201, added.text
    return menu