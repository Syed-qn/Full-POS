from decimal import Decimal

import pytest

from app.identity.auth import create_access_token
from app.inventory.models import Ingredient
from app.organizations.service import (
    add_branch,
    organization_inventory_summary,
    signup_organization,
)


async def _seed_org_with_inventory(db_session):
    org = await signup_organization(
        db_session,
        name="Wave 3 Group",
        owner_email="wave3@example.test",
        password="hunter2!",
    )
    branch_1 = await add_branch(
        db_session, organization_id=org.id, name="Downtown", lat=25.1, lng=55.1,
    )
    branch_2 = await add_branch(
        db_session, organization_id=org.id, name="Marina", lat=25.2, lng=55.2,
    )
    db_session.add_all([
        Ingredient(
            restaurant_id=branch_1.id,
            name="Tomato",
            unit="kg",
            current_stock=Decimal("5.000"),
            low_stock_threshold=Decimal("2.000"),
            cost_per_unit_aed=Decimal("3.0000"),
        ),
        Ingredient(
            restaurant_id=branch_1.id,
            name="Cheese",
            unit="kg",
            current_stock=Decimal("1.000"),
            low_stock_threshold=Decimal("2.000"),
            cost_per_unit_aed=Decimal("12.0000"),
        ),
        Ingredient(
            restaurant_id=branch_2.id,
            name="Rice",
            unit="kg",
            current_stock=Decimal("10.000"),
            low_stock_threshold=Decimal("12.000"),
            cost_per_unit_aed=Decimal("4.0000"),
        ),
        Ingredient(
            restaurant_id=branch_2.id,
            name="Oil",
            unit="L",
            current_stock=Decimal("2.000"),
            low_stock_threshold=Decimal("1.000"),
            cost_per_unit_aed=Decimal("8.5000"),
        ),
    ])
    await db_session.commit()
    return org


@pytest.mark.anyio
async def test_organization_inventory_summary_aggregates_branch_values_and_low_stock(
    db_session,
):
    org = await _seed_org_with_inventory(db_session)

    result = await organization_inventory_summary(db_session, organization_id=org.id)

    assert result["total_inventory_value_aed"] == Decimal("84.00")
    assert result["total_low_stock_count"] == 2
    by_name = {row["restaurant_name"]: row for row in result["branches"]}
    assert by_name["Downtown"]["inventory_value_aed"] == Decimal("27.00")
    assert by_name["Downtown"]["low_stock_count"] == 1
    assert by_name["Marina"]["inventory_value_aed"] == Decimal("57.00")
    assert by_name["Marina"]["low_stock_count"] == 1


@pytest.mark.anyio
async def test_inventory_summary_route_serializes_money_as_strings(client, db_session):
    org = await _seed_org_with_inventory(db_session)
    token = create_access_token(org_id=org.id, audience="org")

    response = await client.get(
        "/api/v1/organizations/inventory-summary",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_inventory_value_aed"] == "84.00"
    assert body["total_low_stock_count"] == 2
    by_name = {row["restaurant_name"]: row for row in body["branches"]}
    assert by_name["Downtown"]["inventory_value_aed"] == "27.00"
    assert by_name["Downtown"]["low_stock_count"] == 1
    assert by_name["Marina"]["inventory_value_aed"] == "57.00"
    assert by_name["Marina"]["low_stock_count"] == 1
