"""Time/channel/branch dish pricing rules.

A DishPriceRule overrides a dish's base ``price_aed`` when its conditions match the
moment/channel an order is being priced at (e.g. a "Happy Hour" time rule, a higher
price for aggregator channels, or a branch-specific price). Rules are additive
config on top of the existing Dish/variant/modifier/combo pricing — they do not
replace or duplicate those.
"""

from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import ForeignKey, Integer, Numeric, String, Time, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.audit.service import record_audit
from app.db import Base, TimestampMixin
from app.menu.models import Dish

_VALID_RULE_TYPES = ("time", "channel", "branch")
_DUBAI = ZoneInfo("Asia/Dubai")


class DishPriceRule(Base, TimestampMixin):
    __tablename__ = "dish_price_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    dish_id: Mapped[int] = mapped_column(ForeignKey("dishes.id"), index=True)
    rule_type: Mapped[str] = mapped_column(String(16))  # "time" | "channel" | "branch"
    # "time" rules: optional start/end (inclusive) + optional day-of-week filter.
    start_time: Mapped[time | None] = mapped_column(Time)
    end_time: Mapped[time | None] = mapped_column(Time)
    days_of_week: Mapped[list | None] = mapped_column(JSONB)  # 0=Mon ... 6=Sun; None=every day
    # "channel" rules: e.g. "delivery" | "dine_in" | "aggregator".
    channel: Mapped[str | None] = mapped_column(String(32))
    # "branch" rules: optional restaurant_id of the branch (multi-location).
    # Null branch_id + rule_type=branch still means "this restaurant's base override".
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("restaurants.id"), index=True)
    price_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))


async def create_price_rule(
    session: AsyncSession,
    *,
    restaurant_id: int,
    dish_id: int,
    rule_type: str,
    price_aed: Decimal,
    start_time: time | None = None,
    end_time: time | None = None,
    days_of_week: list[int] | None = None,
    channel: str | None = None,
    branch_id: int | None = None,
) -> DishPriceRule:
    if rule_type not in _VALID_RULE_TYPES:
        raise ValueError(f"unknown rule_type: {rule_type}")
    rule = DishPriceRule(
        restaurant_id=restaurant_id,
        dish_id=dish_id,
        rule_type=rule_type,
        price_aed=price_aed,
        start_time=start_time,
        end_time=end_time,
        days_of_week=days_of_week,
        channel=channel,
        branch_id=branch_id,
    )
    session.add(rule)
    await session.flush()
    return rule


async def list_price_rules(
    session: AsyncSession, *, restaurant_id: int, dish_id: int
) -> list[DishPriceRule]:
    return list((await session.scalars(
        select(DishPriceRule)
        .where(DishPriceRule.restaurant_id == restaurant_id, DishPriceRule.dish_id == dish_id)
        .order_by(DishPriceRule.id)
    )).all())


async def delete_price_rule(
    session: AsyncSession, *, restaurant_id: int, dish_id: int, rule_id: int
) -> None:
    rule = await session.get(DishPriceRule, rule_id)
    if rule is None or rule.restaurant_id != restaurant_id or rule.dish_id != dish_id:
        raise ValueError("price rule not found")
    before = {
        "rule_type": rule.rule_type,
        "price_aed": str(rule.price_aed),
        "channel": rule.channel,
    }
    await record_audit(
        session, actor="manager", restaurant_id=restaurant_id, entity="price_rule",
        entity_id=str(rule.id), action="deleted", before=before, after=None,
    )
    await session.delete(rule)
    await session.flush()


def _rule_matches(
    rule: DishPriceRule,
    *,
    at: datetime,
    channel: str | None,
    branch_id: int | None = None,
) -> bool:
    if rule.rule_type == "time":
        # Time/day-of-week rules are business-local (Asia/Dubai) — same convention as
        # conversation/hours.py and ordering/service.py. A naive `at` is assumed to
        # already be Asia/Dubai wall-clock time (matches how callers pass it today);
        # an aware datetime is converted so a UTC-aware `at` still compares correctly.
        local_at = at.astimezone(_DUBAI) if at.tzinfo is not None else at
        if rule.days_of_week is not None and local_at.weekday() not in rule.days_of_week:
            return False
        if rule.start_time is not None and rule.end_time is not None:
            t = local_at.time()
            if rule.start_time <= rule.end_time:
                if not (rule.start_time <= t <= rule.end_time):
                    return False
            else:
                # Window crosses midnight (e.g. 22:00-02:00).
                if not (t >= rule.start_time or t <= rule.end_time):
                    return False
        return True
    if rule.rule_type == "channel":
        return channel is not None and rule.channel == channel
    if rule.rule_type == "branch":
        # Match specific branch when rule.branch_id is set; otherwise match any
        # (restaurant-scoped override for this dish).
        if rule.branch_id is None:
            return True
        return branch_id is not None and rule.branch_id == branch_id
    return False


async def resolve_dish_price(
    session: AsyncSession,
    *,
    dish_id: int,
    at: datetime,
    channel: str | None = None,
    branch_id: int | None = None,
) -> Decimal:
    """Resolve the effective price for a dish at a given moment/channel/branch.

    FIRST-MATCHING-RULE WINS: rules are evaluated in creation (id) order and the first
    rule whose conditions match ``at``/``channel``/``branch_id`` decides the price.
    Falls back to the dish's base ``price_aed`` when no rule matches.
    """
    dish = await session.get(Dish, dish_id)
    if dish is None:
        raise ValueError(f"dish {dish_id} not found")
    rules = (
        await session.scalars(
            select(DishPriceRule)
            .where(DishPriceRule.dish_id == dish_id)
            .order_by(DishPriceRule.id)
        )
    ).all()
    for rule in rules:
        if _rule_matches(rule, at=at, channel=channel, branch_id=branch_id):
            return rule.price_aed
    return dish.price_aed
