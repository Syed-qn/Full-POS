"""Marketing REST API — templates, segments, campaigns, analytics."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.marketing.models import Campaign, Segment, WaTemplate
from app.marketing.schemas import (
    CampaignCreate,
    CampaignResponse,
    SegmentCreate,
    SegmentResponse,
    TemplateCreate,
    TemplateResponse,
)
from app.marketing.service import (
    campaign_stats,
    create_campaign,
    create_segment,
)

router = APIRouter(prefix="/api/v1/marketing", tags=["marketing"])


# ── Segments ────────────────────────────────────────────────────────────────

@router.post("/segments", status_code=201)
async def post_segment(
    body: SegmentCreate,
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> SegmentResponse:
    seg = await create_segment(
        session,
        restaurant_id=restaurant.id,
        name=body.name,
        dsl=body.dsl,
        plain_english=body.plain_english,
    )
    await session.commit()
    return SegmentResponse(id=seg.id, name=seg.name, last_preview_count=seg.last_preview_count)


@router.get("/segments")
async def list_segments(
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> list[SegmentResponse]:
    rows = (
        await session.scalars(
            select(Segment).where(Segment.restaurant_id == restaurant.id)
        )
    ).all()
    return [SegmentResponse(id=r.id, name=r.name, last_preview_count=r.last_preview_count) for r in rows]


# ── Templates ────────────────────────────────────────────────────────────────

@router.post("/templates", status_code=201)
async def create_wa_template(
    body: TemplateCreate,
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> TemplateResponse:
    tpl = WaTemplate(
        restaurant_id=restaurant.id,
        meta_template_name=body.meta_template_name,
        language=body.language,
        category=body.category,
        body=body.body,
        header=body.header,
        footer=body.footer,
        buttons=body.buttons or [],
        status="draft",
    )
    session.add(tpl)
    await session.flush()
    await session.commit()
    return TemplateResponse(
        id=tpl.id,
        meta_template_name=tpl.meta_template_name,
        status=tpl.status,
        rejection_reason=None,
    )


@router.get("/templates")
async def list_templates(
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> list[TemplateResponse]:
    rows = (
        await session.scalars(
            select(WaTemplate).where(WaTemplate.restaurant_id == restaurant.id)
        )
    ).all()
    return [
        TemplateResponse(
            id=r.id,
            meta_template_name=r.meta_template_name,
            status=r.status,
            rejection_reason=r.rejection_reason,
        )
        for r in rows
    ]


# ── Campaigns ────────────────────────────────────────────────────────────────

@router.post("/campaigns", status_code=201)
async def post_campaign(
    body: CampaignCreate,
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> CampaignResponse:
    camp = await create_campaign(
        session,
        restaurant_id=restaurant.id,
        type=body.type,
        template_id=body.template_id,
        segment_id=body.segment_id,
        image_url=body.image_url,
        coupon_value=body.coupon_value,
        scheduled_at=body.scheduled_at,
    )
    await session.commit()
    return CampaignResponse(id=camp.id, type=camp.type, status=camp.status, stats=camp.stats or {})


@router.get("/campaigns")
async def list_campaigns(
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> list[CampaignResponse]:
    rows = (
        await session.scalars(
            select(Campaign).where(Campaign.restaurant_id == restaurant.id)
        )
    ).all()
    return [
        CampaignResponse(id=r.id, type=r.type, status=r.status, stats=r.stats or {})
        for r in rows
    ]


@router.get("/campaigns/{campaign_id}/stats")
async def get_campaign_stats(
    campaign_id: int,
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> dict:
    camp = await session.get(Campaign, campaign_id)
    if camp is None or camp.restaurant_id != restaurant.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "campaign not found")
    return await campaign_stats(session, restaurant_id=restaurant.id, campaign_id=campaign_id)
