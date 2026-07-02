"""Map partner POS kitchen labels onto our order FSM targets."""
from __future__ import annotations

from app.ordering.fsm import OrderStatus

# POS → our kitchen target (Phase 2). Extend per partner later if needed.
POS_KITCHEN_STATUS: dict[str, OrderStatus | str] = {
    "accepted": OrderStatus.CONFIRMED,
    "preparing": OrderStatus.PREPARING,
    "ready": OrderStatus.READY,
    "cancelled": "cancelled",
}

_ALLOWED_POS_LABELS = frozenset(POS_KITCHEN_STATUS.keys())


def parse_pos_kitchen_status(label: str) -> OrderStatus | str:
    """Normalize POS status string; raises ValueError if unknown."""
    key = (label or "").strip().lower()
    if key not in _ALLOWED_POS_LABELS:
        allowed = ", ".join(sorted(_ALLOWED_POS_LABELS))
        raise ValueError(f"Unknown kitchen status '{label}'. Allowed: {allowed}")
    return POS_KITCHEN_STATUS[key]