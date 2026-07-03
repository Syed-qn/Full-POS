# tests/ordering/test_customer_profile.py
from datetime import datetime
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


async def test_nameless_customer_shows_receiver_name(client, db_session, restaurant):
    """A customer with no name on file falls back to their address receiver name
    in both the list and the profile (WhatsApp only collects a receiver name)."""
    customer = Customer(
        restaurant_id=restaurant.id, phone="+971509998888",
        name=None, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    db_session.add(CustomerAddress(
        customer_id=customer.id, room_apartment="12", building="Tower Y",
        receiver_name="Asfer", confirmed=True,
    ))
    await db_session.commit()

    resp = await client.get("/api/v1/ordering/customers", headers=_auth(restaurant.id))
    assert resp.status_code == 200
    listed = next(c for c in resp.json()["items"] if c["phone"] == "+971509998888")
    assert listed["name"] == "Asfer"

    resp = await client.get(
        f"/api/v1/ordering/customers/{customer.id}", headers=_auth(restaurant.id)
    )
    assert resp.json()["name"] == "Asfer"


async def test_recompute_customer_stats_and_endpoints(client, db_session, restaurant):
    """recompute_customer_stats rebuilds the denormalized columns from orders
    (draft excluded from the count, spend = delivered only), and the list +
    profile endpoints read those maintained columns."""
    from app.ordering.service import recompute_customer_stats

    customer = Customer(
        restaurant_id=restaurant.id, phone="+971507776666",
        name="Maya", total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    db_session.add_all([
        Order(
            restaurant_id=restaurant.id, customer_id=customer.id, order_number="R-D1",
            status="delivered", subtotal=Decimal("30.00"), delivery_fee_aed=Decimal("5.00"),
            total=Decimal("35.00"), priority="normal", weather_delay_disclosed=False,
        ),
        Order(
            restaurant_id=restaurant.id, customer_id=customer.id, order_number="R-D2",
            status="draft", subtotal=Decimal("10.00"), delivery_fee_aed=Decimal("0.00"),
            total=Decimal("10.00"), priority="normal", weather_delay_disclosed=False,
        ),
    ])
    await db_session.flush()

    await recompute_customer_stats(db_session, customer.id)
    await db_session.commit()
    await db_session.refresh(customer)
    assert customer.total_orders == 1  # draft excluded
    assert customer.total_spend == Decimal("35.00")  # delivered only

    resp = await client.get("/api/v1/ordering/customers", headers=_auth(restaurant.id))
    row = next(c for c in resp.json()["items"] if c["phone"] == "+971507776666")
    assert row["total_orders"] == 1
    assert Decimal(str(row["total_spend"])) == Decimal("35.00")

    resp = await client.get(
        f"/api/v1/ordering/customers/{customer.id}", headers=_auth(restaurant.id)
    )
    body = resp.json()
    assert body["total_orders"] == 1
    assert Decimal(str(body["total_spend"])) == Decimal("35.00")


async def test_advance_delivery_updates_customer_spend(db_session, restaurant):
    """Delivering an order refreshes the customer's denormalized stats (the
    delivery path bypasses fsm.transition, so it has its own recompute hook)."""
    from app.dispatch.delivery import advance_delivery

    customer = Customer(
        restaurant_id=restaurant.id, phone="+971502223333",
        name="Sami", total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=customer.id, order_number="R-A1",
        status="arriving", subtotal=Decimal("40.00"), delivery_fee_aed=Decimal("10.00"),
        total=Decimal("50.00"), priority="normal", weather_delay_disclosed=False,
    )
    db_session.add(order)
    await db_session.flush()

    await advance_delivery(db_session, order_id=order.id, to_status="delivered")
    await db_session.commit()
    await db_session.refresh(customer)
    assert customer.total_orders == 1
    assert customer.total_spend == Decimal("50.00")


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


def test_format_usual_order_time_buckets():
    """Circular mean keeps a tight evening cluster in the Evenings band and
    averages times straddling midnight to late night, not noon."""
    from app.ordering.service import _format_usual_order_time

    assert _format_usual_order_time([]) is None
    # 20:00 + 20:30 Dubai → Evenings, ~8:15 PM
    evening = _format_usual_order_time([20.0, 20.5])
    assert evening is not None and evening.startswith("Evenings")
    # 23:30 and 00:30 must average to ~00:00 (Late night), not 12:00 (noon).
    wrapped = _format_usual_order_time([23.5, 0.5])
    assert wrapped is not None and wrapped.startswith("Late night")


async def test_profile_reports_usual_order_time(client, db_session, restaurant):
    """Orders placed around 20:00 Dubai (16:00 UTC) surface as an evening habit."""
    customer = Customer(
        restaurant_id=restaurant.id, phone="+971501112222",
        name="Layla", total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    db_session.add_all([
        Order(
            restaurant_id=restaurant.id, customer_id=customer.id,
            order_number=f"R-T{i}", status="delivered",
            subtotal=Decimal("20.00"), delivery_fee_aed=Decimal("0.00"),
            total=Decimal("20.00"), priority="normal", weather_delay_disclosed=False,
            created_at=datetime(2026, 6, 20 + i, 16, 0),  # naive UTC → 20:00 Dubai
        )
        for i in range(2)
    ])
    await db_session.flush()
    from app.ordering.service import recompute_customer_stats

    await recompute_customer_stats(db_session, customer.id)
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/ordering/customers/{customer.id}", headers=_auth(restaurant.id)
    )
    assert resp.status_code == 200
    assert resp.json()["usual_order_time"].startswith("Evenings")


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


async def test_delete_customer_removes_record(client, db_session, restaurant):
    customer, addr = await _seed_customer(db_session, restaurant.id)

    resp = await client.delete(
        f"/api/v1/ordering/customers/{customer.id}",
        headers=_auth(restaurant.id),
    )
    assert resp.status_code == 204

    profile_resp = await client.get(
        f"/api/v1/ordering/customers/{customer.id}",
        headers=_auth(restaurant.id),
    )
    assert profile_resp.status_code == 404


async def test_delete_customer_linked_to_order_returns_409(client, db_session, restaurant):
    customer, _addr = await _seed_customer(db_session, restaurant.id)

    order = Order(
        restaurant_id=restaurant.id, customer_id=customer.id,
        order_number="R1-CUST", status="delivered",
        subtotal=Decimal("22.00"), delivery_fee_aed=Decimal("0.00"),
        total=Decimal("22.00"),
    )
    db_session.add(order)
    await db_session.commit()

    resp = await client.delete(
        f"/api/v1/ordering/customers/{customer.id}",
        headers=_auth(restaurant.id),
    )
    assert resp.status_code == 409
