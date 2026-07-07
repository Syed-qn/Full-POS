from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.auth import create_access_token, verify_password
from app.organizations.deps import current_organization
from app.organizations.models import Organization
from app.organizations.schemas import BranchIn, OrgLoginIn, OrgSignupIn
from app.organizations.service import add_branch, list_branches, rollup_sales, signup_organization

router = APIRouter(prefix="/api/v1/organizations", tags=["organizations"])


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
