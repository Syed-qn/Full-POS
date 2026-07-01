"""One per-line quantity policy for every order path (typed, catalogue, modify).

A single source of truth for "how many of one line is too many", so the catalogue
basket path enforces the same tenant ``max_item_qty`` guard as the typed-order path
(R-050) and W8 can reuse it for add/update/modify. Standalone: no DB, no imports
from the engine/service, so it stays importable from anywhere.
"""
from __future__ import annotations

from dataclasses import dataclass

_DEFAULT_MAX_ITEM_QTY = 10


class QuantityError(ValueError):
    """Raised when a single line's quantity is outside the allowed range.

    ``qty`` is the offending amount and ``max_qty`` the tenant threshold, so callers
    can build a localized reply without re-deriving the policy.
    """

    def __init__(self, qty: int, max_qty: int) -> None:
        self.qty = qty
        self.max_qty = max_qty
        super().__init__(f"quantity {qty} outside allowed range 1..{max_qty}")


@dataclass(frozen=True)
class QuantityPolicy:
    """Immutable per-line quantity bounds for one restaurant."""

    max_item_qty: int = _DEFAULT_MAX_ITEM_QTY

    @classmethod
    def from_restaurant(cls, settings) -> "QuantityPolicy":
        """Build the policy from a restaurant row OR its raw ``settings`` dict.

        Accepts either the ``Restaurant`` object (reads ``.settings``) or a settings
        dict directly, mirroring ``engine._max_item_qty`` (``settings.max_item_qty``,
        default 10). Malformed values fall back to the default.
        """
        obj = settings
        raw = getattr(obj, "settings", None)
        if raw is None and isinstance(obj, dict):
            raw = obj
        raw = raw or {}
        try:
            max_qty = int(raw.get("max_item_qty", _DEFAULT_MAX_ITEM_QTY))
        except (TypeError, ValueError):
            max_qty = _DEFAULT_MAX_ITEM_QTY
        if max_qty < 1:
            max_qty = _DEFAULT_MAX_ITEM_QTY
        return cls(max_item_qty=max_qty)

    def check_line(self, qty: int) -> int:
        """Return ``qty`` if within ``1..max_item_qty``; else raise ``QuantityError``."""
        if qty < 1 or qty > self.max_item_qty:
            raise QuantityError(qty, self.max_item_qty)
        return qty
