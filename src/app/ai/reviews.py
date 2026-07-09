"""AI review reply suggestions + negative review escalation."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import ReviewReplySuggestion
from app.ai.text_gen import generate_narrative
from app.audit.service import record_audit

_NEG_WORDS = re.compile(
    r"\b(bad|terrible|awful|cold|late|missing|wrong|disgusting|refund|never)\b",
    re.I,
)


def _sentiment(score: int | None, comment: str | None) -> str:
    if score is not None:
        if score <= 6:
            return "negative"
        if score >= 9:
            return "positive"
        return "neutral"
    if comment and _NEG_WORDS.search(comment):
        return "negative"
    return "neutral"


def _theme(comment: str | None) -> str | None:
    if not comment:
        return None
    # light extract: first 40 chars
    return comment.strip()[:40]


async def suggest_review_reply(
    session: AsyncSession,
    *,
    restaurant_id: int,
    comment: str | None,
    score: int | None = None,
    order_id: int | None = None,
    customer_id: int | None = None,
    nps_response_id: int | None = None,
    escalate: bool | None = None,
) -> ReviewReplySuggestion:
    sentiment = _sentiment(score, comment)
    theme = _theme(comment)
    reply = await generate_narrative(
        "review_reply",
        {"score": score, "theme": theme, "comment": (comment or "")[:200]},
    )
    should_escalate = escalate if escalate is not None else sentiment == "negative"
    ticket_id = None
    if should_escalate and customer_id is not None:
        try:
            from app.tickets.service import create_ticket

            t = await create_ticket(
                session,
                restaurant_id=restaurant_id,
                customer_id=customer_id,
                order_id=order_id,
                source_message=comment or f"Negative review (score={score})",
                evidence=[
                    {
                        "kind": "review",
                        "score": score,
                        "comment": comment,
                        "nps_response_id": nps_response_id,
                    }
                ],
                category="quality",
            )
            ticket_id = getattr(t, "id", None)
        except Exception:  # noqa: BLE001
            ticket_id = None
    elif should_escalate and customer_id is None:
        # Mark escalated for ops queue even without ticket when no customer linked.
        ticket_id = None

    row = ReviewReplySuggestion(
        restaurant_id=restaurant_id,
        nps_response_id=nps_response_id,
        order_id=order_id,
        customer_id=customer_id,
        score=score,
        original_comment=comment,
        suggested_reply=reply,
        sentiment=sentiment,
        escalated=bool(should_escalate),
        ticket_id=ticket_id,
    )
    session.add(row)
    await session.flush()
    await record_audit(
        session,
        restaurant_id=restaurant_id,
        actor="system",
        entity="review_reply",
        entity_id=str(row.id),
        action="suggest",
        after={"sentiment": sentiment, "escalated": row.escalated},
    )
    return row


async def list_review_replies(
    session: AsyncSession, *, restaurant_id: int, limit: int = 30
) -> list[ReviewReplySuggestion]:
    return list(
        (
            await session.scalars(
                select(ReviewReplySuggestion)
                .where(ReviewReplySuggestion.restaurant_id == restaurant_id)
                .order_by(ReviewReplySuggestion.id.desc())
                .limit(min(max(limit, 1), 100))
            )
        ).all()
    )


async def escalate_negative_reviews(
    session: AsyncSession, *, restaurant_id: int, lookback_days: int = 30
) -> dict:
    """Scan recent NPS detractors without reply suggestions and escalate."""
    from datetime import date, datetime, time, timedelta

    from app.loyalty.models import NpsResponse

    start = datetime.combine(date.today() - timedelta(days=lookback_days), time.min)
    rows = list(
        (
            await session.scalars(
                select(NpsResponse).where(
                    NpsResponse.restaurant_id == restaurant_id,
                    NpsResponse.score <= 6,
                    NpsResponse.created_at >= start,
                )
            )
        ).all()
    )
    created = 0
    for nps in rows:
        exists = await session.scalar(
            select(ReviewReplySuggestion.id).where(
                ReviewReplySuggestion.restaurant_id == restaurant_id,
                ReviewReplySuggestion.nps_response_id == nps.id,
            )
        )
        if exists:
            continue
        await suggest_review_reply(
            session,
            restaurant_id=restaurant_id,
            comment=nps.comment,
            score=nps.score,
            order_id=nps.order_id,
            customer_id=nps.customer_id,
            nps_response_id=nps.id,
            escalate=True,
        )
        created += 1
    return {"scanned": len(rows), "created": created}
