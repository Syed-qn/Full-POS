"""Loyalty program — tiers (Phase 1) + earn-as-wallet-credit (Phase 2).

Everything is driven by per-restaurant ``settings.loyalty`` (no hardcoded
thresholds). Tiers are an RFM+Monetary cache on Customer, recomputed nightly and
on each delivery, with a demotion grace period, manager lock, welcome + recurring
reward coupons. Earning credits a % of food subtotal to the wallet on delivery.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit

_TIER_RANK = {None: 0, "bronze": 1, "silver": 2, "gold": 3}
_TIER_ORDER = ("gold", "silver", "bronze")
_TIER_EMOJI = {"gold": "🥇", "silver": "🥈", "bronze": "🥉"}
_ZERO = Decimal("0.00")


def _loyalty_cfg(settings: dict | None) -> dict:
    return (settings or {}).get("loyalty", {}) or {}


def _recency_days(last_order_at: datetime | None, now: datetime) -> float | None:
    if last_order_at is None:
        return None
    if last_order_at.tzinfo is None:
        last_order_at = last_order_at.replace(tzinfo=timezone.utc)
    return (now - last_order_at).total_seconds() / 86400.0


def _qualifies(tier_cfg: dict, *, total_orders: int, total_spend: Decimal, recency: float | None) -> bool:
    if total_orders < int(tier_cfg.get("min_orders", 0)):
        return False
    if Decimal(str(total_spend)) < Decimal(str(tier_cfg.get("min_spend_aed", 0))):
        return False
    max_recency = tier_cfg.get("max_recency_days")
    if max_recency is not None:
        if recency is None or recency > float(max_recency):
            return False
    return True


def compute_tier(
    cfg: dict, *, total_orders: int, total_spend: Decimal, last_order_at: datetime | None, now: datetime,
    recency_grace_days: float = 0.0,
) -> str | None:
    """Highest tier the customer qualifies for. ``recency_grace_days`` loosens the
    recency cap (used to KEEP a current tier during the grace window)."""
    tiers = cfg.get("tiers", {})
    recency = _recency_days(last_order_at, now)
    for name in _TIER_ORDER:
        tcfg = tiers.get(name)
        if not tcfg:
            continue
        tcfg = {**tcfg}
        if recency_grace_days and tcfg.get("max_recency_days") is not None:
            tcfg["max_recency_days"] = float(tcfg["max_recency_days"]) + recency_grace_days
        if _qualifies(tcfg, total_orders=total_orders, total_spend=total_spend, recency=recency):
            return name
    return None


async def recompute_tier(
    session: AsyncSession, *, customer, settings: dict, now: datetime | None = None,
    notify: bool = True,
) -> tuple[bool, str | None, str | None]:
    """Recompute one customer's tier. Honors lock + demotion grace. On upgrade/entry
    issues the welcome reward coupon and (best-effort) notifies. Returns
    (changed, old_tier, new_tier). Caller commits.
    """
    cfg = _loyalty_cfg(settings)
    if not cfg.get("enabled"):
        return (False, customer.loyalty_tier, customer.loyalty_tier)
    if customer.loyalty_tier_locked:
        return (False, customer.loyalty_tier, customer.loyalty_tier)

    now = now or datetime.now(timezone.utc)
    current = customer.loyalty_tier
    strict = compute_tier(
        cfg, total_orders=customer.total_orders, total_spend=customer.total_spend,
        last_order_at=customer.last_order_at, now=now,
    )

    new_tier = strict
    # Demotion grace: if strict would drop the tier, allow keeping it while still
    # within max_recency + grace (anti-thrash for a customer going briefly quiet).
    if _TIER_RANK[strict] < _TIER_RANK[current] and current is not None:
        grace = float(cfg.get("demotion_grace_days", 0) or 0)
        kept = compute_tier(
            cfg, total_orders=customer.total_orders, total_spend=customer.total_spend,
            last_order_at=customer.last_order_at, now=now, recency_grace_days=grace,
        )
        if _TIER_RANK[kept] >= _TIER_RANK[current]:
            new_tier = current  # still within grace — hold the tier

    if new_tier == current:
        return (False, current, current)

    old = current
    upgraded = _TIER_RANK[new_tier] > _TIER_RANK[old]
    customer.loyalty_tier = new_tier
    customer.loyalty_tier_since = now
    if upgraded:
        customer.loyalty_reward_anchor = customer.total_orders
    await record_audit(
        session, actor="system", restaurant_id=customer.restaurant_id,
        entity="customer", entity_id=str(customer.id), action="loyalty_tier_change",
        before={"tier": old}, after={"tier": new_tier},
    )
    if upgraded and new_tier is not None:
        await _issue_tier_reward(session, customer=customer, cfg=cfg, tier=new_tier,
                                 reason="welcome", notify=notify)
        if notify:
            await _notify_tier_up(session, customer=customer, tier=new_tier)
    return (True, old, new_tier)


async def maybe_issue_recurring_reward(
    session: AsyncSession, *, customer, settings: dict, notify: bool = True
) -> bool:
    """Issue the every-N-orders reward coupon if the customer just hit a multiple
    of the tier's ``every_n_orders`` since entering the tier. Caller commits."""
    cfg = _loyalty_cfg(settings)
    if not cfg.get("enabled") or not customer.loyalty_tier:
        return False
    rcfg = (cfg.get("tier_rewards", {}) or {}).get(customer.loyalty_tier)
    if not rcfg:
        return False
    every_n = int(rcfg.get("every_n_orders", 0) or 0)
    if every_n <= 0:
        return False
    held = customer.total_orders - (customer.loyalty_reward_anchor or 0)
    if held <= 0 or held % every_n != 0:
        return False
    await _issue_tier_reward(session, customer=customer, cfg=cfg, tier=customer.loyalty_tier,
                             reason=f"milestone:{held}", notify=notify)
    return True


