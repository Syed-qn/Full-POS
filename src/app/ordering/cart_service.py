"""CartService — single owner of cart mutations for ordering.

All add / set-qty / set-note / remove / clear operations go through this
class so callers never scatter raw ORM writes across engine and catalogue paths.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.ordering.models import Order, OrderItem


# -- Prefix normalisation ----------------------------------------------------
_NOTE_PREFIX_RE = re.compile(
    r"^(?:please|pls|kindly|add|make\s+it|make|put|keep\s+it|keep"
    r"|can\s+you|could\s+you|i\s+want|i\s+need|i\s+would\s+like"
    r"|i'd\s+like|id\s+like)\s+",
    re.IGNORECASE,
)


def normalize_note(raw: str) -> str:
    """Strip politeness/action prefixes from a kitchen note before storing.

    'pls add extra masala' -> 'extra masala'
    'please make it spicy'  -> 'spicy'
    Empty / whitespace input -> empty string.
    """
    text = (raw or "").strip()
    changed = True
    while changed and text:
        new_text = _NOTE_PREFIX_RE.sub("", text, count=1).strip()
        changed = new_text != text
        text = new_text
    return text


@dataclass
class CartLineContext:
    """Structured representation of one cart line for LLM context injection."""

    cart_item_id: int
    dish_id: int
    dish_name: str
    variant_name: str | None
    notes: str | None
    qty: int
    price_aed: Decimal


class CartService:
    """Facade over the ordering service functions.

    All callers (conversation engine, catalogue order handler) should go through
    this class so cart semantics (merge key, note preservation, explicit-clear)
    are enforced in one place.
    """

    def __init__(self, session: "AsyncSession") -> None:
        self._session = session

    async def add(
        self,
        *,
        order: "Order",
        dish,
        qty: int = 1,
        notes: str | None = None,
        variant: dict | None = None,
    ) -> "OrderItem":
        """Add or merge a dish into the cart (delegates to service.add_item)."""
        from app.ordering.service import add_item

        return await add_item(
            self._session,
            order=order,
            dish=dish,
            qty=qty,
            notes=notes,
            variant=variant,
        )

    async def set_qty(
        self,
        *,
        order: "Order",
        dish_id: int,
        qty: int,
        variant_name: str | None = None,
    ) -> "OrderItem | None":
        """Set exact quantity, preserving notes (delegates to service.set_item_qty)."""
        from app.ordering.service import set_item_qty

        return await set_item_qty(
            self._session,
            order=order,
            dish_id=dish_id,
            qty=qty,
            variant_name=variant_name,
        )

    async def set_note(
        self,
        *,
        order: "Order",
        dish_id: int,
        raw_note: str,
        qty: int | None = None,
    ) -> "OrderItem | None":
        """Apply a normalised kitchen note to an in-cart dish.

        Strips politeness/action prefixes (F101/TX-30) via normalize_note()
        before storing; delegates to service.set_item_note.
        """
        from app.ordering.service import set_item_note

        clean = normalize_note(raw_note)
        if not clean:
            return None
        return await set_item_note(
            self._session, order=order, dish_id=dish_id, notes=clean, qty=qty
        )

    async def remove(
        self,
        *,
        order: "Order",
        dish,
        qty: int = 1,
    ) -> int:
        """Remove units of a dish from the cart."""
        from app.ordering.service import remove_item

        return await remove_item(self._session, order=order, dish=dish, qty=qty)

    async def clear(self, *, order: "Order", explicit: bool) -> None:
        """Delete ALL items from the cart.

        Raises ValueError when *explicit* is False -- cart clears are structural
        and must only happen when the customer explicitly requested it (F82).
        Never infer a clear from 'only X' -- that routes to set_qty.
        """
        if not explicit:
            raise ValueError(
                "cart_clear requires explicit=True; never infer a clear from 'only X' (F82)"
            )
        from sqlalchemy import delete as sa_delete

        from app.ordering.models import OrderItem

        await self._session.execute(
            sa_delete(OrderItem).where(OrderItem.order_id == order.id)
        )
        order.subtotal = Decimal("0.00")
        order.total = order.delivery_fee_aed
        await self._session.flush()

    async def build_structured_context(self, order: "Order") -> list[CartLineContext]:
        """Return structured cart lines with stable cart_item_id for LLM context (F64)."""
        from sqlalchemy import select

        from app.ordering.models import OrderItem

        rows = (
            await self._session.scalars(
                select(OrderItem)
                .where(OrderItem.order_id == order.id)
                .order_by(OrderItem.id)
            )
        ).all()
        return [
            CartLineContext(
                cart_item_id=r.id,
                dish_id=r.dish_id,
                dish_name=r.dish_name,
                variant_name=r.variant_name,
                notes=r.notes,
                qty=r.qty,
                price_aed=r.price_aed,
            )
            for r in rows
        ]
