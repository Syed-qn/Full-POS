from datetime import date
from decimal import Decimal
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.auth import UNUSABLE_PASSWORD_HASH, hash_password
from app.identity.models import Restaurant
from app.organizations.models import Organization


async def signup_organization(
    session: AsyncSession, *, name: str, owner_email: str, password: str
) -> Organization:
    org = Organization(name=name, owner_email=owner_email, password_hash=hash_password(password))
    session.add(org)
    await session.flush()
    return org


async def bootstrap_organization_for_restaurant(
    session: AsyncSession, restaurant: Restaurant
) -> tuple[Organization, bool]:
    """Idempotently attach ``restaurant`` to an Organization for multi-branch HQ.

    - If the restaurant already has ``organization_id``, return that org.
    - Else create an Organization from the restaurant's name/email (or link to an
      existing org that already uses the same owner email) and set
      ``restaurant.organization_id``.

    Used so a restaurant **owner** can open Branches with their normal login —
    no second organization email/password required. Branch **managers** must not
    call this (enforced at the router with ``require_role("owner")``).

    Returns ``(org, created_new_org)``.
    """
    if restaurant.organization_id is not None:
        org = await session.get(Organization, restaurant.organization_id)
        if org is None:
            raise ValueError("organization_missing")
        return org, False

    email = (restaurant.email or "").strip() or f"org-{restaurant.id}@branches.local"
    existing = await session.scalar(
        select(Organization).where(Organization.owner_email == email)
    )
    if existing is not None:
        restaurant.organization_id = existing.id
        await session.flush()
        return existing, False

    # Reuse the restaurant password hash when present so optional org email login
    # still works; otherwise mint an unusable random hash (HQ uses owner JWT).
    password_hash = (
        restaurant.password_hash
        if (restaurant.password_hash or "").strip()
        else hash_password(secrets.token_urlsafe(32))
    )
    org = Organization(
        name=(restaurant.name or "Organization").strip() or "Organization",
        owner_email=email,
        password_hash=password_hash,
    )
    session.add(org)
    await session.flush()
    restaurant.organization_id = org.id
    await session.flush()
    return org, True


async def add_branch(
    session: AsyncSession,
    *,
    organization_id: int,
    name: str,
    lat: float,
    lng: float,
    email: str | None = None,
    password: str | None = None,
    region: str | None = None,
    currency: str = "AED",
    locale: str = "en",
    is_central_kitchen: bool = False,
) -> Restaurant:
    """Create a sister store under ``organization_id``.

    A branch normally has NO login of its own. One owner account runs the whole
    organization and reaches each store through the branch switcher, which mints
    a per-branch token after checking ownership — so a second credential per
    store is one more thing to leak and rotate for no extra capability.

    Email and password stay OPTIONAL rather than being removed: an operator who
    genuinely wants a store to sign in on its own (a franchisee, say) can still
    supply them. Omitting them leaves the branch with the auto-generated
    placeholder email and an unusable password hash, so no credential exists to
    sign in with. The branch's location/coordinates come from the picker either
    way — a store is defined by where it is, not by an inbox.
    """
    from app.identity.models import DEFAULT_SETTINGS

    email_norm = (email or "").strip().lower()
    password_clean = (password or "").strip()

    # Half a credential is worse than none: an email with no password is an
    # account that looks signable-in but is not, and a password with no email
    # has nothing to sign in as.
    if bool(email_norm) != bool(password_clean):
        raise ValueError("email_and_password_together")
    if password_clean and len(password_clean) < 6:
        raise ValueError("password_min_6")

    if email_norm:
        existing = await session.scalar(
            select(Restaurant).where(Restaurant.email == email_norm)
        )
        if existing is not None:
            raise ValueError("email_already_registered")

    branch = Restaurant(
        name=name,
        lat=lat,
        lng=lng,
        password_hash=(
            hash_password(password_clean) if password_clean else UNUSABLE_PASSWORD_HASH
        ),
        organization_id=organization_id,
        region=region,
        currency=(currency or "AED").upper()[:8],
        locale=locale or "en",
        is_central_kitchen=is_central_kitchen,
        # New branches still run onboarding (menu / Meta) like a normal signup.
        settings={**DEFAULT_SETTINGS, "onboarding_complete": False},
    )
    # Assign only when given: the column's Python-side default mints a unique
    # ``r-<uuid>@auto.local`` placeholder, and passing None instead would violate
    # the NOT NULL constraint rather than trigger that default.
    if email_norm:
        branch.email = email_norm
    session.add(branch)
    await session.flush()
    return branch


