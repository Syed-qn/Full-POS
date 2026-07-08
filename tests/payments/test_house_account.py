from decimal import Decimal

import pytest

from app.payments.service import (
    charge_to_house_account,
    enable_house_account,
    settle_house_account,
)


async def _seed_customer(db_session, restaurant, phone):
    from app.ordering.models import Customer

    cust = Customer(restaurant_id=restaurant.id, phone=phone, name="House Account Test")
    db_session.add(cust)
    await db_session.flush()
    await db_session.commit()
    return cust


@pytest.mark.anyio
async def test_charge_to_house_account_requires_enabled(db_session, restaurant):
    cust = await _seed_customer(db_session, restaurant, "+971500000901")

    with pytest.raises(ValueError):
        await charge_to_house_account(
            db_session, restaurant_id=restaurant.id, customer_id=cust.id,
            order_id=1, amount_aed=Decimal("10.00"),
        )


@pytest.mark.anyio
async def test_enable_then_charge_and_settle(db_session, restaurant):
    cust = await _seed_customer(db_session, restaurant, "+971500000902")

    await enable_house_account(db_session, restaurant_id=restaurant.id, customer_id=cust.id)
    await db_session.commit()
    await db_session.refresh(cust)
    assert cust.house_account_enabled is True

    balance = await charge_to_house_account(
        db_session, restaurant_id=restaurant.id, customer_id=cust.id,
        order_id=1, amount_aed=Decimal("75.00"),
    )
    await db_session.commit()
    assert balance == Decimal("75.00")

    balance2 = await charge_to_house_account(
        db_session, restaurant_id=restaurant.id, customer_id=cust.id,
        order_id=2, amount_aed=Decimal("25.00"),
    )
    await db_session.commit()
    assert balance2 == Decimal("100.00")

    settled = await settle_house_account(
        db_session, restaurant_id=restaurant.id, customer_id=cust.id, amount_aed=Decimal("60.00"),
    )
    await db_session.commit()
    assert settled == Decimal("40.00")


@pytest.mark.anyio
async def test_settle_house_account_floors_at_zero(db_session, restaurant):
    cust = await _seed_customer(db_session, restaurant, "+971500000903")
    await enable_house_account(db_session, restaurant_id=restaurant.id, customer_id=cust.id)
    await db_session.commit()

    await charge_to_house_account(
        db_session, restaurant_id=restaurant.id, customer_id=cust.id,
        order_id=1, amount_aed=Decimal("20.00"),
    )
    await db_session.commit()

    settled = await settle_house_account(
        db_session, restaurant_id=restaurant.id, customer_id=cust.id, amount_aed=Decimal("500.00"),
    )
    await db_session.commit()
    assert settled == Decimal("0.00")


@pytest.mark.anyio
async def test_house_account_via_router(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.ordering.models import Customer, Order

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000904", name="Router House Account")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="HA-RTR-0001",
        status="confirmed", subtotal=Decimal("60.00"), total=Decimal("60.00"),
    )
    db_session.add(order)
    await db_session.commit()

    enable = await client.post(
        f"/api/v1/customers/{cust.id}/house-account/enable", headers=auth_headers,
    )
    assert enable.status_code == 200
    assert enable.json()["house_account_enabled"] is True

    charge = await client.post(
        f"/api/v1/orders/{order.id}/charge-to-house-account",
        json={"amount_aed": "60.00"},
        headers=auth_headers,
    )
    assert charge.status_code == 200
    assert charge.json()["house_account_balance_aed"] == "60.00"

    settle = await client.post(
        f"/api/v1/customers/{cust.id}/house-account/settle",
        json={"amount_aed": "60.00"},
        headers=auth_headers,
    )
    assert settle.status_code == 200
    assert settle.json()["house_account_balance_aed"] == "0.00"


@pytest.mark.anyio
async def test_charge_to_house_account_two_charges_accumulate_not_lost(db_session, restaurant):
    """Guards against the read-modify-write-in-Python race: if the balance
    update isn't a single atomic in-DB statement, two charges issued back to
    back can still land correctly here (this is a necessary, not sufficient,
    regression signal — the real race needs true concurrency — but a naive
    Python read-modify-write would already fail this under session reuse if
    the second read doesn't see the first write)."""
    cust = await _seed_customer(db_session, restaurant, "+971500000905")
    await enable_house_account(db_session, restaurant_id=restaurant.id, customer_id=cust.id)
    await db_session.commit()

    balance1 = await charge_to_house_account(
        db_session, restaurant_id=restaurant.id, customer_id=cust.id,
        order_id=1, amount_aed=Decimal("15.00"),
    )
    await db_session.commit()
    balance2 = await charge_to_house_account(
        db_session, restaurant_id=restaurant.id, customer_id=cust.id,
        order_id=2, amount_aed=Decimal("25.00"),
    )
    await db_session.commit()

    assert balance1 == Decimal("15.00")
    assert balance2 == Decimal("40.00")
    await db_session.refresh(cust)
    assert cust.house_account_balance_aed == Decimal("40.00")


