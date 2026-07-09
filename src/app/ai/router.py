"""HTTP surface for Category 14 AI features."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import calls as call_svc
from app.ai import eta as eta_svc
from app.ai import insights as insight_svc
from app.ai import marketing_ai as mkt_svc
from app.ai import recommendations as rec_svc
from app.ai import reservations as res_svc
from app.ai import reviews as review_svc
from app.ai import translation as tr_svc
from app.db import get_session
from app.identity.deps import current_restaurant
from app.staff.deps import require_role

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])


def _insight_out(row) -> dict:
    return {
        "id": row.id,
        "kind": row.kind,
        "title": row.title,
        "summary": row.summary,
        "payload": row.payload,
        "period_start": row.period_start.isoformat() if row.period_start else None,
        "period_end": row.period_end.isoformat() if row.period_end else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


# ── Catalog of wired AI features (dashboard index) ──────────────────────────


@router.get("/features")
async def list_ai_features(restaurant=Depends(current_restaurant)):
    return {
        "features": [
            {"key": "whatsapp_order", "status": "implemented", "surface": "conversation"},
            {"key": "menu_recommendation", "status": "implemented", "surface": "suggestion_agent"},
            {"key": "upsell", "status": "implemented", "path": "/api/v1/ai/upsell"},
            {"key": "combo_suggestion", "status": "implemented", "path": "/api/v1/ai/combos"},
            {"key": "reorder_prompt", "status": "implemented", "path": "/api/v1/ai/reorder-prompt"},
            {"key": "abandoned_recovery", "status": "implemented", "path": "/api/v1/ai/abandoned-copy"},
            {"key": "segmentation", "status": "implemented", "path": "/api/v1/ai/segments"},
            {"key": "daily_sales", "status": "implemented", "path": "/api/v1/ai/insights/daily-sales"},
            {"key": "low_stock", "status": "implemented", "path": "/api/v1/ai/insights/low-stock"},
            {"key": "slow_moving", "status": "implemented", "path": "/api/v1/ai/insights/slow-moving"},
            {"key": "food_cost_anomaly", "status": "implemented", "path": "/api/v1/ai/insights/food-cost"},
            {"key": "staff_summary", "status": "implemented", "path": "/api/v1/ai/insights/staff"},
            {"key": "complaint_detection", "status": "implemented", "surface": "complaint_agent"},
            {"key": "review_reply", "status": "implemented", "path": "/api/v1/ai/reviews/reply"},
            {"key": "negative_escalation", "status": "implemented", "path": "/api/v1/ai/reviews/escalate"},
            {"key": "eta_explain", "status": "implemented", "path": "/api/v1/ai/eta/{order_id}"},
            {"key": "sales_drop", "status": "implemented", "path": "/api/v1/ai/insights/sales-drop"},
            {"key": "menu_bundle", "status": "implemented", "path": "/api/v1/ai/bundles"},
            {"key": "promotion", "status": "implemented", "surface": "marketing/copywriter"},
            {"key": "festival_campaign", "status": "implemented", "path": "/api/v1/ai/festival"},
            {"key": "menu_translation", "status": "implemented", "path": "/api/v1/ai/translate"},
            {"key": "voice_ordering", "status": "implemented", "surface": "speech + webhook"},
            {"key": "call_answering", "status": "implemented", "path": "/api/v1/ai/calls"},
            {"key": "reservations", "status": "implemented", "path": "/api/v1/ai/reservations"},
            {"key": "demand_forecast", "status": "implemented", "surface": "/api/v1/predictions"},
        ]
    }


# ── Insights ────────────────────────────────────────────────────────────────


@router.post("/insights/daily-sales")
async def post_daily_sales(
    day: date | None = None,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    row = await insight_svc.daily_sales_summary(
        session, restaurant_id=restaurant.id, day=day
    )
    await session.commit()
    return _insight_out(row)


@router.post("/insights/sales-drop")
async def post_sales_drop(
    days: int = Query(default=7, ge=1, le=90),
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    row = await insight_svc.why_sales_dropped(
        session, restaurant_id=restaurant.id, days=days
    )
    await session.commit()
    return _insight_out(row)


@router.post("/insights/staff")
async def post_staff_summary(
    days: int = Query(default=7, ge=1, le=90),
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    row = await insight_svc.staff_performance_summary(
        session, restaurant_id=restaurant.id, days=days
    )
    await session.commit()
    return _insight_out(row)


@router.post("/insights/slow-moving")
async def post_slow_moving(
    days: int = Query(default=14, ge=3, le=90),
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    row = await insight_svc.slow_moving_items(
        session, restaurant_id=restaurant.id, days=days
    )
    await session.commit()
    return _insight_out(row)


@router.post("/insights/food-cost")
async def post_food_cost(
    threshold_pct: float = Query(default=40.0, ge=10, le=90),
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    row = await insight_svc.food_cost_anomalies(
        session, restaurant_id=restaurant.id, threshold_pct=threshold_pct
    )
    await session.commit()
    return _insight_out(row)


@router.post("/insights/low-stock")
async def post_low_stock(
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    row = await insight_svc.low_stock_prediction(session, restaurant_id=restaurant.id)
    await session.commit()
    return _insight_out(row)


@router.get("/insights")
async def get_insights(
    kind: str | None = None,
    limit: int = Query(default=30, ge=1, le=100),
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = await insight_svc.list_insights(
        session, restaurant_id=restaurant.id, kind=kind, limit=limit
    )
    return [_insight_out(r) for r in rows]


# ── Recommendations ─────────────────────────────────────────────────────────


class UpsellIn(BaseModel):
    dish_ids: list[int] = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=20)


@router.post("/upsell")
async def post_upsell(
    body: UpsellIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await rec_svc.ai_upsell(
        session,
        restaurant_id=restaurant.id,
        dish_ids=body.dish_ids,
        limit=body.limit,
    )


@router.get("/combos")
async def get_combos(
    limit: int = Query(default=5, ge=1, le=20),
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await rec_svc.ai_combo_suggestions(
        session, restaurant_id=restaurant.id, limit=limit
    )


@router.post("/bundles")
async def post_bundles(
    limit: int = Query(default=5, ge=1, le=20),
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    row = await rec_svc.best_menu_bundles(
        session, restaurant_id=restaurant.id, limit=limit
    )
    await session.commit()
    return _insight_out(row)


# ── Marketing AI ────────────────────────────────────────────────────────────


@router.post("/reorder-prompt")
async def post_reorder(
    customer_id: int | None = None,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await mkt_svc.reorder_prompt_copy(
        session, restaurant_id=restaurant.id, customer_id=customer_id
    )


@router.post("/abandoned-copy")
async def post_abandoned(cart_summary: str | None = None):
    return await mkt_svc.abandoned_recovery_copy(cart_summary=cart_summary)


@router.post("/segments")
async def post_segments(
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    row = await mkt_svc.segment_insights(session, restaurant_id=restaurant.id)
    await session.commit()
    return _insight_out(row)


class FestivalIn(BaseModel):
    festival: str = Field(min_length=1, max_length=64)
    offer: str | None = None


@router.post("/festival")
async def post_festival(
    body: FestivalIn,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    row = await mkt_svc.festival_campaign(
        session,
        restaurant_id=restaurant.id,
        festival=body.festival,
        offer=body.offer,
    )
    await session.commit()
    return _insight_out(row)


# ── Reviews ─────────────────────────────────────────────────────────────────


class ReviewReplyIn(BaseModel):
    comment: str | None = None
    score: int | None = Field(default=None, ge=0, le=10)
    order_id: int | None = None
    customer_id: int | None = None
    nps_response_id: int | None = None
    escalate: bool | None = None


@router.post("/reviews/reply", status_code=status.HTTP_201_CREATED)
async def post_review_reply(
    body: ReviewReplyIn,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    row = await review_svc.suggest_review_reply(
        session,
        restaurant_id=restaurant.id,
        comment=body.comment,
        score=body.score,
        order_id=body.order_id,
        customer_id=body.customer_id,
        nps_response_id=body.nps_response_id,
        escalate=body.escalate,
    )
    await session.commit()
    return {
        "id": row.id,
        "suggested_reply": row.suggested_reply,
        "sentiment": row.sentiment,
        "escalated": row.escalated,
        "ticket_id": row.ticket_id,
    }


@router.post("/reviews/escalate")
async def post_escalate(
    lookback_days: int = Query(default=30, ge=1, le=180),
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    result = await review_svc.escalate_negative_reviews(
        session, restaurant_id=restaurant.id, lookback_days=lookback_days
    )
    await session.commit()
    return result


@router.get("/reviews")
async def get_reviews(
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = await review_svc.list_review_replies(session, restaurant_id=restaurant.id)
    return [
        {
            "id": r.id,
            "score": r.score,
            "sentiment": r.sentiment,
            "suggested_reply": r.suggested_reply,
            "escalated": r.escalated,
            "original_comment": r.original_comment,
        }
        for r in rows
    ]


# ── ETA ─────────────────────────────────────────────────────────────────────


@router.get("/eta/{order_id}")
async def get_eta(
    order_id: int,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await eta_svc.explain_delivery_eta(
            session, restaurant_id=restaurant.id, order_id=order_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ── Translation ─────────────────────────────────────────────────────────────


class TranslateIn(BaseModel):
    dish_id: int | None = None
    target_lang: str = "ar"
    all_menu: bool = False
    limit: int = Field(default=50, ge=1, le=200)


@router.post("/translate")
async def post_translate(
    body: TranslateIn,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    if body.all_menu:
        rows = await tr_svc.translate_menu(
            session,
            restaurant_id=restaurant.id,
            target_lang=body.target_lang,
            limit=body.limit,
        )
        await session.commit()
        return {
            "count": len(rows),
            "items": [
                {
                    "id": r.id,
                    "dish_id": r.dish_id,
                    "name": r.name,
                    "description": r.description,
                    "target_lang": r.target_lang,
                }
                for r in rows
            ],
        }
    if body.dish_id is None:
        raise HTTPException(status_code=400, detail="dish_id or all_menu required")
    try:
        row = await tr_svc.translate_dish(
            session,
            restaurant_id=restaurant.id,
            dish_id=body.dish_id,
            target_lang=body.target_lang,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return {
        "id": row.id,
        "dish_id": row.dish_id,
        "name": row.name,
        "description": row.description,
        "target_lang": row.target_lang,
    }


# ── Reservations ────────────────────────────────────────────────────────────


class ReservationIn(BaseModel):
    party_size: int = Field(ge=1, le=50)
    requested_for: datetime
    guest_name: str | None = None
    phone: str | None = None
    notes: str | None = None
    customer_id: int | None = None


@router.post("/reservations", status_code=status.HTTP_201_CREATED)
async def post_reservation(
    body: ReservationIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    row = await res_svc.create_reservation(
        session,
        restaurant_id=restaurant.id,
        party_size=body.party_size,
        requested_for=body.requested_for,
        guest_name=body.guest_name,
        phone=body.phone,
        notes=body.notes,
        customer_id=body.customer_id,
    )
    await session.commit()
    return {
        "id": row.id,
        "status": row.status,
        "party_size": row.party_size,
        "table_id": row.table_id,
        "ai_summary": row.ai_summary,
        "requested_for": row.requested_for.isoformat(),
    }


@router.get("/reservations")
async def get_reservations(
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = await res_svc.list_reservations(session, restaurant_id=restaurant.id)
    return [
        {
            "id": r.id,
            "status": r.status,
            "party_size": r.party_size,
            "guest_name": r.guest_name,
            "phone": r.phone,
            "table_id": r.table_id,
            "ai_summary": r.ai_summary,
            "requested_for": r.requested_for.isoformat() if r.requested_for else None,
        }
        for r in rows
    ]


class ReservationStatusIn(BaseModel):
    status: str


@router.patch("/reservations/{reservation_id}")
async def patch_reservation(
    reservation_id: int,
    body: ReservationStatusIn,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    try:
        row = await res_svc.update_reservation_status(
            session,
            restaurant_id=restaurant.id,
            reservation_id=reservation_id,
            status=body.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    return {"id": row.id, "status": row.status}


# ── Call answering ──────────────────────────────────────────────────────────


class CallStartIn(BaseModel):
    caller_phone: str | None = None


class CallTurnIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@router.post("/calls", status_code=status.HTTP_201_CREATED)
async def post_call_start(
    body: CallStartIn | None = None,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    body = body or CallStartIn()
    row = await call_svc.start_call(
        session, restaurant_id=restaurant.id, caller_phone=body.caller_phone
    )
    await session.commit()
    return {
        "id": row.id,
        "status": row.status,
        "transcript": row.transcript,
    }


@router.post("/calls/{session_id}/turn")
async def post_call_turn(
    session_id: int,
    body: CallTurnIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        row = await call_svc.turn_call(
            session,
            restaurant_id=restaurant.id,
            session_id=session_id,
            user_text=body.text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    return {
        "id": row.id,
        "status": row.status,
        "outcome": row.outcome,
        "transcript": row.transcript,
        "ai_summary": row.ai_summary,
    }


@router.get("/calls")
async def get_calls(
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = await call_svc.list_calls(session, restaurant_id=restaurant.id)
    return [
        {
            "id": r.id,
            "status": r.status,
            "caller_phone": r.caller_phone,
            "outcome": r.outcome,
            "ai_summary": r.ai_summary,
        }
        for r in rows
    ]
