"""Today's Special automation — per-customer send-time logic (pure helpers).

When a restaurant enables Today's Special, every opted-in customer is sent the
daily special a few minutes *before* their own predicted ordering time (e.g. a
customer who reliably orders ~12:00 gets it at ~11:45). The timing comes from
``app.ordering.service.predict_order_time``; this module turns that prediction
into a concrete "minute of the Dubai day" to fire at, and decides whether a
given tick is the moment to send.

All functions are pure and timezone-free (they work in Asia/Dubai minute-of-day
integers, 0..1439) so they're trivially unit-testable. The orchestration that
queries customers and enqueues messages lives in ``marketing.service``.
"""

from __future__ import annotations

from app.ordering.service import OrderTimePrediction

# Optional UAE Cabinet Decision 56/2024 send window (09:00-18:00 Asia/Dubai),
# applied only when APP_MARKETING_SEND_WINDOW_ENABLED is on (off by default —
# WhatsApp is treated as exempt). When enabled, a predicted send time is clamped
# into [WINDOW_START, WINDOW_END); otherwise the real minute-of-day is kept.
WINDOW_START_MIN = 9 * 60   # 09:00 -> 540
WINDOW_END_MIN = 18 * 60    # 18:00 -> 1080 (exclusive; last sendable minute 1079)

# A customer must have at least this many orders, clustered tightly enough
# (resultant length R), before we trust their personal time. Otherwise we fall
# back to the restaurant's default time. "3 orders around noon" is the canonical
# signal this encodes.
MIN_ORDERS = 3
MIN_CONCENTRATION = 0.5

# Default lead time and how late a missed tick may still fire (so a cron that
# skips a beat still delivers, but a noon special never goes out at 5pm).
DEFAULT_LEAD_MINUTES = 15
DEFAULT_MAX_LATE_MINUTES = 90


def parse_hhmm(value: str | None, *, default: int) -> int:
    """Parse a "HH:MM" string into a Dubai minute-of-day, else ``default``."""
    if not value:
        return default
    try:
        hh, mm = str(value).split(":")
        h, m = int(hh), int(mm)
    except (ValueError, AttributeError):
        return default
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return default
    return h * 60 + m


def _clamp_to_window(minute: int) -> int:
    """Clamp a minute-of-day into the [09:00, 18:00) UAE send window."""
    if minute < WINDOW_START_MIN:
        return WINDOW_START_MIN
    if minute > WINDOW_END_MIN - 1:
        return WINDOW_END_MIN - 1
    return minute


def is_personalized(pred: OrderTimePrediction | None) -> bool:
    """True when a prediction is trustworthy enough to use the customer's own time."""
    return (
        pred is not None
        and pred.order_count >= MIN_ORDERS
        and pred.concentration >= MIN_CONCENTRATION
    )


def desired_send_minute(
    pred: OrderTimePrediction | None,
    *,
    lead_minutes: int = DEFAULT_LEAD_MINUTES,
    default_minute: int,
    clamp_window: bool = True,
    window: tuple[int, int] | None = None,
) -> int:
    """Dubai minute-of-day to send a customer's special.

    Personalized (enough clustered orders) → ``predicted - lead_minutes``.
    Otherwise → the restaurant ``default_minute``.

    ``window`` — a restaurant's own custom [start, end] minute-of-day range
    (the "Custom time" send window, e.g. only 18:00-22:00) — takes precedence and
    clamps the result into it. Otherwise the legacy UAE 09:00-18:00 window applies
    only when ``clamp_window`` is set; with neither, the raw minute-of-day is kept.
    """
    if is_personalized(pred):
        base = pred.minute_of_day - lead_minutes  # type: ignore[union-attr]
    else:
        base = default_minute
    if window is not None:
        lo, hi = window
        return min(max(base, lo), hi)
    if clamp_window:
        return _clamp_to_window(base)
    return base % 1440


def is_due(
    desired_minute: int,
    now_minute: int,
    *,
    max_late_minutes: int = DEFAULT_MAX_LATE_MINUTES,
) -> bool:
    """True iff ``now`` is at/after the desired minute but not more than
    ``max_late_minutes`` past it — so the first tick on or shortly after the
    target fires, a missed tick still catches up, but stale targets are skipped.
    """
    return desired_minute <= now_minute < desired_minute + max_late_minutes
