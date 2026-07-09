"""AI call answering (mock IVR / phone order taking)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import CallAnswerSession
from app.ai.text_gen import generate_narrative
from app.audit.service import record_audit


async def start_call(
    session: AsyncSession,
    *,
    restaurant_id: int,
    caller_phone: str | None = None,
) -> CallAnswerSession:
    greeting = await generate_narrative(
        "call_turn",
        {
            "reply": (
                "Thanks for calling. I can take your order, check status, "
                "or help with a reservation. What would you like?"
            )
        },
    )
    row = CallAnswerSession(
        restaurant_id=restaurant_id,
        caller_phone=caller_phone,
        status="active",
        transcript=[{"role": "assistant", "text": greeting}],
        ai_summary=None,
        outcome=None,
    )
    session.add(row)
    await session.flush()
    await record_audit(
        session,
        restaurant_id=restaurant_id,
        actor="system",
        entity="call_session",
        entity_id=str(row.id),
        action="start",
        after={"phone": caller_phone},
    )
    return row


async def turn_call(
    session: AsyncSession,
    *,
    restaurant_id: int,
    session_id: int,
    user_text: str,
) -> CallAnswerSession:
    row = await session.get(CallAnswerSession, session_id)
    if row is None or row.restaurant_id != restaurant_id:
        raise ValueError("call session not found")
    if row.status != "active":
        raise ValueError("call session is not active")

    text = (user_text or "").strip()
    transcript = list(row.transcript or [])
    transcript.append({"role": "user", "text": text})

    lower = text.lower()
    outcome = None
    if any(w in lower for w in ("order", "biryani", "menu", "want", "add")):
        reply = (
            "Got it — I can place that as a WhatsApp-style order. "
            "Please share dish numbers or names, and your delivery address."
        )
        outcome = "order_intent"
    elif any(w in lower for w in ("status", "where", "track", "late")):
        reply = (
            "I can check your latest order status. Please share your order number "
            "or the phone used to order."
        )
        outcome = "status_intent"
    elif any(w in lower for w in ("reserv", "table", "book", "party")):
        reply = (
            "Happy to reserve a table. How many guests and what date/time?"
        )
        outcome = "reservation_intent"
    elif any(w in lower for w in ("bye", "thanks", "thank you", "that's all")):
        reply = "Thank you for calling. Goodbye!"
        outcome = "completed"
        row.status = "completed"
    else:
        reply = await generate_narrative(
            "call_turn",
            {
                "reply": (
                    "I can help with orders, delivery status, or reservations. "
                    "Could you say that another way?"
                )
            },
        )

    transcript.append({"role": "assistant", "text": reply})
    row.transcript = transcript
    if outcome:
        row.outcome = outcome
    if row.status == "completed":
        row.ai_summary = (
            f"Call with {row.caller_phone or 'unknown'}: outcome={row.outcome}. "
            f"Turns={len(transcript)}."
        )
    await session.flush()
    return row


async def list_calls(
    session: AsyncSession, *, restaurant_id: int, limit: int = 30
) -> list[CallAnswerSession]:
    return list(
        (
            await session.scalars(
                select(CallAnswerSession)
                .where(CallAnswerSession.restaurant_id == restaurant_id)
                .order_by(CallAnswerSession.id.desc())
                .limit(min(max(limit, 1), 100))
            )
        ).all()
    )
