from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.auth import hash_password
from app.identity.models import Restaurant
from app.organizations.models import Organization


async def signup_organization(
    session: AsyncSession, *, name: str, owner_email: str, password: str
) -> Organization:
    org = Organization(name=name, owner_email=owner_email, password_hash=hash_password(password))
    session.add(org)
    await session.flush()
    return org


async def add_branch(
    session: AsyncSession, *, organization_id: int, name: str, lat: float, lng: float
) -> Restaurant:
    branch = Restaurant(name=name, lat=lat, lng=lng, password_hash="", organization_id=organization_id)
    session.add(branch)
    await session.flush()
    return branch


async def list_branches(session: AsyncSession, *, organization_id: int) -> list[Restaurant]:
    rows = await session.scalars(
        select(Restaurant).where(Restaurant.organization_id == organization_id)
    )
    return list(rows)


async def rollup_sales(session: AsyncSession, *, organization_id: int, target_date: date) -> dict:
    from app.reports.zreport import build_z_report

    branches = await list_branches(session, organization_id=organization_id)
    breakdown = []
    total = Decimal("0.00")
    for branch in branches:
        report = await build_z_report(session, restaurant_id=branch.id, target_date=target_date)
        breakdown.append({
            "restaurant_id": branch.id, "name": branch.name,
            "gross_sales_aed": report["gross_sales_aed"],
        })
        total += report["gross_sales_aed"]

    return {"total_gross_sales_aed": total, "branches": breakdown}