async def _issue_tier_reward(
    session: AsyncSession, *, customer, cfg: dict, tier: str, reason: str, notify: bool
) -> None:
    from app.coupons.service import issue_coupon

    rcfg = (cfg.get("tier_rewards", {}) or {}).get(tier)
    if not rcfg:
        return
    discount = Decimal(str(rcfg.get("discount_aed", 0) or 0))
    if discount <= _ZERO:
        return
    coupon = await issue_coupon(
        session, restaurant_id=customer.restaurant_id, customer_id=customer.id,
        order_id=None, discount_aed=discount,
    )
    if not notify:
        return
    from app.identity.models import Restaurant
    from app.whatsapp.templates import notify_customer

    restaurant = await session.get(Restaurant, customer.restaurant_id)
    rname = restaurant.name if restaurant else "the restaurant"
    await notify_customer(
        session, restaurant_id=customer.restaurant_id, phone=customer.phone,
        session_text=(
            f"{_TIER_EMOJI.get(tier, '')} {tier.title()} reward! Coupon {coupon.code} — "
            f"AED {discount} off your next order at {rname}. 🎁"
        ),
        template_key="coupon_issued",
        variables=[rname, coupon.code, str(discount)],
        idempotency_key=f"loyalty:reward:{coupon.id}",
    )


async def _notify_tier_up(session: AsyncSession, *, customer, tier: str) -> None:
    """Best-effort tier-up nudge (engagement; session text only)."""
    from app.identity.models import Restaurant
    from app.outbox.service import enqueue_message
    from app.whatsapp.port import OutboundMessageType

    restaurant = await session.get(Restaurant, customer.restaurant_id)
    rname = restaurant.name if restaurant else "us"
    await enqueue_message(
        session, restaurant_id=customer.restaurant_id, to_phone=customer.phone,
        msg_type=OutboundMessageType.TEXT,
        payload={"body": f"{_TIER_EMOJI.get(tier, '')} You're now a {tier.title()} member at {rname}! Enjoy your perks. 🎉"},
        idempotency_key=f"loyalty:tierup:{customer.id}:{tier}:{customer.loyalty_tier_since.date().isoformat() if customer.loyalty_tier_since else 'x'}",
    )


