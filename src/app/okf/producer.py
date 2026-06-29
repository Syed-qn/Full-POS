"""OKF producer — turn DB rows into Open Knowledge Format concept docs.

Each builder returns (slug, title, frontmatter, body, search_text, entity_id) and
``_upsert`` writes/refreshes the okf_docs row (stable on restaurant+kind+slug). The
bot retrieves these to answer grounded — never inventing facts the data doesn't have.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.okf.models import OkfDoc


def _yaml(frontmatter: dict) -> str:
    lines = ["---"]
    for k, v in frontmatter.items():
        if isinstance(v, list):
            lines.append(f"{k}: [{', '.join(str(x) for x in v)}]")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


async def _upsert(
    session: AsyncSession, *, restaurant_id: int, kind: str, slug: str,
    title: str, frontmatter: dict, body: str, search_text: str,
    entity_id: int | None = None, source_updated_at: datetime | None = None,
) -> OkfDoc:
    doc = await session.scalar(
        select(OkfDoc).where(
            OkfDoc.restaurant_id == restaurant_id, OkfDoc.kind == kind, OkfDoc.slug == slug
        )
    )
    full_body = f"{_yaml(frontmatter)}\n\n{body}".strip()
    st = search_text.lower()
    if doc is None:
        doc = OkfDoc(
            restaurant_id=restaurant_id, kind=kind, slug=slug, entity_id=entity_id,
            title=title, body=full_body, frontmatter=frontmatter, search_text=st,
            source_updated_at=source_updated_at,
        )
        session.add(doc)
    else:
        doc.title = title
        doc.body = full_body
        doc.frontmatter = frontmatter
        doc.search_text = st
        doc.entity_id = entity_id
        doc.source_updated_at = source_updated_at
    await session.flush()
    return doc


async def refresh_menu_and_policy(session: AsyncSession, *, restaurant_id: int) -> int:
    """(Re)build the restaurant, policy, and per-dish OKF docs. Returns doc count."""
    from app.identity.models import Restaurant
    from app.menu.models import Dish, Menu

    restaurant = await session.get(Restaurant, restaurant_id)
    if restaurant is None:
        return 0
    settings = restaurant.settings or {}
    n = 0

    # Restaurant profile.
    await _upsert(
        session, restaurant_id=restaurant_id, kind="restaurant", slug="restaurant",
        title=f"{restaurant.name} — profile",
        frontmatter={"type": "Restaurant", "title": restaurant.name},
        body=(
            f"# {restaurant.name}\n"
            f"Phone: {restaurant.phone}\n"
            f"Delivery radius: {settings.get('max_radius_km', 10)} km\n"
        ),
        search_text=f"{restaurant.name} restaurant phone {restaurant.phone}",
    )
    n += 1

    # Policy doc (COD, delivery fees, radius, hours).
    tiers = settings.get("delivery_fee_tiers", [])
    fee_lines = "\n".join(
        f"- up to {t.get('max_km')} km: AED {t.get('fee_aed')}" for t in tiers
    ) or "- standard delivery fee applies"
    hours = settings.get("open_hours", {}).get("days") if isinstance(settings.get("open_hours"), dict) else None
    body = (
        "# Delivery & ordering policy\n"
        "- Payment: Cash on Delivery (COD) only.\n"
        f"- Maximum delivery radius: {settings.get('max_radius_km', 10)} km.\n"
        "## Delivery fees\n" + fee_lines + "\n"
    )
    if hours:
        body += "## Opening hours\n" + "\n".join(
            f"- day {d}: {w[0]}–{w[1]}" for d, w in hours.items()
        ) + "\n"
    await _upsert(
        session, restaurant_id=restaurant_id, kind="policy", slug="policy",
        title="Delivery & ordering policy",
        frontmatter={"type": "Policy", "title": "Delivery & ordering policy",
                     "tags": ["cod", "delivery", "fees", "hours"]},
        body=body,
        search_text="policy cod cash delivery fee radius hours payment " + fee_lines,
    )
    n += 1

    # Per-dish docs (active menu).
    menu = await session.scalar(
        select(Menu).where(Menu.restaurant_id == restaurant_id, Menu.status == "active")
    )
    current_dish_slugs: set[str] = set()
    if menu is not None:
        dishes = (await session.scalars(select(Dish).where(Dish.menu_id == menu.id))).all()
        for d in dishes:
            current_dish_slugs.add(f"dish-{d.id}")
            tags = []
            desc = d.description or ""
            fm = {
                "type": "Dish", "title": d.name, "dish_number": d.dish_number,
                "price_aed": str(d.price_aed) if d.price_aed is not None else None,
                "category": d.category, "available": d.is_available, "tags": tags,
            }
            body = (
                f"# {d.name} (#{d.dish_number})\n"
                f"Category: {d.category or '—'}\n"
                f"Price: AED {d.price_aed if d.price_aed is not None else '—'}\n"
                f"Available: {'yes' if d.is_available else 'no'}\n"
            )
            if desc:
                body += f"\n{desc}\n"
            await _upsert(
                session, restaurant_id=restaurant_id, kind="dish", slug=f"dish-{d.id}",
                title=d.name, entity_id=d.id, frontmatter=fm, body=body,
                search_text=f"{d.name} {d.category or ''} {desc} dish menu",
            )
            n += 1

    # Prune dish docs no longer in the active menu (removed/replaced dishes) so the
    # bot can't ground on or offer a dish that's gone.
    stale = await session.scalars(
        select(OkfDoc).where(OkfDoc.restaurant_id == restaurant_id, OkfDoc.kind == "dish")
    )
    for doc in stale:
        if doc.slug not in current_dish_slugs:
            await session.delete(doc)
    await session.flush()
    return n


async def refresh_customer(session: AsyncSession, *, restaurant_id: int, customer_id: int) -> int:
    """Build/refresh the customer profile OKF doc (tier, wallet, usual order, recents)."""
    from app.ordering.models import Customer, Order
    from app.wallet import service as wallet

    c = await session.get(Customer, customer_id)
    if c is None or c.restaurant_id != restaurant_id:
        return 0
    acc = await wallet.get_or_create_account(session, restaurant_id=restaurant_id, customer_id=customer_id)
    bal = await wallet.balance(session, account_id=acc.id)
    recents = (
        await session.scalars(
            select(Order).where(Order.customer_id == customer_id, Order.restaurant_id == restaurant_id)
            .order_by(Order.id.desc()).limit(5)
        )
    ).all()
    recent_lines = "\n".join(
        f"- {o.order_number}: {o.status}, AED {o.total}" for o in recents
    ) or "- no past orders"
    fm = {
        "type": "Customer", "title": c.name or c.phone, "phone": c.phone,
        "loyalty_tier": c.loyalty_tier, "total_orders": c.total_orders,
        "total_spend_aed": str(c.total_spend), "wallet_balance_aed": str(bal),
    }
    body = (
        f"# {c.name or c.phone}\n"
        f"Phone: {c.phone}\n"
        f"Loyalty tier: {c.loyalty_tier or 'none'}\n"
        f"Wallet credit: AED {bal}\n"
        f"Total orders: {c.total_orders} · total spend: AED {c.total_spend}\n"
        "## Recent orders\n" + recent_lines + "\n"
    )
    await _upsert(
        session, restaurant_id=restaurant_id, kind="customer", slug=f"customer-{c.id}",
        title=c.name or c.phone, entity_id=c.id, frontmatter=fm, body=body,
        search_text=f"{c.name or ''} {c.phone} customer loyalty wallet orders history",
        source_updated_at=c.last_order_at,
    )
    return 1


async def refresh_order(session: AsyncSession, *, restaurant_id: int, order_id: int) -> int:
    """Build/refresh an order OKF doc (status, items, total, delivery)."""
    from app.ordering.models import Order, OrderItem

    o = await session.get(Order, order_id)
    if o is None or o.restaurant_id != restaurant_id:
        return 0
    items = (await session.scalars(select(OrderItem).where(OrderItem.order_id == o.id))).all()
    item_lines = "\n".join(f"- {it.qty}x {it.dish_name} (AED {it.price_aed})" for it in items) or "- (no items)"
    fm = {
        "type": "Order", "title": o.order_number, "status": o.status,
        "total_aed": str(o.total), "wallet_applied_aed": str(o.wallet_applied_aed),
    }
    body = (
        f"# Order {o.order_number}\n"
        f"Status: {o.status}\n"
        f"Total: AED {o.total} (wallet applied: AED {o.wallet_applied_aed})\n"
        "## Items\n" + item_lines + "\n"
    )
    await _upsert(
        session, restaurant_id=restaurant_id, kind="order", slug=f"order-{o.id}",
        title=o.order_number, entity_id=o.id, frontmatter=fm, body=body,
        search_text=f"{o.order_number} order status {o.status} " + " ".join(it.dish_name for it in items),
        source_updated_at=datetime.now(timezone.utc),
    )
    return 1
