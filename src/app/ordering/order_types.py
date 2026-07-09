"""Order fulfillment / channel types for Category-1 POS order management.

``Order.order_type`` is a free string constrained by this module's constants.
Legacy rows and WhatsApp defaults use ``delivery``.
"""

from __future__ import annotations

ORDER_TYPE_DELIVERY = "delivery"
ORDER_TYPE_DINE_IN = "dine_in"
ORDER_TYPE_TAKEAWAY = "takeaway"
ORDER_TYPE_DRIVE_THRU = "drive_thru"
ORDER_TYPE_QR = "qr"
ORDER_TYPE_TABLESIDE = "tableside"
ORDER_TYPE_AGGREGATOR = "aggregator"
ORDER_TYPE_ONLINE = "online"

ORDER_TYPES: frozenset[str] = frozenset(
    {
        ORDER_TYPE_DELIVERY,
        ORDER_TYPE_DINE_IN,
        ORDER_TYPE_TAKEAWAY,
        ORDER_TYPE_DRIVE_THRU,
        ORDER_TYPE_QR,
        ORDER_TYPE_TABLESIDE,
        ORDER_TYPE_AGGREGATOR,
        ORDER_TYPE_ONLINE,
    }
)

# Types that require a delivery address (lat/lng or building).
ADDRESS_REQUIRED_TYPES: frozenset[str] = frozenset(
    {
        ORDER_TYPE_DELIVERY,
        ORDER_TYPE_ONLINE,
        ORDER_TYPE_AGGREGATOR,
    }
)

# Types that bind to a physical dining table.
TABLE_BOUND_TYPES: frozenset[str] = frozenset(
    {
        ORDER_TYPE_DINE_IN,
        ORDER_TYPE_QR,
        ORDER_TYPE_TABLESIDE,
    }
)

# Non-terminal "open ticket" statuses for open-order lists.
OPEN_ORDER_STATUSES: frozenset[str] = frozenset(
    {
        "draft",
        "pending_confirmation",
        "confirmed",
        "preparing",
        "ready",
        "assigned",
        "picked_up",
        "arriving",
    }
)

PRIORITY_NORMAL = "normal"
PRIORITY_PRIORITY = "priority"
PRIORITY_RUSH = "rush"
PRIORITIES: frozenset[str] = frozenset(
    {PRIORITY_NORMAL, PRIORITY_PRIORITY, PRIORITY_RUSH}
)


def validate_order_type(order_type: str) -> str:
    value = (order_type or "").strip().lower()
    if value not in ORDER_TYPES:
        raise ValueError(
            f"invalid order_type {order_type!r}; allowed: {sorted(ORDER_TYPES)}"
        )
    return value


def validate_priority(priority: str) -> str:
    value = (priority or "").strip().lower()
    if value not in PRIORITIES:
        raise ValueError(
            f"invalid priority {priority!r}; allowed: {sorted(PRIORITIES)}"
        )
    return value


def requires_address(order_type: str) -> bool:
    return order_type in ADDRESS_REQUIRED_TYPES


def requires_table(order_type: str) -> bool:
    return order_type in TABLE_BOUND_TYPES
