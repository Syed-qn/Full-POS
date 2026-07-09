from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.auth import create_access_token, verify_password
from app.organizations.deps import current_organization
from app.organizations.models import Organization
from app.organizations.schemas import BranchIn, OrgLoginIn, OrgSignupIn, StockTransferIn
from app.organizations.service import (
    add_branch,
    branch_comparison,
    list_branches,
    organization_inventory_summary,
    rollup_sales,
    signup_organization,
)
from app.organizations.stock_transfer import complete_stock_transfer, create_stock_transfer

router = APIRouter(prefix="/api/v1/organizations", tags=["organizations"])
stock_transfer_router = APIRouter(prefix="/api/v1/stock-transfers", tags=["organizations"])


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(body: OrgSignupIn, session: AsyncSession = Depends(get_session)):
    existing = await session.scalar(
        select(Organization).where(Organization.owner_email == body.owner_email)
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="owner_email already registered")
    org = await signup_organization(
        session, name=body.name, owner_email=body.owner_email, password=body.password,
    )
    await session.commit()
    token = create_access_token(org_id=org.id, audience="org")
    return {"access_token": token, "token_type": "bearer"}


@router.post("/login")
async def login(body: OrgLoginIn, session: AsyncSession = Depends(get_session)):
    org = await session.scalar(
        select(Organization).where(Organization.owner_email == body.owner_email)
    )
    if org is None or not verify_password(body.password, org.password_hash):
        raise HTTPException(status_code=401, detail="invalid credentials")
    token = create_access_token(org_id=org.id, audience="org")
    return {"access_token": token, "token_type": "bearer"}


@router.post("/branches", status_code=status.HTTP_201_CREATED)
async def create_branch(
    body: BranchIn,
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    branch = await add_branch(session, organization_id=org.id, name=body.name, lat=body.lat, lng=body.lng)
    await session.commit()
    return {"id": branch.id, "name": branch.name}


@router.get("/branches")
async def get_branches(
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    branches = await list_branches(session, organization_id=org.id)
    return [{"id": b.id, "name": b.name} for b in branches]


@router.get("/rollup-sales")
async def get_rollup_sales(
    target_date: date,
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    result = await rollup_sales(session, organization_id=org.id, target_date=target_date)
    return {
        "total_gross_sales_aed": str(result["total_gross_sales_aed"]),
        "branches": [
            {**b, "gross_sales_aed": str(b["gross_sales_aed"])} for b in result["branches"]
        ],
    }


@router.get("/inventory-summary")
async def get_inventory_summary(
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    result = await organization_inventory_summary(session, organization_id=org.id)
    return {
        "total_inventory_value_aed": str(result["total_inventory_value_aed"]),
        "total_low_stock_count": result["total_low_stock_count"],
        "branches": [
            {**row, "inventory_value_aed": str(row["inventory_value_aed"])}
            for row in result["branches"]
        ],
    }


@router.get("/{org_id}/branch-comparison")
async def get_branch_comparison(
    org_id: int,
    start_date: date,
    end_date: date,
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    if org_id != org.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "cannot view another organization")
    results = await branch_comparison(session, org_id=org_id, start_date=start_date, end_date=end_date)
    return [
        {**r, "revenue_aed": str(r["revenue_aed"])} for r in results
    ]


@router.post("/{org_id}/stock-transfers", status_code=status.HTTP_201_CREATED)
async def create_stock_transfer_route(
    org_id: int,
    body: StockTransferIn,
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    if org_id != org.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "cannot act on another organization")
    try:
        transfer = await create_stock_transfer(
            session,
            org_id=org_id,
            from_restaurant_id=body.from_restaurant_id,
            to_restaurant_id=body.to_restaurant_id,
            lines=[line.model_dump() for line in body.lines],
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    await session.commit()
    return {
        "id": transfer.id,
        "status": transfer.status,
        "from_restaurant_id": transfer.from_restaurant_id,
        "to_restaurant_id": transfer.to_restaurant_id,
    }


@stock_transfer_router.post("/{transfer_id}/complete")
async def complete_stock_transfer_route(
    transfer_id: int,
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    try:
        transfer = await complete_stock_transfer(session, transfer_id=transfer_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    if transfer.organization_id != org.id:
        await session.rollback()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "cannot act on another organization's transfer")
    await session.commit()
    return {"id": transfer.id, "status": transfer.status}
