"""UAE marketing send-window helpers (pure, timezone-aware).

UAE Cabinet Decision 56/2024 restricts telemarketing (incl. WhatsApp) to
09:00-18:00 UAE local time. Window hours are parameters so they stay
configurable from settings. All inputs/outputs are UTC; conversion to
Asia/Dubai happens internally.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_DUBAI = ZoneInfo("Asia/Dubai")


def is_within_uae_window(
    now_utc: datetime, *, start_hour: int = 9, end_hour: int = 18
) -> bool:
    """True iff ``now_utc`` falls inside the UAE send window.

    Converts to Asia/Dubai and tests ``start_hour <= local.hour < end_hour``.
    """
    local = now_utc.astimezone(_DUBAI)
    return start_hour <= local.hour < end_hour


def next_window_open(
    now_utc: datetime, *, start_hour: int = 9, end_hour: int = 18
) -> datetime:
    """Next UTC instant at which the send window opens.

    Today's open if ``now`` is before it, otherwise tomorrow's open. The
    ``end_hour`` parameter is accepted for signature symmetry with
    ``is_within_uae_window``; only ``start_hour`` defines the open instant.
    """
    local = now_utc.astimezone(_DUBAI)
    open_today = local.replace(
        hour=start_hour, minute=0, second=0, microsecond=0
    )
    target = open_today if local < open_today else open_today + timedelta(days=1)
    return target.astimezone(timezone.utc)
