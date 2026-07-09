from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.auth import create_access_token, verify_password
from app.organizations.deps import current_organization
from app.organizations.franchise import (
    approve_menu_publish,
    bulk_update_branches,
    create_central_kitchen_request,
    create_org_member,
    create_org_menu_item,
    create_org_promotion,
    credit_org_loyalty,
    list_central_kitchen_requests,
    list_org_customers,
    list_org_members,
    list_org_menu,
    multi_currency_rollup,
    push_promotion_to_branches,
    region_report,
    request_menu_publish,
    royalty_report,
    set_branch_price,
    update_branch_meta,
    update_central_kitchen_status,
    update_org_settings,
    upsert_org_customer,
)
from app.organizations.models import Organization, OrgMenuPublishJob, OrgPromotion
from app.organizations.schemas import (
    BranchIn,
    BranchPatchIn,
    BranchPriceIn,
    BulkUpdateIn,
    CentralKitchenRequestIn,
    CentralKitchenStatusIn,
    LoyaltyCreditIn,
    MenuPublishDecisionIn,
    MenuPublishIn,
    OrgCustomerIn,
    OrgLoginIn,
    OrgMemberIn,
    OrgMenuItemIn,
    OrgPromotionIn,
    OrgSettingsIn,
    OrgSignupIn,
    StockTransferIn,
)
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


@router.get("/me")
async def org_me(org: Organization = Depends(current_organization)):
    return {
        "id": org.id,
        "name": org.name,
        "owner_email": org.owner_email,
        "royalty_pct": str(org.royalty_pct or 0),
        "default_currency": org.default_currency,
        "default_locale": org.default_locale,
        "settings": org.settings or {},
    }


