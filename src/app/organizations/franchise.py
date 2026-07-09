"""Category 11 — franchise HQ ops: menu publish, royalty, regions, loyalty, promos."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.audit.service import record_audit
from app.identity.models import Restaurant
from app.organizations.models import (
    CentralKitchenRequest,
    OrgBranchPrice,
    OrgCustomer,
    OrgMember,
    OrgMenuItem,
    OrgMenuPublishJob,
    OrgPromotion,
    Organization,
)
from app.organizations.service import list_branches


def _money(d: Decimal | float | int) -> Decimal:
    return Decimal(str(d)).quantize(Decimal("0.01"))


# ── Branch metadata ──────────────────────────────────────────────────────────


async def update_branch_meta(
    session: AsyncSession,
    *,
    organization_id: int,
    restaurant_id: int,
    region: str | None = None,
    currency: str | None = None,
    locale: str | None = None,
    is_central_kitchen: bool | None = None,
    name: str | None = None,
) -> Restaurant:
    branch = await session.get(Restaurant, restaurant_id)
    if branch is None or branch.organization_id != organization_id:
        raise ValueError("branch not found in organization")
    if region is not None:
        branch.region = region
    if currency is not None:
        branch.currency = currency.upper()[:8]
    if locale is not None:
        branch.locale = locale
    if is_central_kitchen is not None:
        branch.is_central_kitchen = is_central_kitchen
    if name is not None:
        branch.name = name
    await session.flush()
    return branch


async def update_org_settings(
    session: AsyncSession,
    *,
    org: Organization,
    royalty_pct: Decimal | None = None,
    default_currency: str | None = None,
    default_locale: str | None = None,
    settings_patch: dict | None = None,
) -> Organization:
    if royalty_pct is not None:
        org.royalty_pct = _money(royalty_pct)
    if default_currency is not None:
        org.default_currency = default_currency.upper()[:8]
    if default_locale is not None:
        org.default_locale = default_locale
    if settings_patch:
        cur = dict(org.settings or {})
        cur.update(settings_patch)
        org.settings = cur
        flag_modified(org, "settings")
    await session.flush()
    return org


# ── Central menu ─────────────────────────────────────────────────────────────


async def create_org_menu_item(
    session: AsyncSession,
    *,
    organization_id: int,
    name: str,
    base_price_aed: Decimal,
    category: str | None = None,
    description: str | None = None,
    name_ar: str | None = None,
    dish_number: int | None = None,
) -> OrgMenuItem:
    item = OrgMenuItem(
        organization_id=organization_id,
        name=name,
        name_ar=name_ar,
        description=description,
        category=category,
        base_price_aed=_money(base_price_aed),
        dish_number=dish_number,
        is_active=True,
    )
    session.add(item)
    await session.flush()
    return item


async def list_org_menu(
    session: AsyncSession, *, organization_id: int, active_only: bool = False
) -> list[OrgMenuItem]:
    stmt = select(OrgMenuItem).where(OrgMenuItem.organization_id == organization_id)
    if active_only:
        stmt = stmt.where(OrgMenuItem.is_active.is_(True))
    return list((await session.scalars(stmt.order_by(OrgMenuItem.id))).all())


async def set_branch_price(
    session: AsyncSession,
    *,
    organization_id: int,
    org_menu_item_id: int,
    restaurant_id: int,
    price_aed: Decimal,
) -> OrgBranchPrice:
    item = await session.get(OrgMenuItem, org_menu_item_id)
    if item is None or item.organization_id != organization_id:
        raise ValueError("menu item not found")
    branch = await session.get(Restaurant, restaurant_id)
    if branch is None or branch.organization_id != organization_id:
        raise ValueError("branch not found")
    existing = await session.scalar(
        select(OrgBranchPrice).where(
            OrgBranchPrice.org_menu_item_id == org_menu_item_id,
            OrgBranchPrice.restaurant_id == restaurant_id,
        )
    )
    if existing:
        existing.price_aed = _money(price_aed)
        await session.flush()
        return existing
    row = OrgBranchPrice(
        organization_id=organization_id,
        org_menu_item_id=org_menu_item_id,
        restaurant_id=restaurant_id,
        price_aed=_money(price_aed),
    )
    session.add(row)
    await session.flush()
    return row


async def request_menu_publish(
    session: AsyncSession,
    *,
    organization_id: int,
    target_restaurant_ids: list[int] | None = None,
    org_menu_item_ids: list[int] | None = None,
    requested_by: str = "hq",
    notes: str | None = None,
) -> OrgMenuPublishJob:
    job = OrgMenuPublishJob(
        organization_id=organization_id,
        status="pending",
        target_restaurant_ids=list(target_restaurant_ids or []),
        org_menu_item_ids=list(org_menu_item_ids or []),
        requested_by=requested_by,
        notes=notes,
    )
    session.add(job)
    await session.flush()
    await record_audit(
        session,
        restaurant_id=None,
        actor=requested_by,
        entity="org_menu_publish",
        entity_id=str(job.id),
        action="publish_requested",
        after={"organization_id": organization_id},
    )
    return job


async def approve_menu_publish(
    session: AsyncSession,
    *,
    organization_id: int,
    job_id: int,
    approved_by: str = "hq",
    approve: bool = True,
) -> OrgMenuPublishJob:
    job = await session.get(OrgMenuPublishJob, job_id)
    if job is None or job.organization_id != organization_id:
        raise ValueError("publish job not found")
    if job.status not in ("pending",):
        raise ValueError(f"job already {job.status}")
    if not approve:
        job.status = "rejected"
        job.approved_by = approved_by
        job.resolved_at = datetime.now(timezone.utc)
        await session.flush()
        return job
    job.status = "approved"
    job.approved_by = approved_by
    await session.flush()
    # execute publish
    return await execute_menu_publish(session, organization_id=organization_id, job=job)


async def execute_menu_publish(
    session: AsyncSession, *, organization_id: int, job: OrgMenuPublishJob
) -> OrgMenuPublishJob:
    from app.menu.models import Dish, Menu

    branches = await list_branches(session, organization_id=organization_id)
    targets = job.target_restaurant_ids or [b.id for b in branches]
    branch_map = {b.id: b for b in branches if b.id in targets}

    items = await list_org_menu(session, organization_id=organization_id, active_only=True)
    if job.org_menu_item_ids:
        allow = set(job.org_menu_item_ids)
        items = [i for i in items if i.id in allow]

    prices = list(
        (
            await session.scalars(
                select(OrgBranchPrice).where(
                    OrgBranchPrice.organization_id == organization_id
                )
            )
        ).all()
    )
    price_map: dict[tuple[int, int], Decimal] = {
        (p.org_menu_item_id, p.restaurant_id): p.price_aed for p in prices
    }

    published = 0
    for rid, branch in branch_map.items():
        menu = await session.scalar(
            select(Menu).where(Menu.restaurant_id == rid, Menu.status == "active")
        )
        if menu is None:
            menu = Menu(restaurant_id=rid, version=1, status="active", source_files=[])
            session.add(menu)
            await session.flush()
        for item in items:
            price = price_map.get((item.id, rid), item.base_price_aed)
            existing = await session.scalar(
                select(Dish).where(
                    Dish.restaurant_id == rid,
                    Dish.name_normalized == item.name.strip().lower(),
                )
            )
            if existing:
                existing.price_aed = price
                existing.category = item.category
                existing.description = item.description
                existing.name_ar = item.name_ar
                existing.is_available = item.is_active
                if item.dish_number is not None:
                    existing.dish_number = item.dish_number
            else:
                session.add(
                    Dish(
                        menu_id=menu.id,
                        restaurant_id=rid,
                        dish_number=item.dish_number,
                        name=item.name,
                        name_ar=item.name_ar,
                        description=item.description,
                        category=item.category,
                        price_aed=price,
                        is_available=item.is_active,
                        name_normalized=item.name.strip().lower(),
                    )
                )
            published += 1
    await session.flush()
    job.status = "published"
    job.resolved_at = datetime.now(timezone.utc)
    job.result = {"dishes_touched": published, "branches": list(branch_map.keys())}
    await session.flush()
    await record_audit(
        session,
        restaurant_id=None,
        actor=job.approved_by or "hq",
        entity="org_menu_publish",
        entity_id=str(job.id),
        action="published",
        after=job.result,
    )
    return job


async def bulk_update_branches(
    session: AsyncSession,
    *,
    organization_id: int,
    restaurant_ids: list[int],
    action: str,
    payload: dict[str, Any],
) -> dict:
    """Bulk ops: set_available, set_price_delta, set_region, set_currency."""
    branches = await list_branches(session, organization_id=organization_id)
    targets = [b for b in branches if b.id in set(restaurant_ids)]
    touched = 0

    if action == "set_region":
        region = payload.get("region")
        for b in targets:
            b.region = region
            touched += 1
    elif action == "set_currency":
        currency = str(payload.get("currency", "AED")).upper()[:8]
        for b in targets:
            b.currency = currency
            touched += 1
    elif action == "set_locale":
        locale = str(payload.get("locale", "en"))
        for b in targets:
            b.locale = locale
            touched += 1
    elif action in ("set_available", "set_price_delta"):
        from app.menu.models import Dish

        for b in targets:
            dishes = list(
                (
                    await session.scalars(
                        select(Dish).where(Dish.restaurant_id == b.id)
                    )
                ).all()
            )
            names = payload.get("dish_names")
            for d in dishes:
                if names and d.name not in names:
                    continue
                if action == "set_available":
                    d.is_available = bool(payload.get("is_available", True))
                    touched += 1
                else:
                    delta = Decimal(str(payload.get("price_delta_aed", "0")))
                    d.price_aed = _money((d.price_aed or Decimal("0")) + delta)
                    touched += 1
    else:
        raise ValueError(f"unknown bulk action: {action}")

    await session.flush()
    await record_audit(
        session,
        restaurant_id=None,
        actor="hq",
        entity="org_bulk_update",
        entity_id=str(organization_id),
        action=action,
        after={"touched": touched, "branches": [b.id for b in targets]},
    )
    return {"action": action, "touched": touched, "branch_count": len(targets)}


# ── Royalty & region reports ─────────────────────────────────────────────────


async def royalty_report(
    session: AsyncSession,
    *,
    organization_id: int,
    start_date: date,
    end_date: date,
    org: Organization | None = None,
) -> dict:
    from app.organizations.service import branch_comparison

    if org is None:
        org = await session.get(Organization, organization_id)
    pct = float(org.royalty_pct or 0) if org else 0.0
    rows = await branch_comparison(
        session, org_id=organization_id, start_date=start_date, end_date=end_date
    )
    out = []
    total_rev = Decimal("0")
    total_royalty = Decimal("0")
    for r in rows:
        rev = r["revenue_aed"]
        royalty = _money(rev * Decimal(str(pct)) / Decimal("100"))
        total_rev += rev
        total_royalty += royalty
        out.append(
            {
                "restaurant_id": r["restaurant_id"],
                "restaurant_name": r["restaurant_name"],
                "revenue_aed": str(_money(rev)),
                "royalty_pct": pct,
                "royalty_aed": str(royalty),
                "order_count": r["order_count"],
            }
        )
    return {
        "royalty_pct": pct,
        "total_revenue_aed": str(_money(total_rev)),
        "total_royalty_aed": str(_money(total_royalty)),
        "branches": out,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }


async def region_report(
    session: AsyncSession,
    *,
    organization_id: int,
    start_date: date,
    end_date: date,
) -> list[dict]:
    from datetime import datetime

    from app.ordering.models import Order

    day_start = datetime.combine(start_date, time.min)
    day_end = datetime.combine(end_date, time.max)
    branches = await list_branches(session, organization_id=organization_id)
    by_region: dict[str, dict] = {}
    for b in branches:
        region = b.region or "unassigned"
        bucket = by_region.setdefault(
            region,
            {
                "region": region,
                "branch_count": 0,
                "order_count": 0,
                "revenue_aed": Decimal("0"),
                "branches": [],
            },
        )
        orders = list(
            (
                await session.scalars(
                    select(Order).where(
                        Order.restaurant_id == b.id,
                        Order.created_at >= day_start,
                        Order.created_at <= day_end,
                        Order.status == "delivered",
                    )
                )
            ).all()
        )
        rev = sum((o.total or Decimal("0") for o in orders), Decimal("0"))
        bucket["branch_count"] += 1
        bucket["order_count"] += len(orders)
        bucket["revenue_aed"] = _money(bucket["revenue_aed"] + rev)
        bucket["branches"].append(
            {
                "restaurant_id": b.id,
                "name": b.name,
                "currency": b.currency,
                "revenue_aed": str(_money(rev)),
            }
        )
    return [
        {
            **v,
            "revenue_aed": str(v["revenue_aed"]),
        }
        for v in sorted(by_region.values(), key=lambda x: x["region"])
    ]


async def multi_currency_rollup(
    session: AsyncSession,
    *,
    organization_id: int,
    target_date: date,
    org: Organization,
) -> dict:
    """Rollup sales converted to org default currency using settings.fx_rates.

    Branch totals are stored in AED operationally; fx_rates maps AED→foreign
    (e.g. USD: 0.27). When branch.currency is AED, rate=1.
    """
    from app.reports.zreport import build_z_report

    fx = (org.settings or {}).get("fx_rates") or {}
    default_ccy = org.default_currency or "AED"
    branches = await list_branches(session, organization_id=organization_id)
    rows = []
    total_base = Decimal("0")
    for b in branches:
        z = await build_z_report(session, restaurant_id=b.id, target_date=target_date)
        gross_aed = z["gross_sales_aed"]
        ccy = (b.currency or "AED").upper()
        if ccy == "AED" or ccy == default_ccy:
            rate = Decimal("1")
            converted = gross_aed
        else:
            # fx_rates stored as foreign per 1 AED
            rate = Decimal(str(fx.get(ccy, "1")))
            converted = _money(gross_aed * rate)
        total_base += converted if default_ccy != "AED" else gross_aed
        rows.append(
            {
                "restaurant_id": b.id,
                "name": b.name,
                "currency": ccy,
                "gross_sales_aed": str(_money(gross_aed)),
                "fx_rate": str(rate),
                "gross_sales_org_currency": str(
                    _money(converted if default_ccy != "AED" else gross_aed)
                ),
            }
        )
    return {
        "org_currency": default_ccy,
        "total_org_currency": str(_money(total_base)),
        "branches": rows,
    }


# ── Shared customers / loyalty ───────────────────────────────────────────────


async def upsert_org_customer(
    session: AsyncSession,
    *,
    organization_id: int,
    phone: str,
    name: str | None = None,
    preferred_locale: str | None = None,
) -> OrgCustomer:
    phone = phone.strip()
    row = await session.scalar(
        select(OrgCustomer).where(
            OrgCustomer.organization_id == organization_id,
            OrgCustomer.phone == phone,
        )
    )
    if row:
        if name:
            row.name = name
        if preferred_locale:
            row.preferred_locale = preferred_locale
        await session.flush()
        return row
    row = OrgCustomer(
        organization_id=organization_id,
        phone=phone,
        name=name,
        preferred_locale=preferred_locale,
    )
    session.add(row)
    await session.flush()
    return row


async def credit_org_loyalty(
    session: AsyncSession,
    *,
    organization_id: int,
    phone: str,
    points: int,
    spend_aed: Decimal = Decimal("0"),
) -> OrgCustomer:
    cust = await upsert_org_customer(
        session, organization_id=organization_id, phone=phone
    )
    cust.loyalty_points = int(cust.loyalty_points or 0) + max(0, points)
    cust.total_orders = int(cust.total_orders or 0) + 1
    cust.total_spend_aed = _money(
        (cust.total_spend_aed or Decimal("0")) + spend_aed
    )
    await session.flush()
    return cust


async def list_org_customers(
    session: AsyncSession, *, organization_id: int, limit: int = 50
) -> list[OrgCustomer]:
    return list(
        (
            await session.scalars(
                select(OrgCustomer)
                .where(OrgCustomer.organization_id == organization_id)
                .order_by(OrgCustomer.total_spend_aed.desc())
                .limit(min(max(limit, 1), 200))
            )
        ).all()
    )


# ── Promotions ───────────────────────────────────────────────────────────────


async def create_org_promotion(
    session: AsyncSession,
    *,
    organization_id: int,
    code: str,
    title: str,
    discount_aed: Decimal = Decimal("0"),
    discount_pct: Decimal | None = None,
    target_restaurant_ids: list[int] | None = None,
) -> OrgPromotion:
    promo = OrgPromotion(
        organization_id=organization_id,
        code=code.strip().upper(),
        title=title,
        discount_aed=_money(discount_aed),
        discount_pct=discount_pct,
        status="active",
        target_restaurant_ids=list(target_restaurant_ids or []),
    )
    session.add(promo)
    await session.flush()
    return promo


async def push_promotion_to_branches(
    session: AsyncSession, *, organization_id: int, promo_id: int
) -> OrgPromotion:
    """Create restaurant coupons for each target branch."""
    from app.coupons.models import Coupon

    promo = await session.get(OrgPromotion, promo_id)
    if promo is None or promo.organization_id != organization_id:
        raise ValueError("promotion not found")
    branches = await list_branches(session, organization_id=organization_id)
    targets = promo.target_restaurant_ids or [b.id for b in branches]
    pushed = dict(promo.pushed_coupon_ids or {})
    for b in branches:
        if b.id not in targets:
            continue
        existing = await session.scalar(
            select(Coupon).where(
                Coupon.restaurant_id == b.id, Coupon.code == promo.code
            )
        )
        if existing:
            pushed[str(b.id)] = existing.id
            continue
        if promo.discount_pct is not None and Decimal(str(promo.discount_pct)) > 0:
            coupon = Coupon(
                restaurant_id=b.id,
                code=promo.code,
                kind="multi_use",
                discount_type="percent",
                discount_aed=None,
                percent=promo.discount_pct,
                status="active",
            )
        else:
            coupon = Coupon(
                restaurant_id=b.id,
                code=promo.code,
                kind="multi_use",
                discount_type="fixed",
                discount_aed=promo.discount_aed,
                status="active",
            )
        session.add(coupon)
        await session.flush()
        pushed[str(b.id)] = coupon.id
    promo.pushed_coupon_ids = pushed
    flag_modified(promo, "pushed_coupon_ids")
    await session.flush()
    return promo


# ── Org members (branch-scoped roles) ────────────────────────────────────────


async def create_org_member(
    session: AsyncSession,
    *,
    organization_id: int,
    email: str,
    name: str,
    role: str = "branch_manager",
    branch_ids: list[int] | None = None,
    pin: str | None = None,
) -> OrgMember:
    from app.identity.auth import hash_password

    if role not in ("hq_admin", "regional_manager", "branch_manager", "auditor"):
        raise ValueError("invalid role")
    member = OrgMember(
        organization_id=organization_id,
        email=email.strip().lower(),
        name=name,
        role=role,
        branch_ids=list(branch_ids or []),
        is_active=True,
        pin_hash=hash_password(pin) if pin else None,
    )
    session.add(member)
    await session.flush()
    return member


async def list_org_members(
    session: AsyncSession, *, organization_id: int
) -> list[OrgMember]:
    return list(
        (
            await session.scalars(
                select(OrgMember).where(OrgMember.organization_id == organization_id)
            )
        ).all()
    )


def member_can_access_branch(member: OrgMember, restaurant_id: int) -> bool:
    if not member.is_active:
        return False
    if member.role in ("hq_admin", "auditor"):
        return True
    if not member.branch_ids:
        return member.role == "regional_manager"
    return restaurant_id in member.branch_ids


# ── Central kitchen ──────────────────────────────────────────────────────────


async def create_central_kitchen_request(
    session: AsyncSession,
    *,
    organization_id: int,
    from_restaurant_id: int,
    items: list[dict],
    notes: str | None = None,
    central_kitchen_id: int | None = None,
) -> CentralKitchenRequest:
    branches = await list_branches(session, organization_id=organization_id)
    kitchens = [b for b in branches if b.is_central_kitchen]
    if central_kitchen_id is None:
        if not kitchens:
            raise ValueError("no central kitchen designated for organization")
        central_kitchen_id = kitchens[0].id
    else:
        if not any(b.id == central_kitchen_id and b.is_central_kitchen for b in branches):
            raise ValueError("central_kitchen_id is not a central kitchen branch")
    if not any(b.id == from_restaurant_id for b in branches):
        raise ValueError("from_restaurant not in organization")
    req = CentralKitchenRequest(
        organization_id=organization_id,
        from_restaurant_id=from_restaurant_id,
        central_kitchen_id=central_kitchen_id,
        status="pending",
        items=list(items),
        notes=notes,
    )
    session.add(req)
    await session.flush()
    return req


async def update_central_kitchen_status(
    session: AsyncSession,
    *,
    organization_id: int,
    request_id: int,
    status: str,
) -> CentralKitchenRequest:
    allowed = {"pending", "in_production", "ready", "shipped", "cancelled"}
    if status not in allowed:
        raise ValueError(f"status must be one of {sorted(allowed)}")
    req = await session.get(CentralKitchenRequest, request_id)
    if req is None or req.organization_id != organization_id:
        raise ValueError("request not found")
    req.status = status
    await session.flush()
    return req


async def list_central_kitchen_requests(
    session: AsyncSession, *, organization_id: int
) -> list[CentralKitchenRequest]:
    return list(
        (
            await session.scalars(
                select(CentralKitchenRequest)
                .where(CentralKitchenRequest.organization_id == organization_id)
                .order_by(CentralKitchenRequest.created_at.desc())
            )
        ).all()
    )
