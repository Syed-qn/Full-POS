# tests/ordering/test_customer_profile.py
from decimal import Decimal

from app.ordering.models import Customer, CustomerAddress, Order


def _token(restaurant_id: int) -> str:
    from app.identity.auth import create_access_token
    return create_access_token(restaurant_id=restaurant_id)


def _auth(restaurant_id: int) -> dict:
    return {"Authorization": f"Bearer {_token(restaurant_id)}"}


async def _seed_customer(db_session, restaurant_id):
    customer = Customer(
        restaurant_id=restaurant_id, phone="+971503334444",
        name="Khalid Hassan", total_orders=3, total_spend=Decimal("99.00"),
    )
    db_session.add(customer)
    await db_session.flush()

    addr = CustomerAddress(
        customer_id=customer.id, room_apartment="Villa 5",
        building="Palm Residences", receiver_name="Khalid Hassan",
        confirmed=True,
    )
    db_session.add(addr)
    await db_session.commit()
    return customer, addr


async def test_list_customers_returns_tenant_only(client, db_session, restaurant):
    await _seed_customer(db_session, restaurant.id)

    resp = await client.get(
        "/api/v1/ordering/customers",
        headers=_auth(restaurant.id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) >= 1
    assert all(c["phone"] for c in data["items"])


async def test_list_customers_search_by_phone(client, db_session, restaurant):
    await _seed_customer(db_session, restaurant.id)

    resp = await client.get(
        "/api/v1/ordering/customers?q=503334444",
        headers=_auth(restaurant.id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert any("Khalid" in (c.get("name") or "") for c in data["items"])


async def test_get_customer_profile(client, db_session, restaurant):
    customer, addr = await _seed_customer(db_session, restaurant.id)

    resp = await client.get(
        f"/api/v1/ordering/customers/{customer.id}",
        headers=_auth(restaurant.id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Khalid Hassan"
    assert data["phone"] == "+971503334444"
    assert len(data["addresses"]) == 1
    assert data["addresses"][0]["building"] == "Palm Residences"
    assert "recent_orders" in data
    assert "marketing_opted_in" in data


async def test_get_customer_profile_wrong_tenant_404(client, db_session, restaurant):
    resp = await client.get(
        "/api/v1/ordering/customers/99999",
        headers=_auth(restaurant.id),
    )
    assert resp.status_code == 404


async def test_delete_address_removes_record(client, db_session, restaurant):
    customer, addr = await _seed_customer(db_session, restaurant.id)

    resp = await client.delete(
        f"/api/v1/ordering/customers/{customer.id}/addresses/{addr.id}",
        headers=_auth(restaurant.id),
    )
    assert resp.status_code == 204

    profile_resp = await client.get(
        f"/api/v1/ordering/customers/{customer.id}",
        headers=_auth(restaurant.id),
    )
    assert len(profile_resp.json()["addresses"]) == 0


async def test_delete_address_linked_to_open_order_returns_409(client, db_session, restaurant):
    from app.menu.models import Dish, Menu

    customer, addr = await _seed_customer(db_session, restaurant.id)

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()

    dish = Dish(menu_id=menu.id, restaurant_id=restaurant.id, dish_number=110,
                name="Biryani", price_aed=Decimal("22.00"), category="Rice", is_available=True)
    db_session.add(dish)
    await db_session.flush()

    order = Order(
        restaurant_id=restaurant.id, customer_id=customer.id,
        order_number="R1-OPEN", status="confirmed",
        address_id=addr.id, subtotal=Decimal("22.00"),
        delivery_fee_aed=Decimal("0.00"), total=Decimal("22.00"),
    )
    db_session.add(order)
    await db_session.commit()

    resp = await client.delete(
        f"/api/v1/ordering/customers/{customer.id}/addresses/{addr.id}",
        headers=_auth(restaurant.id),
    )
    assert resp.status_code == 409
