"""AI delivery ETA explanation."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.text_gen import generate_narrative


async def explain_delivery_eta(
    session: AsyncSession, *, restaurant_id: int, order_id: int
) -> dict:
    from app.ordering.models import Order

    order = await session.get(Order, order_id)
    if order is None or order.restaurant_id != restaurant_id:
        raise ValueError("order not found")

    now = datetime.now(timezone.utc)
    eta_min = 40
    if order.promised_eta:
        pe = order.promised_eta
        if pe.tzinfo is None:
            pe = pe.replace(tzinfo=timezone.utc)
        eta_min = max(1, int((pe - now).total_seconds() / 60))
    prep_min = int(order.cook_estimate_minutes or 15)
    drive_min = max(5, eta_min - prep_min) if eta_min > prep_min else 15
    batched = False
    extra = ""
    try:

        # if assignment has algorithm score batch info
        if order.rider_id:
            extra = f"Rider assigned (#{order.rider_id})."
            batched = True
    except Exception:  # noqa: BLE001
        pass

    if order.distance_km:
        extra = (extra + f" Distance ~{order.distance_km:.1f} km.").strip()

    facts = {
        "eta_min": eta_min,
        "prep_min": prep_min,
        "drive_min": drive_min,
        "batched": batched,
        "extra": extra,
        "status": order.status,
        "order_number": order.order_number,
    }
    explanation = await generate_narrative("eta_explain", facts)
    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "explanation": explanation,
        "facts": facts,
    }
