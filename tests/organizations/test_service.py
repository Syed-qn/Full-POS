from datetime import date
from decimal import Decimal

import pytest

from app.organizations.service import add_branch, rollup_sales, signup_organization


@pytest.mark.anyio
async def test_signup_creates_organization(db_session):
    org = await signup_organization(
        db_session, name="Acme Group", owner_email="owner@acme.ae", password="hunter2!",
    )
    await db_session.commit()
    assert org.owner_email == "owner@acme.ae"


@pytest.mark.anyio
async def test_add_branch_creates_restaurant_under_org(db_session):
    org = await signup_organization(
        db_session, name="Acme Group 2", owner_email="owner2@acme.ae", password="hunter2!",
    )
    await db_session.commit()
    branch = await add_branch(
        db_session, organization_id=org.id, name="Acme Downtown", lat=25.2, lng=55.3,
    )
    await db_session.commit()
    assert branch.organization_id == org.id


@pytest.mark.anyio
async def test_rollup_sales_sums_across_branches(db_session):
    from app.ordering.models import Customer, Order

    org = await signup_organization(
        db_session, name="Acme Group 3", owner_email="owner3@acme.ae", password="hunter2!",
    )
    await db_session.commit()
    b1 = await add_branch(db_session, organization_id=org.id, name="Branch 1", lat=25.1, lng=55.1)
    b2 = await add_branch(db_session, organization_id=org.id, name="Branch 2", lat=25.2, lng=55.2)
    await db_session.commit()

    for branch, amount in ((b1, "50.00"), (b2, "30.00")):
        cust = Customer(restaurant_id=branch.id, phone=f"+97150000{branch.id:04d}", name="Cust")
        db_session.add(cust)
        await db_session.flush()
        db_session.add(Order(
            restaurant_id=branch.id, customer_id=cust.id, order_number=f"RB-{branch.id}",
            status="delivered", subtotal=Decimal(amount), total=Decimal(amount),
        ))
    await db_session.commit()

    result = await rollup_sales(db_session, organization_id=org.id, target_date=date.today())
    assert result["total_gross_sales_aed"] == Decimal("80.00")
    assert len(result["branches"]) == 2
