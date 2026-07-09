"""Category 6 CRM helpers — stamps, points, favorites, phone history, high-value list."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.loyalty.models import LoyaltyPointEntry, StampCard
from app.ordering.models import Customer, CustomerFavorite, CustomerPhoneHistory, Order, OrderItem

_ZERO = Decimal("0.00")


async def record_phone_change(
    session: AsyncSession,
    *,
    restaurant_id: int,
    customer_id: int,
    old_phone: str,
    changed_by: str = "manager",
) -> CustomerPhoneHistory:
    row = CustomerPhoneHistory(
        restaurant_id=restaurant_id,
        customer_id=customer_id,
        phone=old_phone,
        changed_by=changed_by,
    )
    session.add(row)
    await session.flush()
    return row


async def list_phone_history(
    session: AsyncSession, *, restaurant_id: int, customer_id: int
) -> list[CustomerPhoneHistory]:
    return list(
        (
            await session.scalars(
                select(CustomerPhoneHistory)
                .where(
                    CustomerPhoneHistory.restaurant_id == restaurant_id,
                    CustomerPhoneHistory.customer_id == customer_id,
                )
                .order_by(CustomerPhoneHistory.id.desc())
                .limit(50)
            )
        ).all()
    )


async def get_or_create_stamp_card(
    session: AsyncSession,
    *,
    restaurant_id: int,
    customer_id: int,
    stamps_required: int = 10,
) -> StampCard:
    card = await session.scalar(
        select(StampCard).where(
            StampCard.restaurant_id == restaurant_id,
            StampCard.customer_id == customer_id,
        )
    )
    if card is not None:
        return card
    card = StampCard(
        restaurant_id=restaurant_id,
        customer_id=customer_id,
        stamps=0,
        rewards_redeemed=0,
        stamps_required=stamps_required,
    )
    session.add(card)
    await session.flush()
    return card


async def add_stamp(
    session: AsyncSession,
    *,
    restaurant_id: int,
    customer_id: int,
    stamps_required: int = 10,
    count: int = 1,
) -> StampCard:
    card = await get_or_create_stamp_card(
        session,
        restaurant_id=restaurant_id,
        customer_id=customer_id,
        stamps_required=stamps_required,
    )
    card.stamps_required = stamps_required
    card.stamps = int(card.stamps or 0) + max(count, 0)
    await session.flush()
    return card


async def redeem_stamp_reward(
    session: AsyncSession,
    *,
    restaurant_id: int,
    customer_id: int,
) -> tuple[StampCard, object | None]:
    """Redeem one full stamp card for a wallet credit coupon amount AED 15."""
    from app.coupons.service import issue_coupon

    card = await get_or_create_stamp_card(
        session, restaurant_id=restaurant_id, customer_id=customer_id
    )
    need = int(card.stamps_required or 10)
    if int(card.stamps or 0) < need:
        raise ValueError(f"need {need} stamps, have {card.stamps}")
    card.stamps = int(card.stamps) - need
    card.rewards_redeemed = int(card.rewards_redeemed or 0) + 1
    coupon = await issue_coupon(
        session,
        restaurant_id=restaurant_id,
        customer_id=customer_id,
        order_id=None,
        discount_aed=Decimal("15.00"),
    )
    await session.flush()
    return card, coupon


async def award_loyalty_points(
    session: AsyncSession,
    *,
    restaurant_id: int,
    customer_id: int,
    points: int,
    reason: str,
    order_id: int | None = None,
    idempotency_key: str,
) -> int:
    """Credit or debit points. Returns new balance. Idempotent on key."""
    if points == 0:
        cust = await session.get(Customer, customer_id)
        return int(cust.loyalty_points or 0) if cust else 0
    existing = await session.scalar(
        select(LoyaltyPointEntry).where(LoyaltyPointEntry.idempotency_key == idempotency_key)
    )
    if existing is not None:
        cust = await session.get(Customer, customer_id)
        return int(cust.loyalty_points or 0) if cust else 0

    cust = await session.get(Customer, customer_id)
    if cust is None or cust.restaurant_id != restaurant_id:
        raise ValueError("customer not found")
    new_bal = max(int(cust.loyalty_points or 0) + points, 0)
    cust.loyalty_points = new_bal
    session.add(
        LoyaltyPointEntry(
            restaurant_id=restaurant_id,
            customer_id=customer_id,
            points=points,
            reason=reason,
            order_id=order_id,
            idempotency_key=idempotency_key,
        )
    )
    await session.flush()
    return new_bal


async def redeem_loyalty_points(
    session: AsyncSession,
    *,
    restaurant_id: int,
    customer_id: int,
    points: int,
    reason: str = "redeem",
) -> int:
    if points <= 0:
        raise ValueError("points must be positive")
    cust = await session.get(Customer, customer_id)
    if cust is None or cust.restaurant_id != restaurant_id:
        raise ValueError("customer not found")
    if int(cust.loyalty_points or 0) < points:
        raise ValueError("insufficient points")
    return await award_loyalty_points(
        session,
        restaurant_id=restaurant_id,
        customer_id=customer_id,
        points=-points,
        reason=reason,
        idempotency_key=f"points:redeem:{customer_id}:{points}:{datetime.now(timezone.utc).timestamp()}",
    )


async def refresh_favorites(
    session: AsyncSession, *, restaurant_id: int, customer_id: int, limit: int = 10
) -> list[CustomerFavorite]:
    """Rebuild top dishes from delivered/confirmed order items."""
    orders = list(
        (
            await session.scalars(
                select(Order).where(
                    Order.restaurant_id == restaurant_id,
                    Order.customer_id == customer_id,
                    Order.status.in_(
                        ("confirmed", "preparing", "out_for_delivery", "delivered", "ready")
                    ),
                )
            )
        ).all()
    )
    if not orders:
        return []
    order_ids = [o.id for o in orders]
    items = list(
        (
            await session.scalars(
                select(OrderItem).where(OrderItem.order_id.in_(order_ids))
            )
        ).all()
    )
    counter: Counter[tuple[int | None, str]] = Counter()
    for it in items:
        key = (it.dish_id, it.dish_name or f"dish-{it.dish_id}")
        counter[key] += int(it.qty or 1)

    # Clear existing and rewrite top N
    existing = list(
        (
            await session.scalars(
                select(CustomerFavorite).where(
                    CustomerFavorite.restaurant_id == restaurant_id,
                    CustomerFavorite.customer_id == customer_id,
                )
            )
        ).all()
    )
    for row in existing:
        await session.delete(row)
    await session.flush()

    favorites: list[CustomerFavorite] = []
    for (dish_id, dish_name), count in counter.most_common(limit):
        fav = CustomerFavorite(
            restaurant_id=restaurant_id,
            customer_id=customer_id,
            dish_id=dish_id,
            dish_name=dish_name,
            order_count=count,
        )
        session.add(fav)
        favorites.append(fav)
    await session.flush()
    return favorites


async def list_favorites(
    session: AsyncSession, *, restaurant_id: int, customer_id: int
) -> list[CustomerFavorite]:
    rows = list(
        (
            await session.scalars(
                select(CustomerFavorite)
                .where(
                    CustomerFavorite.restaurant_id == restaurant_id,
                    CustomerFavorite.customer_id == customer_id,
                )
                .order_by(CustomerFavorite.order_count.desc())
            )
        ).all()
    )
    if not rows:
        rows = await refresh_favorites(
            session, restaurant_id=restaurant_id, customer_id=customer_id
        )
    return rows


def compute_aov_clv(customer: Customer) -> dict:
    orders = int(customer.total_orders or 0)
    spend = Decimal(customer.total_spend or _ZERO)
    aov = (spend / orders).quantize(Decimal("0.01")) if orders > 0 else _ZERO
    # CLV approximation: historical spend (running lifetime value in this POS).
    return {
        "average_order_value_aed": aov,
        "customer_lifetime_value_aed": spend.quantize(Decimal("0.01")),
    }


async def high_value_customers(
    session: AsyncSession,
    *,
    restaurant_id: int,
    min_spend_aed: Decimal = Decimal("200"),
    min_orders: int = 3,
    limit: int = 50,
) -> list[Customer]:
    rows = list(
        (
            await session.scalars(
                select(Customer)
                .where(
                    Customer.restaurant_id == restaurant_id,
                    Customer.total_spend >= min_spend_aed,
                    Customer.total_orders >= min_orders,
                )
                .order_by(Customer.total_spend.desc())
                .limit(limit)
            )
        ).all()
    )
    return rows


async def birthday_customer_ids(
    session: AsyncSession, *, restaurant_id: int, on_date: date | None = None
) -> list[int]:
    """Customers whose birthday month-day matches today (Asia/Dubai calendar day)."""
    today = on_date or datetime.now(timezone.utc).date()
    rows = list(
        (
            await session.scalars(
                select(Customer).where(
                    Customer.restaurant_id == restaurant_id,
                    Customer.birthday.is_not(None),
                )
            )
        ).all()
    )
    return [
        c.id
        for c in rows
        if c.birthday is not None
        and c.birthday.month == today.month
        and c.birthday.day == today.day
    ]


async def on_delivery_crm_hooks(
    session: AsyncSession, *, order, customer: Customer, settings: dict
) -> None:
    """Stamps + points + favorites refresh after a successful delivery earn."""
    loyalty = (settings or {}).get("loyalty") or {}
    stamps_required = int(loyalty.get("stamp_card_required", 10) or 10)
    await add_stamp(
        session,
        restaurant_id=order.restaurant_id,
        customer_id=customer.id,
        stamps_required=stamps_required,
        count=1,
    )
    # 1 point per whole AED of subtotal (configurable via points_per_aed, default 1).
    rate = float(loyalty.get("points_per_aed", 1) or 1)
    pts = int(Decimal(str(order.subtotal or 0)) * Decimal(str(rate)))
    if pts > 0:
        await award_loyalty_points(
            session,
            restaurant_id=order.restaurant_id,
            customer_id=customer.id,
            points=pts,
            reason="order_earn",
            order_id=order.id,
            idempotency_key=f"points:earn:{order.id}",
        )
    await refresh_favorites(
        session, restaurant_id=order.restaurant_id, customer_id=customer.id
    )
    await record_audit(
        session,
        actor="system",
        restaurant_id=order.restaurant_id,
        entity="customer",
        entity_id=str(customer.id),
        action="crm_delivery_hooks",
        before=None,
        after={"order_id": order.id, "points": pts, "stamps_required": stamps_required},
    )
