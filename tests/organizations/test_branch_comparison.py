from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.organizations.service import add_branch, branch_comparison, signup_organization


@pytest.mark.anyio
async def test_branch_comparison_sorts_by_revenue_desc(db_session):
    from app.ordering.models import Customer, Order

    org = await signup_organization(
        db_session, name="Compare Group", owner_email="owner@compare.ae", password="hunter2!",
    )
    await db_session.commit()
    b1 = await add_branch(db_session, organization_id=org.id, name="Low Branch", lat=25.1, lng=55.1)
    b2 = await add_branch(db_session, organization_id=org.id, name="High Branch", lat=25.2, lng=55.2)
    await db_session.commit()

    for branch, amounts in ((b1, ["20.00"]), (b2, ["50.00", "40.00"])):
        cust = Customer(restaurant_id=branch.id, phone=f"+97151000{branch.id:04d}", name="Cust")
        db_session.add(cust)
        await db_session.flush()
        for i, amount in enumerate(amounts):
            db_session.add(Order(
                restaurant_id=branch.id, customer_id=cust.id, order_number=f"CB-{branch.id}-{i}",
                status="delivered", subtotal=Decimal(amount), total=Decimal(amount),
            ))
    await db_session.commit()

    today = date.today()
    result = await branch_comparison(
        db_session, org_id=org.id, start_date=today - timedelta(days=1), end_date=today + timedelta(days=1),
    )

    assert len(result) == 2
    assert result[0]["restaurant_id"] == b2.id
    assert result[0]["order_count"] == 2
    assert result[0]["revenue_aed"] == Decimal("90.00")
    assert result[1]["restaurant_id"] == b1.id
    assert result[1]["order_count"] == 1
    assert result[1]["revenue_aed"] == Decimal("20.00")


@pytest.mark.anyio
async def test_branch_comparison_router(client, db_session):
    from app.ordering.models import Customer, Order
    from sqlalchemy import select

    from app.organizations.models import Organization

    signup = await client.post(
        "/api/v1/organizations/signup",
        json={"name": "Router Compare Group", "owner_email": "owner@routercompare.ae", "password": "hunter2!"},
    )
    token = signup.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    branch = await client.post(
        "/api/v1/organizations/branches", json={"name": "RC Branch", "lat": 25.1, "lng": 55.1}, headers=headers,
    )
    branch_id = branch.json()["id"]

    cust = Customer(restaurant_id=branch_id, phone="+971510009999", name="Cust")
    db_session.add(cust)
    await db_session.flush()
    db_session.add(Order(
        restaurant_id=branch_id, customer_id=cust.id, order_number="RC-1",
        status="delivered", subtotal=Decimal("15.00"), total=Decimal("15.00"),
    ))
    await db_session.commit()

    org = await db_session.scalar(
        select(Organization).where(Organization.owner_email == "owner@routercompare.ae")
    )

    today = date.today()
    start = (today - timedelta(days=1)).isoformat()
    end = (today + timedelta(days=1)).isoformat()

    resp = await client.get(
        f"/api/v1/organizations/{org.id}/branch-comparison?start_date={start}&end_date={end}",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["restaurant_id"] == branch_id
    assert data[0]["order_count"] == 1
    assert data[0]["revenue_aed"] == "15.00"