def tier_progress_text(settings: dict, *, total_orders: int, total_spend: Decimal,
                       last_order_at: datetime | None, now: datetime | None = None) -> str:
    """Plain answer to 'what do I need to reach the next tier?' from settings."""
    cfg = _loyalty_cfg(settings)
    if not cfg.get("enabled"):
        return "We don't have a loyalty program right now 😊"
    now = now or datetime.now(timezone.utc)
    current = compute_tier(cfg, total_orders=total_orders, total_spend=total_spend,
                           last_order_at=last_order_at, now=now)
    tiers = cfg.get("tiers", {})
    # Find the next tier up from current.
    order_up = ["bronze", "silver", "gold"]
    start = order_up.index(current) + 1 if current in order_up else 0
    for name in order_up[start:]:
        tcfg = tiers.get(name)
        if not tcfg:
            continue
        need_orders = max(0, int(tcfg.get("min_orders", 0)) - total_orders)
        need_spend = max(_ZERO, Decimal(str(tcfg.get("min_spend_aed", 0))) - Decimal(str(total_spend)))
        parts = []
        if need_orders:
            parts.append(f"{need_orders} more order(s)")
        if need_spend > _ZERO:
            parts.append(f"AED {need_spend} more spend")
        gap = " and ".join(parts) if parts else "just keep ordering to stay active"
        cur_label = f"You're {current.title()}. " if current else ""
        return f"{cur_label}{need_orders or need_spend and '' or ''}To reach {name.title()} {_TIER_EMOJI.get(name,'')}: {gap}."
    return f"You're at our top tier{(' (' + current.title() + ')') if current else ''} 🏆 — thank you!"


async def set_manual_tier(
    session: AsyncSession, *, customer, tier: str | None, created_by: str
) -> None:
    """Manager override: set + lock the tier so recompute leaves it alone. Caller commits."""
    if tier is not None and tier not in _TIER_RANK:
        raise ValueError(f"invalid tier {tier!r}")
    before = {"tier": customer.loyalty_tier, "locked": customer.loyalty_tier_locked}
    customer.loyalty_tier = tier
    customer.loyalty_tier_locked = True
    customer.loyalty_tier_since = datetime.now(timezone.utc)
    customer.loyalty_reward_anchor = customer.total_orders
    await record_audit(
        session, actor=created_by, restaurant_id=customer.restaurant_id,
        entity="customer", entity_id=str(customer.id), action="loyalty_manual_tier",
        before=before, after={"tier": tier, "locked": True},
    )


async def unlock_tier(session: AsyncSession, *, customer, created_by: str) -> None:
    customer.loyalty_tier_locked = False
    await record_audit(
        session, actor=created_by, restaurant_id=customer.restaurant_id,
        entity="customer", entity_id=str(customer.id), action="loyalty_unlock",
        before={"locked": True}, after={"locked": False},
    )


async def earn(
    session: AsyncSession, *, order, settings: dict, notify: bool = False
) -> Decimal:
    """Phase 2: credit a % of food subtotal to the customer's wallet on delivery.
    Idempotent per order (wallet key). Returns the credited amount (0 if disabled).
    Caller commits.
    """
    cfg = _loyalty_cfg(settings)
    if not cfg.get("enabled"):
        return _ZERO
    rate = Decimal(str(cfg.get("earn_rate", 0) or 0))
    if rate <= _ZERO:
        return _ZERO
    amount = (Decimal(str(order.subtotal)) * rate).quantize(Decimal("0.01"))
    cap = Decimal(str(cfg.get("earn_max_per_order_aed", 0) or 0))
    if cap > _ZERO:
        amount = min(amount, cap)
    if amount <= _ZERO:
        return _ZERO
    from app.wallet import service as wallet
    await wallet.credit(
        session, restaurant_id=order.restaurant_id, customer_id=order.customer_id,
        amount=amount, idempotency_key=f"loyalty:earn:{order.id}",
        type="promo_credit", reason_note="loyalty earn", created_by="system",
    )
    return amount


async def reverse_earn(session: AsyncSession, *, order, created_by: str = "system") -> None:
    """Clawback the loyalty earn for an order (refund/cancel-after-deliver). Idempotent."""
    from sqlalchemy import select

    from app.wallet import service as wallet
    from app.wallet.models import WalletEntry

    entry = await session.scalar(
        select(WalletEntry).where(WalletEntry.idempotency_key == f"loyalty:earn:{order.id}")
    )
    if entry is None or entry.status != "posted":
        return
    await wallet.reverse(
        session, entry_id=entry.id, restaurant_id=order.restaurant_id,
        idempotency_key=f"loyalty:earn:reverse:{order.id}",
        reason_note="loyalty earn reversed (refund/cancel)", created_by=created_by,
    )
