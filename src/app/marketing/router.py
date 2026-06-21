"""Marketing REST API — templates, segments, campaigns, analytics."""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.marketing.copywriter import draft_template
from app.marketing.models import Campaign, Segment, WaTemplate
from app.marketing.schemas import (
    BroadcastRequest,
    BroadcastResponse,
    CampaignCreate,
    CampaignResponse,
    ImageUploadResponse,
    SegmentCreate,
    SegmentResponse,
    TemplateCreate,
    TemplateDraftRequest,
    TemplateDraftResponse,
    TemplateResponse,
)
from app.marketing.service import (
    campaign_stats,
    create_campaign,
    create_segment,
    refresh_template,
    run_campaign_send,
    submit_template,
)
from app.marketing.template_factory import get_template_provider

router = APIRouter(prefix="/api/v1/marketing", tags=["marketing"])
_logger = logging.getLogger(__name__)

_IMAGE_MIMES = {"image/jpeg", "image/png"}
_MAX_IMAGE_BYTES = 5 * 1024 * 1024  # Meta header-image limit


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
    # The (restaurant_id, meta_template_name, language) unique constraint makes
    # re-drafting the same offer collide (the AI suggests the same slug each time)
    # and the bare insert 500s. Auto-suffix _2, _3, … against ALL existing names
    # for this tenant+language — including soft-deleted rows, which still occupy
    # the constraint — so every draft gets a unique name. The final Meta name is
    # datestamped later in submit_template.
    existing = set(
        (
            await session.scalars(
                select(WaTemplate.meta_template_name).where(
                    WaTemplate.restaurant_id == restaurant.id,
                    WaTemplate.language == body.language,
                )
            )
        ).all()
    )
    name = body.meta_template_name
    suffix = 2
    while name in existing:
        name = f"{body.meta_template_name}_{suffix}"
        suffix += 1

    tpl = WaTemplate(
        restaurant_id=restaurant.id,
        meta_template_name=name,
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


@router.post("/templates/draft", response_model=TemplateDraftResponse)
async def draft_wa_template(
    body: TemplateDraftRequest,
    restaurant: Restaurant = Depends(current_restaurant),
) -> TemplateDraftResponse:
    """AI-draft a compliant template body from a plain-English offer (DSC-style)."""
    out = await draft_template(restaurant_name=restaurant.name, describe=body.describe)
    return TemplateDraftResponse(**out)


@router.post("/templates/image", response_model=ImageUploadResponse)
async def upload_template_image(
    file: UploadFile,
    restaurant: Restaurant = Depends(current_restaurant),
) -> ImageUploadResponse:
    """Store a header image and return a public URL (used as the template's
    IMAGE header — Meta uploads it on submit, and the dashboard previews it)."""
    if (file.content_type or "") not in _IMAGE_MIMES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Header image must be JPG or PNG")
    content = await file.read()
    if len(content) > _MAX_IMAGE_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Image exceeds 5 MB")
    settings = get_settings()
    ext = "png" if (file.content_type == "image/png") else "jpg"
    rel = f"marketing/{restaurant.id}/{uuid.uuid4().hex}.{ext}"
    dest = os.path.join(settings.upload_dir, rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as fh:
        fh.write(content)
    url = f"{settings.public_base_url.rstrip('/')}/media/{rel}"
    return ImageUploadResponse(url=url)


@router.post("/templates/{template_id}/submit", response_model=TemplateResponse)
async def submit_wa_template(
    template_id: int,
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> TemplateResponse:
    """Lint + submit a draft template to Meta for approval."""
    settings = get_settings()
    # Friendly pre-check: an IMAGE header is uploaded to Meta via the resumable
    # /uploads API, which needs a Facebook App ID. Without it the live Meta call
    # would 500 — surface a clear, actionable message instead.
    pre = await session.get(WaTemplate, template_id)
    if (
        pre is not None
        and pre.restaurant_id == restaurant.id
        and isinstance(pre.header, dict)
        and str(pre.header.get("type", "")).upper() == "IMAGE"
        and settings.marketing_template_provider == "meta"
        and not settings.marketing_send_dry_run
        and not settings.wa_app_id
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Image-header templates need APP_WA_APP_ID (your Facebook App ID) set. "
            "Add it, or remove the image and submit a text-only template.",
        )
    try:
        tpl = await submit_template(
            session,
            restaurant_id=restaurant.id,
            wa_template_id=template_id,
            provider=get_template_provider(),
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    except Exception as exc:  # noqa: BLE001 - turn provider/network faults into a clean 502
        _logger.exception("template submit to Meta failed (template_id=%s)", template_id)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"WhatsApp template submission failed: {exc}"
        )
    await session.commit()
    return TemplateResponse(
        id=tpl.id, meta_template_name=tpl.meta_template_name,
        status=tpl.status, rejection_reason=tpl.rejection_reason,
    )


@router.post("/templates/{template_id}/refresh", response_model=TemplateResponse)
async def refresh_wa_template(
    template_id: int,
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> TemplateResponse:
    """Re-poll a pending template's Meta approval status (manual, web-only safe)."""
    try:
        tpl = await refresh_template(
            session,
            restaurant_id=restaurant.id,
            wa_template_id=template_id,
            provider=get_template_provider(),
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    await session.commit()
    return TemplateResponse(
        id=tpl.id, meta_template_name=tpl.meta_template_name,
        status=tpl.status, rejection_reason=tpl.rejection_reason,
    )


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


@router.post("/broadcast", response_model=BroadcastResponse, status_code=201)
async def broadcast_now(
    body: BroadcastRequest,
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> BroadcastResponse:
    """Send an APPROVED template to all opted-in customers (or a segment) NOW.

    Creates a campaign, runs the compliant send (opt-out → UAE window → 24h cap),
    then flushes the outbox synchronously (no Celery needed). Re-runnable: the
    per-(campaign,customer) ledger makes repeats idempotent."""
    from app.outbox.service import deliver_pending

    try:
        camp = await create_campaign(
            session,
            restaurant_id=restaurant.id,
            type=body.type,
            template_id=body.template_id,
            segment_id=body.segment_id,
            coupon_value=body.coupon_value,
        )
        camp.status = "sending"
        await session.flush()
        summary = await run_campaign_send(
            session,
            campaign=camp,
            provider=get_template_provider(),
            now_utc=datetime.now(timezone.utc),
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    await session.commit()
    await deliver_pending(session, restaurant.id)
    return BroadcastResponse(
        campaign_id=camp.id,
        queued=summary.get("queued", 0),
        suppressed_cap=summary.get("suppressed_cap", 0),
        suppressed_optout=summary.get("suppressed_optout", 0),
        suppressed_window=summary.get("suppressed_window", 0),
    )


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
