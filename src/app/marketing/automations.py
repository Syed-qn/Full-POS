"""Preset marketing automation evaluators (Phase 4).

Four fixed presets — welcome, recurring, winback, reorder — backed by
``marketing_automations`` rows and hard-coded Python logic. Custom DSL
automations are deferred to Phase 4b.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.marketing.models import (
    MarketingAutomation,
    MarketingAutomationSend,
    RecurringMessageState,
    Segment,
)
from app.marketing.segments import evaluate_segment
from app.marketing.todays_special import (
    DEFAULT_LEAD_MINUTES,
    MIN_ORDERS,
    MIN_ORDERS_WEEKDAY,
    is_personalized,
    parse_hhmm,
)
from app.ordering.habits import habit_for_weekday
from app.ordering.models import Customer, Order
from app.ordering.service import predict_order_time

_DUBAI = ZoneInfo("Asia/Dubai")

PRESET_KEYS = ("welcome", "winback", "reorder", "recurring", "birthday", "review_request")

PRESET_DEFAULTS: dict[str, dict] = {
    "welcome": {
        "title": "Welcome offer",
        "description": "Send a one time promo 1 hour after a customer's first order.",
        "config": {"delay_hours": 1},
    },
    "recurring": {
        "title": "Recurring promo",
        "description": "Day 3 after each order, then weekly on the same day.",
        "config": {"lead_minutes": 15},
    },
    "winback": {
        "title": "Win back",
        "description": "Bring back customers inactive 60+ days.",
        "config": {"lapsed_days": 60, "cooldown_days": 60},
    },
    "reorder": {
        "title": "Reorder reminder",
        "description": "Nudge habitual customers before their usual order time.",
        "config": {"lead_minutes": 15},
    },
    "birthday": {
        "title": "Birthday offer",
        "description": "Send a birthday coupon to customers on their birthday.",
        "config": {"discount_aed": 15, "cooldown_days": 360},
    },
    "review_request": {
        "title": "Review request",
        "description": "Ask for NPS/feedback 2 hours after delivery.",
        "config": {"delay_hours": 2},
    },
}

WINBACK_DSL: dict = {
    "all": [{"field": "last_order_days_ago", "op": "gt", "value": 60}],
}


def clamp_config(preset_key: str, config: dict | None) -> dict:
    """Clamp preset config knobs to allowed ranges."""
    raw = dict(config or {})
    defaults = PRESET_DEFAULTS[preset_key]["config"]
    out = {**defaults, **raw}
    if preset_key == "welcome":
        out["delay_hours"] = max(1, min(48, int(out.get("delay_hours", 1))))
    elif preset_key in ("recurring", "reorder"):
        out["lead_minutes"] = max(5, min(120, int(out.get("lead_minutes", 15))))
    elif preset_key == "winback":
        out["lapsed_days"] = max(30, min(180, int(out.get("lapsed_days", 60))))
        out["cooldown_days"] = max(30, min(180, int(out.get("cooldown_days", 60))))
    elif preset_key == "birthday":
        out["discount_aed"] = max(5, min(100, int(out.get("discount_aed", 15))))
        out["cooldown_days"] = max(300, min(400, int(out.get("cooldown_days", 360))))
    elif preset_key == "review_request":
        out["delay_hours"] = max(1, min(48, int(out.get("delay_hours", 2))))
    return out


async def birthday_customer_ids(
    session: AsyncSession, *, restaurant_id: int, automation: MarketingAutomation
) -> list[int]:
    """Customers with birthday today (for birthday offer automation)."""
    from app.loyalty.crm import birthday_customer_ids as _ids

    return await _ids(session, restaurant_id=restaurant_id)


async def review_request_customer_order_ids(
    session: AsyncSession, *, restaurant_id: int, automation: MarketingAutomation
) -> list[tuple[int, int]]:
    """(customer_id, order_id) pairs delivered delay_hours ago without NPS yet."""
    from app.loyalty.models import NpsResponse

    cfg = clamp_config("review_request", automation.config)
    delay = int(cfg.get("delay_hours", 2))
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=delay + 2)
    window_end = now - timedelta(hours=delay)
    orders = list(
        (
            await session.scalars(
                select(Order).where(
                    Order.restaurant_id == restaurant_id,
                    Order.status == "delivered",
                    Order.delivered_at.is_not(None),
                    Order.delivered_at >= window_start.replace(tzinfo=None),
                    Order.delivered_at <= window_end.replace(tzinfo=None),
                )
            )
        ).all()
    )
    if not orders:
        return []
    order_ids = [o.id for o in orders]
    already = set(
        (
            await session.scalars(
                select(NpsResponse.order_id).where(NpsResponse.order_id.in_(order_ids))
            )
        ).all()
    )
    return [
        (o.customer_id, o.id) for o in orders if o.id not in already and o.customer_id
    ]


def _minute_to_hhmm(minute: int) -> str:
    minute = minute % 1440
    h, m = divmod(minute, 60)
    return f"{h:02d}:{m:02d}"


def _utc_from_local(base: date, minute_of_day: int) -> datetime:
    h, m = divmod(minute_of_day % 1440, 60)
    local = datetime(base.year, base.month, base.day, h, m, tzinfo=_DUBAI)
    return local.astimezone(timezone.utc)


async def _dominant_order_weekday(session: AsyncSession, customer_id: int) -> int | None:
    """Most common Dubai weekday (0=Mon) from order history, or None."""
    rows = (
        await session.scalars(
            select(Order.created_at).where(
                Order.customer_id == customer_id,
                Order.status != "draft",
            )
        )
    ).all()
    if not rows:
        return None
    counts: Counter[int] = Counter()
    for created in rows:
        if created is None:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        counts[created.astimezone(_DUBAI).weekday()] += 1
    if not counts:
        return None
    return counts.most_common(1)[0][0]


async def _usual_send_hhmm(
    session: AsyncSession,
    customer: Customer,
    *,
    weekday: int | None = None,
) -> str:
    pred = await predict_order_time(session, customer.id, weekday=weekday)
    threshold = MIN_ORDERS_WEEKDAY if weekday is not None else MIN_ORDERS
    if is_personalized(pred, min_orders=threshold):
        return _minute_to_hhmm(pred.minute_of_day)  # type: ignore[union-attr]
    if weekday is not None:
        stored = habit_for_weekday(customer.usual_order_times or {}, weekday)
        if is_personalized(stored, min_orders=MIN_ORDERS_WEEKDAY):
            return _minute_to_hhmm(stored.minute_of_day)  # type: ignore[union-attr]
    if customer.usual_order_time:
        # Parse "Evenings (~8:20 PM)" style — fallback to default.
        import re

        m = re.search(r"(\d{1,2}):(\d{2})", customer.usual_order_time)
        if m:
            return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
    return "11:45"


async def upsert_recurring_state(
    session: AsyncSession,
    *,
    restaurant_id: int,
    customer: Customer,
    delivered_at: datetime,
    lead_minutes: int = DEFAULT_LEAD_MINUTES,
) -> RecurringMessageState:
    """Seed or refresh day3 recurring schedule after a delivered order."""
    if delivered_at.tzinfo is None:
        delivered_at = delivered_at.replace(tzinfo=timezone.utc)
    local = delivered_at.astimezone(_DUBAI)
    usual_hhmm = await _usual_send_hhmm(session, customer, weekday=local.weekday())
    send_minute = parse_hhmm(usual_hhmm, default=11 * 60 + 45) - lead_minutes
    target_date = local.date() + timedelta(days=3)
    next_send_at = _utc_from_local(target_date, send_minute)

    existing = (
        await session.execute(
            select(RecurringMessageState).where(
                RecurringMessageState.restaurant_id == restaurant_id,
                RecurringMessageState.customer_id == customer.id,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.phase = "day3"
        existing.weekday = local.weekday()
        existing.usual_send_local_time = usual_hhmm
        existing.next_send_at = next_send_at
        await session.flush()
        return existing

    row = RecurringMessageState(
        restaurant_id=restaurant_id,
        customer_id=customer.id,
        phase="day3",
        weekday=local.weekday(),
        usual_send_local_time=usual_hhmm,
        next_send_at=next_send_at,
    )
    session.add(row)
    await session.flush()
    return row


async def _refresh_usual_send_hhmm(
    session: AsyncSession,
    *,
    customer: Customer,
    weekday: int,
) -> str:
    """Habit drift: recompute send time from per-weekday ``usual_order_times``."""
    stored = habit_for_weekday(customer.usual_order_times or {}, weekday)
    if is_personalized(stored, min_orders=MIN_ORDERS_WEEKDAY):
        return _minute_to_hhmm(stored.minute_of_day)  # type: ignore[union-attr]
    pred = await predict_order_time(session, customer.id, weekday=weekday)
    if is_personalized(pred, min_orders=MIN_ORDERS_WEEKDAY):
        return _minute_to_hhmm(pred.minute_of_day)  # type: ignore[union-attr]
    return await _usual_send_hhmm(session, customer, weekday=weekday)


async def advance_recurring_state(
    session: AsyncSession,
    *,
    state: RecurringMessageState,
    lead_minutes: int,
    now_utc: datetime,
) -> None:
    """Advance recurring state after a successful send."""
    local_now = now_utc.astimezone(_DUBAI)
    customer = await session.get(Customer, state.customer_id)

    if state.phase == "weekly" and customer is not None:
        state.usual_send_local_time = await _refresh_usual_send_hhmm(
            session, customer=customer, weekday=state.weekday
        )

    usual_minute = parse_hhmm(state.usual_send_local_time, default=11 * 60 + 45)
    send_minute = usual_minute - lead_minutes

    if state.phase == "day3":
        state.phase = "weekly"
        days_ahead = (state.weekday - local_now.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        target = local_now.date() + timedelta(days=days_ahead)
        state.next_send_at = _utc_from_local(target, send_minute)
    else:
        target = state.next_send_at.astimezone(_DUBAI).date() + timedelta(days=7)
        state.next_send_at = _utc_from_local(target, send_minute)
    await session.flush()


async def filter_automation_audience(
    session: AsyncSession,
    *,
    restaurant_id: int,
    automation: MarketingAutomation,
    customer_ids: list[int],
) -> list[int]:
    """Apply optional segment override to a customer id list."""
    if not customer_ids:
        return []
    if automation.segment_id is None:
        return customer_ids
    seg = await session.get(Segment, automation.segment_id)
    if seg is None:
        return []
    seg_ids = set(
        await evaluate_segment(
            session, restaurant_id=restaurant_id, dsl=seg.definition
        )
    )
    return [cid for cid in customer_ids if cid in seg_ids]


async def winback_customer_ids(
    session: AsyncSession,
    *,
    restaurant_id: int,
    automation: MarketingAutomation,
    now_utc: datetime,
) -> list[int]:
    """Customers lapsed beyond threshold, respecting cooldown window."""
    cfg = clamp_config("winback", automation.config)
    lapsed = int(cfg["lapsed_days"])
    cooldown = int(cfg["cooldown_days"])
    dsl = {
        "all": [
            {"field": "last_order_days_ago", "op": "gt", "value": lapsed},
        ]
    }
    ids = await evaluate_segment(session, restaurant_id=restaurant_id, dsl=dsl)
    if not ids:
        return []
    cutoff = now_utc - timedelta(days=cooldown)
    recent = set(
        (
            await session.scalars(
                select(MarketingAutomationSend.customer_id).where(
                    MarketingAutomationSend.automation_id == automation.id,
                    MarketingAutomationSend.sent_at >= cutoff,
                )
            )
        ).all()
    )
    ids = [i for i in ids if i not in recent]
    return await filter_automation_audience(
        session,
        restaurant_id=restaurant_id,
        automation=automation,
        customer_ids=ids,
    )


async def record_automation_send(
    session: AsyncSession,
    *,
    restaurant_id: int,
    automation_id: int,
    customer_id: int,
    campaign_id: int | None,
    sent_at: datetime,
) -> bool:
    """Insert dedup ledger row; returns True if inserted."""
    stmt = (
        pg_insert(MarketingAutomationSend)
        .values(
            restaurant_id=restaurant_id,
            automation_id=automation_id,
            customer_id=customer_id,
            campaign_id=campaign_id,
            sent_at=sent_at,
        )
        .on_conflict_do_nothing(constraint="uq_marketing_automation_send")
        .returning(MarketingAutomationSend.id)
    )
    result = await session.execute(stmt)
    return result.first() is not None