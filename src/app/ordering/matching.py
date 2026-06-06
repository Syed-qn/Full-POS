from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import select, text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from app.menu.models import Dish, Menu

# Floor for treating the top trigram hit as a real match. pg_trgm 1.6 scores a
# common typo like "chikn biryani" vs "chicken biryani" at ~0.58, so 0.5 keeps
# such hits while the 0.3 SQL pre-filter already discards genuine non-matches.
_SINGLE_THRESHOLD = 0.5
_GAP_THRESHOLD = 0.15


def normalize_name(raw: str) -> str:
    """Casefold, strip, drop punctuation while keeping unicode word chars.

    Unicode-aware: ``\\w`` retains letters/digits from any script (Arabic,
    CJK, accented Latin, …) so non-Latin dish names survive normalization
    instead of collapsing to an empty string. Punctuation/symbols become
    spaces, which are then collapsed. ``casefold`` is preferred over ``lower``
    for correct case-insensitive matching across scripts. pg_trgm computes
    bytewise trigrams, so similarity still works on the preserved unicode.
    """
    cleaned = re.sub(r"[^\w ]", " ", raw, flags=re.UNICODE)
    collapsed = re.sub(r"\s+", " ", cleaned)
    return collapsed.strip().casefold()


class MatchConfidence(StrEnum):
    DIRECT = "direct"        # 1 strong match; gap large enough
    AMBIGUOUS = "ambiguous"  # 2+ candidates within threshold of each other
    NO_MATCH = "no_match"    # nothing above floor


@dataclass
class MatchResult:
    confidence: MatchConfidence
    candidates: list[Dish] = field(default_factory=list)


async def _active_menu_id(session: "AsyncSession", restaurant_id: int) -> int | None:
    row = await session.scalar(
        select(Menu.id).where(
            Menu.restaurant_id == restaurant_id,
            Menu.status == "active",
        )
    )
    return row


async def find_dish_matches(
    session: "AsyncSession",
    restaurant_id: int,
    query: str,
) -> MatchResult:
    """Return a MatchResult for the customer's dish query.

    Flow:
    1. If query is a bare integer → exact dish_number lookup.
    2. Otherwise → pg_trgm similarity on name_normalized, ranked DESC.
    3. Apply DIRECT / AMBIGUOUS / NO_MATCH rules.
    """
    query = query.strip()
    menu_id = await _active_menu_id(session, restaurant_id)
    if menu_id is None:
        return MatchResult(confidence=MatchConfidence.NO_MATCH)

    # --- Number lookup ---
    if re.fullmatch(r"\d+", query):
        dish = await session.scalar(
            select(Dish).where(
                Dish.menu_id == menu_id,
                Dish.dish_number == int(query),
                Dish.is_available == True,  # noqa: E712
            )
        )
        if dish:
            return MatchResult(confidence=MatchConfidence.DIRECT, candidates=[dish])
        return MatchResult(confidence=MatchConfidence.NO_MATCH)

    # --- Trigram similarity ---
    normalized_query = normalize_name(query)
    rows = (
        await session.execute(
            text("""
                SELECT d.id, similarity(d.name_normalized, :q) AS sim
                FROM dishes d
                WHERE d.menu_id = :mid
                  AND d.is_available = true
                  AND d.name_normalized IS NOT NULL
                  AND similarity(d.name_normalized, :q) > 0.3
                ORDER BY sim DESC
                LIMIT 5
            """),
            {"q": normalized_query, "mid": menu_id},
        )
    ).fetchall()

    if not rows:
        return MatchResult(confidence=MatchConfidence.NO_MATCH)

    top_sim: float = rows[0].sim
    if top_sim < _SINGLE_THRESHOLD:
        return MatchResult(confidence=MatchConfidence.NO_MATCH)

    # Load top dish objects
    top_ids = [r.id for r in rows]
    dishes_map: dict[int, Dish] = {}
    for dish in (await session.scalars(select(Dish).where(Dish.id.in_(top_ids)))).all():
        dishes_map[dish.id] = dish

    top_dish = dishes_map[rows[0].id]

    if len(rows) == 1 or (top_sim - rows[1].sim) > _GAP_THRESHOLD:
        return MatchResult(confidence=MatchConfidence.DIRECT, candidates=[top_dish])

    # Multiple close candidates → AMBIGUOUS (return up to 3)
    candidates = [dishes_map[r.id] for r in rows[:3] if r.id in dishes_map]
    return MatchResult(confidence=MatchConfidence.AMBIGUOUS, candidates=candidates)