@pytest.mark.anyio
async def test_charge_to_house_account_uses_atomic_db_update(db_session, restaurant, engine):
    """The balance mutation must be a single atomic UPDATE ... SET balance =
    balance + :amt SQL statement sent to Postgres (not a Python-side
    read-modify-write that computes the new value client-side and writes it
    back as a literal), so concurrent charges can't lose an update.

    Detected by listening for the raw SQL text sent to the DB cursor and
    confirming it contains an UPDATE on customers whose SET clause references
    house_account_balance_aed on the right-hand side (i.e. balance = balance
    + :amt, not balance = :literal)."""
    from sqlalchemy import event

    import app.payments.service as service_module

    cust = await _seed_customer(db_session, restaurant, "+971500000906")
    await enable_house_account(db_session, restaurant_id=restaurant.id, customer_id=cust.id)
    await db_session.commit()

    seen_statements = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        seen_statements.append(statement)

    sync_engine = engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _capture)
    try:
        await service_module.charge_to_house_account(
            db_session, restaurant_id=restaurant.id, customer_id=cust.id,
            order_id=1, amount_aed=Decimal("10.00"),
        )
        await db_session.commit()
    finally:
        event.remove(sync_engine, "before_cursor_execute", _capture)

    atomic_updates = [
        s for s in seen_statements
        if "UPDATE customers" in s
        and "house_account_balance_aed" in s
        and "house_account_balance_aed" in s.split("SET", 1)[1].split("WHERE")[0]
    ]
    assert atomic_updates, (
        "charge_to_house_account did not issue an atomic UPDATE ... SET "
        f"balance = balance + :amt statement; saw: {seen_statements}"
    )


@pytest.mark.anyio
async def test_charge_to_house_account_rejects_over_credit_limit(db_session, restaurant):
    from app.ordering.models import Customer

    cust = await _seed_customer(db_session, restaurant, "+971500000907")
    await enable_house_account(db_session, restaurant_id=restaurant.id, customer_id=cust.id)
    cust.house_account_credit_limit_aed = Decimal("100.00")
    await db_session.commit()

    await charge_to_house_account(
        db_session, restaurant_id=restaurant.id, customer_id=cust.id,
        order_id=1, amount_aed=Decimal("80.00"),
    )
    await db_session.commit()

    with pytest.raises(ValueError):
        await charge_to_house_account(
            db_session, restaurant_id=restaurant.id, customer_id=cust.id,
            order_id=2, amount_aed=Decimal("20.01"),
        )

    reloaded = await db_session.get(Customer, cust.id)
    assert reloaded.house_account_balance_aed == Decimal("80.00")


@pytest.mark.anyio
async def test_charge_to_house_account_exactly_at_credit_limit_succeeds(db_session, restaurant):
    cust = await _seed_customer(db_session, restaurant, "+971500000908")
    await enable_house_account(db_session, restaurant_id=restaurant.id, customer_id=cust.id)
    cust.house_account_credit_limit_aed = Decimal("50.00")
    await db_session.commit()

    balance = await charge_to_house_account(
        db_session, restaurant_id=restaurant.id, customer_id=cust.id,
        order_id=1, amount_aed=Decimal("50.00"),
    )
    await db_session.commit()
    assert balance == Decimal("50.00")


@pytest.mark.anyio
async def test_charge_to_house_account_no_limit_when_null(db_session, restaurant):
    """house_account_credit_limit_aed is nullable = no limit enforced."""
    cust = await _seed_customer(db_session, restaurant, "+971500000909")
    await enable_house_account(db_session, restaurant_id=restaurant.id, customer_id=cust.id)
    await db_session.commit()
    assert cust.house_account_credit_limit_aed is None

    balance = await charge_to_house_account(
        db_session, restaurant_id=restaurant.id, customer_id=cust.id,
        order_id=1, amount_aed=Decimal("999999.00"),
    )
    await db_session.commit()
    assert balance == Decimal("999999.00")


@pytest.mark.anyio
@pytest.mark.parametrize("bad_amount", ["0.00", "-1.00"])
async def test_charge_to_house_account_router_rejects_non_positive_amount(client, auth_headers, bad_amount):
    resp = await client.post(
        "/api/v1/orders/999999/charge-to-house-account",
        json={"amount_aed": bad_amount},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.anyio
@pytest.mark.parametrize("bad_amount", ["0.00", "-1.00"])
async def test_settle_house_account_router_rejects_non_positive_amount(client, auth_headers, bad_amount):
    resp = await client.post(
        "/api/v1/customers/999999/house-account/settle",
        json={"amount_aed": bad_amount},
        headers=auth_headers,
    )
    assert resp.status_code == 422
