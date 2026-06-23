from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import select, text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from app.menu.models import Dish, Menu

# word_similarity(query, name) finds the best match of the query within the name
# string — much better than similarity() when the customer types a partial name
# like "biriyani" against "chicken biryani". Thresholds tuned for this function:
# word_similarity("biriyani", "chicken biryani") ≈ 0.55; common typos ≥ 0.45.
_SINGLE_THRESHOLD = 0.4
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


def resolve_variant(dish: "Dish", query: str) -> dict | None:
    """Match a free-text size query against a dish's serving-size variants.

    Returns the matching variant dict (``{"name", "price_aed", "dish_number"}``) or
    None when nothing matches. Matching is in-memory (variants are JSONB on the dish,
    not a queryable table) and tolerant: exact normalized equality first, then
    substring/word-containment either direction (so "fam" → "Family", "family
    biryani" → "Family"). Returns None for a dish without variants.
    """
    variants = getattr(dish, "variants", None) or []
    if not variants:
        return None
    nq = normalize_name(query)
    if not nq:
        return None
    q_tokens = set(nq.split())
    # 1) exact normalized match wins outright.
    for v in variants:
        if normalize_name(v.get("name", "")) == nq:
            return v
    # 2) score each variant on shared signal and pick the SINGLE best. Scoring
    #    (not first-hit) avoids a word common to several variants — e.g. "serve"
    #    in both "1 serve"/"4 serve" — falsely matching whichever is listed first;
    #    the distinguishing token ("4") breaks the tie. Ambiguous ties → None.
    best_score = 0
    best: dict | None = None
    tie = False
    for v in variants:
        nv = normalize_name(v.get("name", ""))
        if not nv:
            continue
        score = len(q_tokens & set(nv.split()))
        if nv in nq or nq in nv:
            score += 2
        if score > best_score:
            best_score, best, tie = score, v, False
        elif score == best_score and score > 0:
            tie = True
    if best_score == 0 or tie:
        return None
    return best


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

    # --- Trigram word-similarity ---
    # word_similarity(query, name) scores how well the query matches any
    # contiguous extent within the dish name — better for "biriyani" vs
    # "chicken biryani" than the full-string similarity() function.
    normalized_query = normalize_name(query)
    rows = (
        await session.execute(
            text("""
                SELECT d.id, word_similarity(:q, d.name_normalized) AS sim
                FROM dishes d
                WHERE d.menu_id = :mid
                  AND d.is_available = true
                  AND d.name_normalized IS NOT NULL
                  AND word_similarity(:q, d.name_normalized) > 0.3
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


async def find_unavailable_match(
    session: "AsyncSession",
    restaurant_id: int,
    query: str,
) -> Dish | None:
    """Return a dish that matches ``query`` but is currently unavailable.

    Mirrors ``find_dish_matches`` but searches dishes with ``is_available =
    false``. Used to distinguish "you asked for something we have but it's out
    of stock" from "we don't have that at all", so the bot can offer an
    alternative instead of a flat "not found".
    """
    query = query.strip()
    menu_id = await _active_menu_id(session, restaurant_id)
    if menu_id is None:
        return None

    if re.fullmatch(r"\d+", query):
        return await session.scalar(
            select(Dish).where(
                Dish.menu_id == menu_id,
                Dish.dish_number == int(query),
                Dish.is_available == False,  # noqa: E712
            )
        )

    normalized_query = normalize_name(query)
    row = (
        await session.execute(
            text("""
                SELECT d.id, word_similarity(:q, d.name_normalized) AS sim
                FROM dishes d
                WHERE d.menu_id = :mid
                  AND d.is_available = false
                  AND d.name_normalized IS NOT NULL
                  AND word_similarity(:q, d.name_normalized) > :thr
                ORDER BY sim DESC
                LIMIT 1
            """),
            {"q": normalized_query, "mid": menu_id, "thr": _SINGLE_THRESHOLD},
        )
    ).first()
    if row is None:
        return None
    return await session.get(Dish, row.id)


async def suggest_available_alternative(
    session: "AsyncSession",
    restaurant_id: int,
    *,
    category: str | None,
    exclude_id: int,
) -> Dish | None:
    """Pick one available dish to offer as an alternative.

    Prefers a dish in the same ``category``; falls back to any available dish.
    Excludes ``exclude_id`` (the out-of-stock dish itself).
    """
    menu_id = await _active_menu_id(session, restaurant_id)
    if menu_id is None:
        return None

    base = select(Dish).where(
        Dish.menu_id == menu_id,
        Dish.is_available == True,  # noqa: E712
        Dish.id != exclude_id,
    )
    if category:
        same_cat = await session.scalar(
            base.where(Dish.category == category).order_by(Dish.dish_number).limit(1)
        )
        if same_cat is not None:
            return same_cat
    return await session.scalar(base.order_by(Dish.dish_number).limit(1))