async def list_branches(session: AsyncSession, *, organization_id: int) -> list[Restaurant]:
    rows = await session.scalars(
        select(Restaurant)
        .where(Restaurant.organization_id == organization_id)
        .order_by(Restaurant.id)
    )
    return list(rows)


def main_branch_id(branches: list[Restaurant], org: Organization) -> int | None:
    """Which store is the organization's main branch.

    There is no column for it. An organization is bootstrapped FROM its founding
    restaurant, copying that restaurant's email into ``owner_email``, so that
    match identifies the original store. Branches added later have either their
    own address or an ``@auto.local`` placeholder, neither of which can collide.

    Falls back to the lowest id when nothing matches — an org whose founding
    restaurant was renamed or deleted still has an oldest store, and returning
    None there would leave the UI with no default selection at all.
    """
    if not branches:
        return None
    owner_email = (org.owner_email or "").strip().lower()
    if owner_email:
        for b in branches:
            if (b.email or "").strip().lower() == owner_email:
                return b.id
    return min(b.id for b in branches)


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


async def organization_inventory_summary(
    session: AsyncSession, *, organization_id: int,
) -> dict:
    from app.inventory.service import inventory_valuation, list_low_stock

    branches = await list_branches(session, organization_id=organization_id)
    branch_rows = []
    total_value = Decimal("0.00")
    total_low_stock_count = 0

    for branch in branches:
        valuation = await inventory_valuation(session, restaurant_id=branch.id)
        low_stock_count = len(await list_low_stock(session, restaurant_id=branch.id))
        branch_value = valuation["total_value_aed"]
        total_value += branch_value
        total_low_stock_count += low_stock_count
        branch_rows.append({
            "restaurant_id": branch.id,
            "restaurant_name": branch.name,
            "inventory_value_aed": branch_value,
            "low_stock_count": low_stock_count,
        })

    return {
        "total_inventory_value_aed": total_value.quantize(Decimal("0.01")),
        "total_low_stock_count": total_low_stock_count,
        "branches": branch_rows,
    }


async def branch_comparison(
    session: AsyncSession, *, org_id: int, start_date: date, end_date: date
) -> list[dict]:
    """Order count + revenue per branch of `org_id` over [start_date, end_date]
    (inclusive), sorted by revenue descending. Revenue counts delivered orders
    only (consistent with rollup_sales' gross_sales_aed), order_count counts
    all orders placed in the window regardless of status.
    """
    from datetime import datetime, time

    from app.ordering.models import Order

    day_start = datetime.combine(start_date, time.min)
    day_end = datetime.combine(end_date, time.max)

    branches = await list_branches(session, organization_id=org_id)
    results = []
    for branch in branches:
        orders = (await session.scalars(
            select(Order).where(
                Order.restaurant_id == branch.id,
                Order.created_at >= day_start,
                Order.created_at <= day_end,
            )
        )).all()
        delivered = [o for o in orders if o.status == "delivered"]
        revenue = sum((o.total for o in delivered), Decimal("0.00"))
        results.append({
            "restaurant_id": branch.id,
            "restaurant_name": branch.name,
            "order_count": len(orders),
            "revenue_aed": revenue,
        })

    results.sort(key=lambda r: r["revenue_aed"], reverse=True)
    return results
