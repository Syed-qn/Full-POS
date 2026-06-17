"""Per-recipient marketing throttle.

``can_send_marketing`` is a pure decision over already-fetched facts (keeps it
unit-testable; the service performs the DB queries). ``count_sends_last_24h`` is
the DB helper backing the per-user cap — Meta limits marketing template messages
to ~2 per user per rolling 24h across all businesses (error 131049); we enforce
our own tenant-scoped count as a guard.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.marketing.models import MarketingSend

# MarketingSend.status values that represent a delivered/attempted send and so
# consume the recipient's 24h marketing allowance.
_COUNTED_STATUSES: frozenset[str] = frozenset({"sent", "delivered", "read"})


@dataclass(frozen=True)
class SendDecision:
    allowed: bool
    reason: str  # "" if allowed; else suppressed_window|suppressed_optout|suppressed_cap


def can_send_marketing(
    *,
    now_utc: datetime,
    sends_last_24h: int,
    opted_out: bool,
    within_window: bool,
    per_user_cap: int = 2,
) -> SendDecision:
    """Decide per-recipient marketing eligibility.

    Order of checks: opt-out → window → cap. Returns the first failing reason;
    ``allowed=True`` only when all pass. ``now_utc`` is accepted for signature
    completeness and future time-based rules.
    """
    if opted_out:
        return SendDecision(allowed=False, reason="suppressed_optout")
    if not within_window:
        return SendDecision(allowed=False, reason="suppressed_window")
    if sends_last_24h >= per_user_cap:
        return SendDecision(allowed=False, reason="suppressed_cap")
    return SendDecision(allowed=True, reason="")


async def count_sends_last_24h(
    session: AsyncSession,
    *,
    restaurant_id: int,
    phone: str,
    now_utc: datetime,
) -> int:
    """Count this tenant's marketing sends to ``phone`` in the trailing 24h.

    Counts only delivered/attempted statuses (``sent|delivered|read``);
    suppressed and failed rows do not consume the recipient's allowance.
    """
    since = now_utc - timedelta(hours=24)
    result = await session.execute(
        select(func.count(MarketingSend.id)).where(
            MarketingSend.restaurant_id == restaurant_id,
            MarketingSend.to_phone == phone,
            MarketingSend.status.in_(_COUNTED_STATUSES),
            MarketingSend.sent_at >= since,
        )
    )
    return result.scalar_one()