@router.patch("/me")
async def org_patch_me(
    body: OrgSettingsIn,
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    await update_org_settings(
        session,
        org=org,
        royalty_pct=body.royalty_pct,
        default_currency=body.default_currency,
        default_locale=body.default_locale,
        settings_patch=body.settings,
    )
    await session.commit()
    await session.refresh(org)
    return {
        "id": org.id,
        "royalty_pct": str(org.royalty_pct or 0),
        "default_currency": org.default_currency,
        "default_locale": org.default_locale,
        "settings": org.settings or {},
    }


@router.post("/branches", status_code=status.HTTP_201_CREATED)
async def create_branch(
    body: BranchIn,
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    branch = await add_branch(
        session,
        organization_id=org.id,
        name=body.name,
        lat=body.lat,
        lng=body.lng,
        region=body.region,
        currency=body.currency,
        locale=body.locale,
        is_central_kitchen=body.is_central_kitchen,
    )
    await session.commit()
    return {
        "id": branch.id,
        "name": branch.name,
        "region": branch.region,
        "currency": branch.currency,
        "locale": branch.locale,
        "is_central_kitchen": branch.is_central_kitchen,
    }


@router.get("/branches")
async def get_branches(
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    branches = await list_branches(session, organization_id=org.id)
    return [
        {
            "id": b.id,
            "name": b.name,
            "region": b.region,
            "currency": getattr(b, "currency", "AED"),
            "locale": getattr(b, "locale", "en"),
            "is_central_kitchen": bool(getattr(b, "is_central_kitchen", False)),
            "lat": b.lat,
            "lng": b.lng,
        }
        for b in branches
    ]


@router.patch("/branches/{restaurant_id}")
async def patch_branch(
    restaurant_id: int,
    body: BranchPatchIn,
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    try:
        branch = await update_branch_meta(
            session,
            organization_id=org.id,
            restaurant_id=restaurant_id,
            **body.model_dump(exclude_none=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return {
        "id": branch.id,
        "name": branch.name,
        "region": branch.region,
        "currency": branch.currency,
        "locale": branch.locale,
        "is_central_kitchen": branch.is_central_kitchen,
    }


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


# ── Category 11 HQ ───────────────────────────────────────────────────────────


@router.post("/menu-items", status_code=status.HTTP_201_CREATED)
async def post_menu_item(
    body: OrgMenuItemIn,
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    item = await create_org_menu_item(
        session,
        organization_id=org.id,
        name=body.name,
        base_price_aed=body.base_price_aed,
        category=body.category,
        description=body.description,
        name_ar=body.name_ar,
        dish_number=body.dish_number,
    )
    await session.commit()
    return {
        "id": item.id,
        "name": item.name,
        "base_price_aed": str(item.base_price_aed),
        "category": item.category,
        "name_ar": item.name_ar,
    }


@router.get("/menu-items")
async def get_menu_items(
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    items = await list_org_menu(session, organization_id=org.id)
    return [
        {
            "id": i.id,
            "name": i.name,
            "name_ar": i.name_ar,
            "category": i.category,
            "base_price_aed": str(i.base_price_aed),
            "is_active": i.is_active,
            "dish_number": i.dish_number,
        }
        for i in items
    ]


@router.post("/branch-prices", status_code=status.HTTP_201_CREATED)
async def post_branch_price(
    body: BranchPriceIn,
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    try:
        row = await set_branch_price(
            session,
            organization_id=org.id,
            org_menu_item_id=body.org_menu_item_id,
            restaurant_id=body.restaurant_id,
            price_aed=body.price_aed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return {
        "id": row.id,
        "org_menu_item_id": row.org_menu_item_id,
        "restaurant_id": row.restaurant_id,
        "price_aed": str(row.price_aed),
    }


@router.post("/menu-publish", status_code=status.HTTP_201_CREATED)
async def post_menu_publish(
    body: MenuPublishIn,
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    job = await request_menu_publish(
        session,
        organization_id=org.id,
        target_restaurant_ids=body.target_restaurant_ids,
        org_menu_item_ids=body.org_menu_item_ids,
        notes=body.notes,
    )
    await session.commit()
    return {"id": job.id, "status": job.status}


@router.post("/menu-publish/{job_id}/decide")
async def decide_menu_publish(
    job_id: int,
    body: MenuPublishDecisionIn,
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    try:
        job = await approve_menu_publish(
            session,
            organization_id=org.id,
            job_id=job_id,
            approved_by=body.approved_by,
            approve=body.approve,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return {"id": job.id, "status": job.status, "result": job.result}


@router.get("/menu-publish")
async def list_menu_publish(
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    rows = list(
        (
            await session.scalars(
                select(OrgMenuPublishJob)
                .where(OrgMenuPublishJob.organization_id == org.id)
                .order_by(OrgMenuPublishJob.id.desc())
                .limit(50)
            )
        ).all()
    )
    return [{"id": r.id, "status": r.status, "result": r.result, "notes": r.notes} for r in rows]


@router.post("/bulk-update")
async def bulk_update(
    body: BulkUpdateIn,
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    try:
        result = await bulk_update_branches(
            session,
            organization_id=org.id,
            restaurant_ids=body.restaurant_ids,
            action=body.action,
            payload=body.payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return result


@router.get("/royalty")
async def get_royalty(
    start_date: date,
    end_date: date,
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    return await royalty_report(
        session,
        organization_id=org.id,
        start_date=start_date,
        end_date=end_date,
        org=org,
    )


@router.get("/region-report")
async def get_region_report(
    start_date: date,
    end_date: date,
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    return await region_report(
        session, organization_id=org.id, start_date=start_date, end_date=end_date
    )


@router.get("/multi-currency-rollup")
async def get_fx_rollup(
    target_date: date,
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    return await multi_currency_rollup(
        session, organization_id=org.id, target_date=target_date, org=org
    )


@router.post("/customers", status_code=status.HTTP_201_CREATED)
async def post_customer(
    body: OrgCustomerIn,
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    c = await upsert_org_customer(
        session,
        organization_id=org.id,
        phone=body.phone,
        name=body.name,
        preferred_locale=body.preferred_locale,
    )
    await session.commit()
    return {
        "id": c.id,
        "phone": c.phone,
        "name": c.name,
        "loyalty_points": c.loyalty_points,
        "preferred_locale": c.preferred_locale,
    }


@router.get("/customers")
async def get_customers(
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=50, ge=1, le=200),
):
    rows = await list_org_customers(session, organization_id=org.id, limit=limit)
    return [
        {
            "id": c.id,
            "phone": c.phone,
            "name": c.name,
            "loyalty_points": c.loyalty_points,
            "total_orders": c.total_orders,
            "total_spend_aed": str(c.total_spend_aed),
            "preferred_locale": c.preferred_locale,
        }
        for c in rows
    ]


@router.post("/loyalty/credit")
async def post_loyalty(
    body: LoyaltyCreditIn,
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    c = await credit_org_loyalty(
        session,
        organization_id=org.id,
        phone=body.phone,
        points=body.points,
        spend_aed=body.spend_aed,
    )
    await session.commit()
    return {
        "id": c.id,
        "phone": c.phone,
        "loyalty_points": c.loyalty_points,
        "total_spend_aed": str(c.total_spend_aed),
    }


@router.post("/promotions", status_code=status.HTTP_201_CREATED)
async def post_promotion(
    body: OrgPromotionIn,
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    promo = await create_org_promotion(
        session,
        organization_id=org.id,
        code=body.code,
        title=body.title,
        discount_aed=body.discount_aed,
        discount_pct=body.discount_pct,
        target_restaurant_ids=body.target_restaurant_ids,
    )
    await session.commit()
    return {"id": promo.id, "code": promo.code, "status": promo.status}


@router.post("/promotions/{promo_id}/push")
async def push_promotion(
    promo_id: int,
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    try:
        promo = await push_promotion_to_branches(
            session, organization_id=org.id, promo_id=promo_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return {
        "id": promo.id,
        "code": promo.code,
        "pushed_coupon_ids": promo.pushed_coupon_ids,
    }


@router.get("/promotions")
async def list_promotions(
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    rows = list(
        (
            await session.scalars(
                select(OrgPromotion).where(OrgPromotion.organization_id == org.id)
            )
        ).all()
    )
    return [
        {
            "id": p.id,
            "code": p.code,
            "title": p.title,
            "status": p.status,
            "discount_aed": str(p.discount_aed),
            "pushed_coupon_ids": p.pushed_coupon_ids,
        }
        for p in rows
    ]


@router.post("/members", status_code=status.HTTP_201_CREATED)
async def post_member(
    body: OrgMemberIn,
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    try:
        m = await create_org_member(
            session,
            organization_id=org.id,
            email=body.email,
            name=body.name,
            role=body.role,
            branch_ids=body.branch_ids,
            pin=body.pin,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return {
        "id": m.id,
        "email": m.email,
        "name": m.name,
        "role": m.role,
        "branch_ids": m.branch_ids,
    }


@router.get("/members")
async def get_members(
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    rows = await list_org_members(session, organization_id=org.id)
    return [
        {
            "id": m.id,
            "email": m.email,
            "name": m.name,
            "role": m.role,
            "branch_ids": m.branch_ids,
            "is_active": m.is_active,
        }
        for m in rows
    ]


@router.post("/central-kitchen/requests", status_code=status.HTTP_201_CREATED)
async def post_ck_request(
    body: CentralKitchenRequestIn,
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    try:
        req = await create_central_kitchen_request(
            session,
            organization_id=org.id,
            from_restaurant_id=body.from_restaurant_id,
            items=body.items,
            notes=body.notes,
            central_kitchen_id=body.central_kitchen_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return {
        "id": req.id,
        "status": req.status,
        "from_restaurant_id": req.from_restaurant_id,
        "central_kitchen_id": req.central_kitchen_id,
        "items": req.items,
    }


@router.get("/central-kitchen/requests")
async def get_ck_requests(
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    rows = await list_central_kitchen_requests(session, organization_id=org.id)
    return [
        {
            "id": r.id,
            "status": r.status,
            "from_restaurant_id": r.from_restaurant_id,
            "central_kitchen_id": r.central_kitchen_id,
            "items": r.items,
            "notes": r.notes,
        }
        for r in rows
    ]


@router.post("/central-kitchen/requests/{request_id}/status")
async def patch_ck_status(
    request_id: int,
    body: CentralKitchenStatusIn,
    org: Organization = Depends(current_organization),
    session: AsyncSession = Depends(get_session),
):
    try:
        req = await update_central_kitchen_status(
            session,
            organization_id=org.id,
            request_id=request_id,
            status=body.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return {"id": req.id, "status": req.status}
