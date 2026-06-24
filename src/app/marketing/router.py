"""Marketing REST API — templates, segments, campaigns, analytics."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.marketing.copywriter import draft_template
from app.marketing.models import Campaign, MarketingMedia, Segment, WaTemplate
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
    campaign_stats_bulk,
    create_campaign,
    create_segment,
    delete_template,
    refresh_template,
    run_campaign_send,
    run_todays_special_tick,
    submit_template,
)
from app.marketing.template_factory import get_template_provider

router = APIRouter(prefix="/api/v1/marketing", tags=["marketing"])
_logger = logging.getLogger(__name__)


def _template_response(tpl: WaTemplate) -> TemplateResponse:
    """Serialize a WaTemplate (incl. content, so the dashboard can preview it)."""
    return TemplateResponse(
        id=tpl.id,
        meta_template_name=tpl.meta_template_name,
        status=tpl.status,
        rejection_reason=tpl.rejection_reason,
        body=tpl.body,
        header=tpl.header,
        footer=tpl.footer,
        buttons=tpl.buttons,
    )

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
    return _template_response(tpl)


@router.get("/templates")
async def list_templates(
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> list[TemplateResponse]:
    rows = (
        await session.scalars(
            select(WaTemplate).where(
                WaTemplate.restaurant_id == restaurant.id,
                WaTemplate.status != "deleted",
            )
        )
    ).all()
    return [_template_response(r) for r in rows]


@router.delete("/templates/{template_id}", status_code=204)
async def delete_wa_template(
    template_id: int,
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> None:
    """Delete a template — removes it from Meta (best-effort) and hides it from the
    list. Soft-delete so existing campaigns keep their FK."""
    ok = await delete_template(
        session,
        restaurant_id=restaurant.id,
        template_id=template_id,
        provider=get_template_provider(),
    )
    await session.commit()
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "template not found")


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
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> ImageUploadResponse:
    """Store a header image and return a public URL (used as the template's
    IMAGE header — Meta uploads it on submit, and the dashboard previews it).

    The bytes are persisted in Postgres (``marketing_media``) rather than local
    disk so the image survives redeploys on ephemeral-disk hosts (Render free
    tier). The returned ``/media/<path>`` URL is served by the media route which
    reads the row back."""
    if (file.content_type or "") not in _IMAGE_MIMES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Header image must be JPG or PNG")
    content = await file.read()
    if len(content) > _MAX_IMAGE_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Image exceeds 5 MB")
    settings = get_settings()
    ext = "png" if (file.content_type == "image/png") else "jpg"
    rel = f"marketing/{restaurant.id}/{uuid.uuid4().hex}.{ext}"
    session.add(
        MarketingMedia(
            restaurant_id=restaurant.id,
            path=rel,
            content_type=file.content_type or "image/jpeg",
            data=content,
        )
    )
    await session.commit()
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
    return _template_response(tpl)


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
    return _template_response(tpl)


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
    # Merge in real sent/delivered/converted from the send ledger so the Reports
    # page (which reads stats.sent / stats.converted) isn't stuck at 0.
    live = await campaign_stats_bulk(session, restaurant_id=restaurant.id)
    return [
        CampaignResponse(
            id=r.id, type=r.type, status=r.status,
            stats={**(r.stats or {}), **live.get(r.id, {})},
        )
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


@router.post("/tick")
async def todays_special_tick(
    x_tick_secret: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Heartbeat for the Today's Special auto-timed send — called by an external
    cron job (Render free tier has no Celery beat), NOT a manager.

    Guarded by the ``X-Tick-Secret`` header matching ``APP_MARKETING_TICK_SECRET``.
    Runs across ALL tenants (cron hits one URL for the platform): each enabled
    restaurant's due customers are sent and their outbox flushed synchronously.
    """
    from app.outbox.service import deliver_pending

    secret = get_settings().marketing_tick_secret.get_secret_value()
    if not secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "tick not configured")
    if x_tick_secret != secret:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid tick secret")

    totals = await run_todays_special_tick(
        session, now_utc=datetime.now(timezone.utc)
    )
    await session.commit()
    for restaurant_id in totals.get("restaurants", []):
        await deliver_pending(session, restaurant_id)
    return {
        "queued": totals.get("queued", 0),
        "suppressed": totals.get("suppressed", 0),
        "restaurants": len(totals.get("restaurants", [])),
    }


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
