from decimal import Decimal

import pytest

from app.inventory.models import Ingredient
from app.organizations.service import add_branch, signup_organization
from app.organizations.stock_transfer import complete_stock_transfer, create_stock_transfer


async def _make_org_with_branches(db_session, suffix: str):
    org = await signup_organization(
        db_session, name=f"Transfer Group {suffix}", owner_email=f"owner{suffix}@transfer.ae",
        password="hunter2!",
    )
    await db_session.commit()
    b1 = await add_branch(db_session, organization_id=org.id, name=f"Branch A {suffix}", lat=25.1, lng=55.1)
    b2 = await add_branch(db_session, organization_id=org.id, name=f"Branch B {suffix}", lat=25.2, lng=55.2)
    await db_session.commit()
    return org, b1, b2


@pytest.mark.anyio
async def test_create_stock_transfer_validates_same_org(db_session):
    org, b1, b2 = await _make_org_with_branches(db_session, "1")
    other_org = await signup_organization(
        db_session, name="Other Org", owner_email="other1@transfer.ae", password="hunter2!",
    )
    await db_session.commit()
    outside_branch = await add_branch(
        db_session, organization_id=other_org.id, name="Outside Branch", lat=25.3, lng=55.3,
    )
    await db_session.commit()

    with pytest.raises(ValueError):
        await create_stock_transfer(
            db_session, org_id=org.id, from_restaurant_id=b1.id,
            to_restaurant_id=outside_branch.id, lines=[{"ingredient_name": "Tomatoes", "unit": "kg", "quantity": "5.000"}],
        )


@pytest.mark.anyio
async def test_create_stock_transfer_creates_transfer_and_lines(db_session):
    org, b1, b2 = await _make_org_with_branches(db_session, "2")

    transfer = await create_stock_transfer(
        db_session, org_id=org.id, from_restaurant_id=b1.id, to_restaurant_id=b2.id,
        lines=[
            {"ingredient_name": "Tomatoes", "unit": "kg", "quantity": "5.000"},
            {"ingredient_name": "Onions", "unit": "kg", "quantity": "2.500"},
        ],
    )
    assert transfer.id is not None
    assert transfer.status == "pending"
    assert transfer.from_restaurant_id == b1.id
    assert transfer.to_restaurant_id == b2.id


@pytest.mark.anyio
async def test_complete_stock_transfer_moves_stock_between_branches(db_session):
    org, b1, b2 = await _make_org_with_branches(db_session, "3")

    source_ing = Ingredient(
        restaurant_id=b1.id, name="Tomatoes", unit="kg",
        current_stock=Decimal("20.000"), low_stock_threshold=Decimal("2.000"),
    )
    db_session.add(source_ing)
    await db_session.commit()

    transfer = await create_stock_transfer(
        db_session, org_id=org.id, from_restaurant_id=b1.id, to_restaurant_id=b2.id,
        lines=[{"ingredient_name": "Tomatoes", "unit": "kg", "quantity": "5.000"}],
    )
    await db_session.commit()

    completed = await complete_stock_transfer(db_session, transfer_id=transfer.id)
    await db_session.commit()

    assert completed.status == "completed"

    await db_session.refresh(source_ing)
    assert source_ing.current_stock == Decimal("15.000")

    from sqlalchemy import select

    dest_ing = await db_session.scalar(
        select(Ingredient).where(Ingredient.restaurant_id == b2.id, Ingredient.name == "Tomatoes")
    )
    assert dest_ing is not None
    assert dest_ing.current_stock == Decimal("5.000")


@pytest.mark.anyio
async def test_complete_stock_transfer_increments_existing_destination_ingredient(db_session):
    org, b1, b2 = await _make_org_with_branches(db_session, "4")

    source_ing = Ingredient(
        restaurant_id=b1.id, name="Onions", unit="kg",
        current_stock=Decimal("10.000"), low_stock_threshold=Decimal("1.000"),
    )
    dest_ing = Ingredient(
        restaurant_id=b2.id, name="Onions", unit="kg",
        current_stock=Decimal("3.000"), low_stock_threshold=Decimal("1.000"),
    )
    db_session.add_all([source_ing, dest_ing])
    await db_session.commit()

    transfer = await create_stock_transfer(
        db_session, org_id=org.id, from_restaurant_id=b1.id, to_restaurant_id=b2.id,
        lines=[{"ingredient_name": "Onions", "unit": "kg", "quantity": "4.000"}],
    )
    await db_session.commit()

    await complete_stock_transfer(db_session, transfer_id=transfer.id)
    await db_session.commit()

    await db_session.refresh(source_ing)
    await db_session.refresh(dest_ing)
    assert source_ing.current_stock == Decimal("6.000")
    assert dest_ing.current_stock == Decimal("7.000")


@pytest.mark.anyio
async def test_stock_transfer_router_create_and_complete(client, db_session):
    signup = await client.post(
        "/api/v1/organizations/signup",
        json={"name": "Router Transfer Group", "owner_email": "owner@routertransfer.ae", "password": "hunter2!"},
    )
    token = signup.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    b1 = await client.post(
        "/api/v1/organizations/branches", json={"name": "R Branch A", "lat": 25.1, "lng": 55.1}, headers=headers,
    )
    b2 = await client.post(
        "/api/v1/organizations/branches", json={"name": "R Branch B", "lat": 25.2, "lng": 55.2}, headers=headers,
    )
    # org id is embedded in the JWT sub claim; decoding it is unnecessary —
    # branches endpoint is org-scoped via the bearer token, so grab org id from db.
    from sqlalchemy import select

    from app.organizations.models import Organization

    org = await db_session.scalar(
        select(Organization).where(Organization.owner_email == "owner@routertransfer.ae")
    )

    b1_id = b1.json()["id"]
    b2_id = b2.json()["id"]

    source_ing = Ingredient(
        restaurant_id=b1_id, name="Rice", unit="kg",
        current_stock=Decimal("50.000"), low_stock_threshold=Decimal("5.000"),
    )
    db_session.add(source_ing)
    await db_session.commit()

    create_resp = await client.post(
        f"/api/v1/organizations/{org.id}/stock-transfers",
        json={
            "from_restaurant_id": b1_id, "to_restaurant_id": b2_id,
            "lines": [{"ingredient_name": "Rice", "unit": "kg", "quantity": "10.000"}],
        },
        headers=headers,
    )
    assert create_resp.status_code == 201
    transfer_id = create_resp.json()["id"]
    assert create_resp.json()["status"] == "pending"

    complete_resp = await client.post(
        f"/api/v1/stock-transfers/{transfer_id}/complete", headers=headers,
    )
    assert complete_resp.status_code == 200
    assert complete_resp.json()["status"] == "completed"

    await db_session.refresh(source_ing)
    assert source_ing.current_stock == Decimal("40.000")
