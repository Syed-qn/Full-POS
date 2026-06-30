"""Resale of cancelled-after-cooking orders (spec §3).

When the kitchen has already started an order that's then cancelled, the food
still exists. Instead of writing it off, offer it to the NEXT customer as a
**fast** (already-cooked) delivery at a manager-set discount. On accept, the
on-resale order is marked RESOLD and a fresh, discounted, READY deliverable order
is spun up for the new customer + their address, then dispatched — and batched
with any other items that customer is ordering.

Everything is config-driven via ``settings.resale`` (enabled / discount_type /
discount_value / max_age_minutes) — nothing hardcoded.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.ordering.fsm import OrderStatus
from app.ordering.fsm import transition as fsm_transition
from app.ordering.models import Order, OrderItem
from app.ordering.service import get_available_resale_orders

_ZERO = Decimal("0.00")
_CENT = Decimal("0.01")


def _resale_cfg(settings: dict | None) -> dict:
    """Resale config, with DEFAULT_SETTINGS merged in. Restaurants created BEFORE the
    `resale` block was added have no `settings["resale"]` (settings are raw JSONB, not
    merged with defaults on read), so without this fallback resale would be silently OFF
    for every existing restaurant. Per-key merge lets a partial block still get defaults."""
    from app.identity.models import DEFAULT_SETTINGS

    base = dict(DEFAULT_SETTINGS.get("resale", {}))
    base.update((settings or {}).get("resale", {}) or {})
    return base


def discounted_total(settings: dict, subtotal: Decimal) -> tuple[Decimal, Decimal]:
    """Return (discounted_subtotal, discount_amount) from settings.resale."""
    cfg = _resale_cfg(settings)
    sub = Decimal(str(subtotal))
    if cfg.get("discount_type") == "fixed":
        disc = Decimal(str(cfg.get("discount_value", 0) or 0))
    else:  # percent
        pct = Decimal(str(cfg.get("discount_value", 0) or 0))
        disc = (sub * pct / Decimal("100")).quantize(_CENT)
    disc = min(disc, sub).quantize(_CENT)
    return (sub - disc).quantize(_CENT), disc


async def resale_offer_for_customer(
    session: AsyncSession,
    *,
    restaurant_id: int,
    phone: str,
    settings: dict,
    receiver_name: str | None = None,
    address_id: int | None = None,
    now: datetime | None = None,
) -> dict | None:
    """Best available resale offer for this customer, or None.

    Honors enable flag, exclusion (same phone/person/address), and a freshness cap
    (``max_age_minutes`` from the order's cancellation time). Returns
    {order, original_subtotal, discounted_subtotal, discount_aed, age_minutes}.
    """
    cfg = _resale_cfg(settings)
    if not cfg.get("enabled"):
        return None
    now = now or datetime.now(timezone.utc)
    candidates = await get_available_resale_orders(
        session, restaurant_id, phone, receiver_name, address_id
    )
    max_age = cfg.get("max_age_minutes")
    best: Order | None = None
    best_age = None
    for o in candidates:
        ref = o.cancelled_at or o.created_at
        age_min = None
        if ref is not None:
            r = ref if ref.tzinfo else ref.replace(tzinfo=timezone.utc)
            age_min = (now - r).total_seconds() / 60.0
            if max_age and age_min > float(max_age):
                continue  # too old to offer
        # Prefer the freshest (smallest age).
        if best is None or (age_min is not None and (best_age is None or age_min < best_age)):
            best, best_age = o, age_min
    if best is None:
        return None
    disc_sub, disc_amt = discounted_total(settings, best.subtotal)
    return {
        "order": best,
        "original_subtotal": Decimal(str(best.subtotal)),
        "discounted_subtotal": disc_sub,
        "discount_aed": disc_amt,
        "age_minutes": best_age,
    }


async def accept_resale(
    session: AsyncSession,
    *,
    resale_order: Order,
    customer_id: int,
    address_id: int | None,
    settings: dict,
    distance_km: float | None = None,
    delivery_fee_aed: Decimal | None = None,
    companion_order: Order | None = None,
    actor: str = "customer",
) -> Order:
    """Sell the resale food to a new customer. Marks the on-resale order RESOLD and
    creates a fresh, discounted, READY deliverable order for the new customer +
    address, then dispatches it (batched with ``companion_order`` if given — the
    customer's other freshly-ordered items). Returns the new deliverable order.
    Caller commits.
    """
    if str(resale_order.status) != str(OrderStatus.ON_RESALE):
        raise ValueError(f"order {resale_order.id} is not on resale")

    disc_sub, disc_amt = discounted_total(settings, resale_order.subtotal)
    fee = Decimal(str(delivery_fee_aed)) if delivery_fee_aed is not None else _ZERO

    # New deliverable order (food already cooked → goes straight to READY).
    count = await session.scalar(
        select(func.count()).select_from(Order)
        .where(Order.restaurant_id == resale_order.restaurant_id)
    ) or 0
    new_order = Order(
        restaurant_id=resale_order.restaurant_id,
        customer_id=customer_id,
        order_number=f"{resale_order.order_number}-SOLD{count + 1:04d}",
        status=OrderStatus.READY,  # cooked food, ready to dispatch
        priority="normal",
        address_id=address_id,
        distance_km=distance_km,
        subtotal=disc_sub,
        delivery_fee_aed=fee,
        total=(disc_sub + fee).quantize(_CENT),
        resale_of_order_id=resale_order.id,
        additional_details=f"Resale of {resale_order.order_number} ({disc_amt} off)",
    )
    session.add(new_order)
    await session.flush()

    # Clone the cooked items.
    items = (
        await session.scalars(select(OrderItem).where(OrderItem.order_id == resale_order.id))
    ).all()
    for it in items:
        session.add(
            OrderItem(
                order_id=new_order.id, dish_id=it.dish_id, dish_number=it.dish_number,
                dish_name=it.dish_name, variant_name=it.variant_name,
                price_aed=it.price_aed, qty=it.qty, notes=it.notes,
            )
        )
    await session.flush()

    # Mark the on-resale order sold.
    await fsm_transition(
        session, resale_order, OrderStatus.RESOLD, actor=actor,
        extra_audit={"sold_as_order_id": new_order.id},
    )

    # If the customer also ordered fresh dishes, push that order to READY too so
    # dispatch batches both into one rider trip to the same address.
    if companion_order is not None and str(companion_order.status) in (
        str(OrderStatus.CONFIRMED), str(OrderStatus.PREPARING),
    ):
        if str(companion_order.status) == str(OrderStatus.CONFIRMED):
            await fsm_transition(session, companion_order, OrderStatus.PREPARING, actor=actor)
        await fsm_transition(session, companion_order, OrderStatus.READY, actor=actor)

    await record_audit(
        session, actor=actor, restaurant_id=resale_order.restaurant_id,
        entity="order", entity_id=str(new_order.id), action="resale_accepted",
        before={"resale_of": resale_order.id},
        after={"discount_aed": str(disc_amt), "total": str(new_order.total)},
    )

    # Dispatch the ready resale (and companion) order(s) to the new location.
    try:
        from app.dispatch.service import run_dispatch_engine

        await run_dispatch_engine(session, restaurant_id=resale_order.restaurant_id)
    except Exception:  # noqa: BLE001 — dispatch retried by the periodic sweep
        pass

    return new_order
