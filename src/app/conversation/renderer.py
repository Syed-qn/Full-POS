"""Pure DB renderer for cart and order summary (W3/RA-1/R-013/R-040).

Renders cart state from the database without touching the LLM. Functions here
NEVER import from engine.py (circular import); the shared money/note helpers are
reimplemented inline with identical logic.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


# ── helpers (must NOT import from engine.py — circular) ───────────────────────

def _aed(value) -> str:
    """Format a money value as a plain AED amount string.

    Identical logic to engine._aed: strips trailing zeros but never emits
    scientific notation (Decimal('5E+1') -> '50', not '5E+1').
    """
    return f"{Decimal(value).normalize():f}"


def _note_suffix(it) -> str:
    """Render an order item's special-note suffix (identical to engine._note_suffix)."""
    note = (getattr(it, "notes", None) or "").strip()
    return f" — {note}" if note else ""


# ── public API ────────────────────────────────────────────────────────────────

async def render_cart_state(
    session: AsyncSession,
    *,
    order,
    phase: str,
    locale: str | None = None,
) -> str:
    """Return a DB-backed cart/summary string for the given order and dialogue phase.

    Args:
        session: async SQLAlchemy session.
        order: Order ORM instance (may have no items yet).
        phase: "ordering" -> cart tail; "awaiting_confirmation" -> full summary text.
        locale: reserved for W7 localisation (unused in W3).

    Returns:
        For "ordering": "\\n\\n🛒 {items} | Subtotal: AED Y"
                        or "\\n\\n🛒 Your cart is now empty." when no items.
        For "awaiting_confirmation": full order summary text body (items, subtotal,
                                     fee, total, payment, deliver-to, ETA) — no buttons.
    """
    from app.ordering.models import OrderItem

    items = list(
        (await session.scalars(
            select(OrderItem).where(OrderItem.order_id == order.id)
        )).all()
    )

    if phase == "awaiting_confirmation":
        return await _render_confirmation_body(session, items, order)
    return _render_cart_tail(items, order)


# ── private render helpers ──────────────────────────────────────────────────────

def _render_cart_tail(items, order) -> str:
    """Render the \\n\\n🛒 cart tail for the ordering phase (mirrors engine._cart_tail)."""
    if not items:
        return "\n\n🛒 Your cart is now empty."
    lines = [
        f"{it.qty}x {it.dish_name}"
        f"{f' ({it.variant_name})' if it.variant_name else ''}"
        f"{_note_suffix(it)} "
        f"(AED {_aed(it.price_aed * it.qty)})"
        for it in items
    ]
    cart = ", ".join(lines) + f" | Subtotal: AED {_aed(order.subtotal)}"
    return f"\n\n🛒 {cart}"


async def _render_confirmation_body(session: AsyncSession, items, order) -> str:
    """Render the full order-summary text body for the awaiting_confirmation phase.

    Mirrors the body built by engine._send_order_summary (without the confirm/cancel
    buttons or the weather/redeem blocks, which stay engine-owned for now).
    """
    from app.ordering.models import CustomerAddress

    item_lines = "\n".join(
        f"  {it.qty}x {it.dish_name}"
        f"{f' ({it.variant_name})' if it.variant_name else ''}"
        f"{_note_suffix(it)}: "
        f"AED {_aed(it.price_aed * it.qty)}"
        for it in items
    )

    address_block = ""
    if order.address_id is not None:
        addr = await session.get(CustomerAddress, order.address_id)
        if addr is not None:
            parts = [p for p in (addr.room_apartment, addr.building) if p]
            addr_line = ", ".join(parts)
            if addr.receiver_name:
                addr_line = (
                    f"{addr_line} (for {addr.receiver_name})"
                    if addr_line
                    else f"For {addr.receiver_name}"
                )
            if addr_line:
                address_block = f"Deliver to: {addr_line}\n"

    # TODO(W5): wallet/coupon composition — insert the COD-due breakdown / redeem_block
    # here once W5 lands (wallet credit applied, pay-on-delivery line).
    return (
        f"Order summary:\n{item_lines}\n\n"
        f"Subtotal: AED {_aed(order.subtotal)}\n"
        f"Delivery fee: AED {_aed(order.delivery_fee_aed)}\n"
        f"Total: AED {_aed(order.total)}\n"
        f"Payment: COD (cash on delivery)\n"
        f"{address_block}"
        f"ETA: 40 minutes\n"
        f"\nConfirm your order?"
    )
