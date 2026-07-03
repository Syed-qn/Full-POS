"""Marketing REST API — templates, segments, campaigns, analytics."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Union

from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.marketing.copywriter import draft_template
from app.marketing.models import Campaign, MarketingMedia, Segment, WaTemplate
from app.marketing.rfm import RFM_SEGMENTS, segment_counts, segment_customer_ids
from app.marketing.schemas import (
    AudienceSegmentOut,
    AutomationPatch,
    AutomationResponse,
    BroadcastRequest,
    BroadcastResponse,
    BroadcastScheduleResponse,
    CampaignCreate,
    CampaignResponse,
    ImageGenerateRequest,
    ImageUploadResponse,
    SchedulePatch,
    SegmentCompileRequest,
    SegmentCompileResponse,
    SegmentCreate,
    SegmentPreviewRequest,
    SegmentPreviewResponse,
    SegmentResponse,
    TemplateCreate,
    TemplateDraftRequest,
    TemplateDraftResponse,
    TemplateFixRequest,
    TemplateResponse,
)
from app.marketing.service import (
    audience_label_for_campaign,
    campaign_stats,
    campaign_stats_bulk,
    compile_segment_from_english,
    cancel_scheduled_campaign,
    create_campaign,
    create_segment,
    delete_segment,
    delete_template,
    fix_template,
    generate_promo_image,
    list_automations,
    patch_automation,
    preview_segment,
    refresh_template,
    reschedule_campaign,
    run_campaign_send,
    run_todays_special_tick,
    schedule_broadcast,
    submit_template,
)
from app.marketing.template_factory import get_template_provider

router = APIRouter(prefix="/api/v1/marketing", tags=["marketing"])
_logger = logging.getLogger(__name__)


def _campaign_response(
    camp: Campaign,
    *,
    template_name: str | None,
    segment_name: str | None,
    live_stats: dict | None = None,
) -> CampaignResponse:
    return CampaignResponse(
        id=camp.id,
        type=camp.type,
        status=camp.status,
        stats={**(camp.stats or {}), **(live_stats or {})},
        created_at=camp.created_at,
        scheduled_at=camp.scheduled_at,
        template_name=template_name,
        audience_label=audience_label_for_campaign(
            segment_name=segment_name,
            stats=camp.stats,
        ),
        segment_id=camp.segment_id,
        template_id=camp.template_id,
    )


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

def _segment_response(seg: Segment) -> SegmentResponse:
    return SegmentResponse(
        id=seg.id,
        name=seg.name,
        last_preview_count=seg.last_preview_count,
        plain_english=seg.plain_english,
        updated_at=seg.updated_at,
    )


@router.post("/segments/compile", response_model=SegmentCompileResponse)
async def compile_segment(
    body: SegmentCompileRequest,
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> SegmentCompileResponse:
    try:
        result = await compile_segment_from_english(
            session,
            restaurant_id=restaurant.id,
            plain_english=body.plain_english,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    except RuntimeError as exc:
        _logger.exception("segment compile failed for restaurant %s", restaurant.id)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))
    return SegmentCompileResponse(**result)


@router.post("/segments/preview", response_model=SegmentPreviewResponse)
async def preview_segment_route(
    body: SegmentPreviewRequest,
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> SegmentPreviewResponse:
    try:
        count = await preview_segment(
            session, restaurant_id=restaurant.id, dsl=body.dsl
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    return SegmentPreviewResponse(preview_count=count)


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
    return _segment_response(seg)


@router.get("/segments")
async def list_segments(
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> list[SegmentResponse]:
    rows = (
        await session.scalars(
            select(Segment)
            .where(Segment.restaurant_id == restaurant.id)
            .order_by(Segment.updated_at.desc())
        )
    ).all()
    return [_segment_response(r) for r in rows]


@router.delete("/segments/{segment_id}", status_code=204)
async def remove_segment(
    segment_id: int,
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> None:
    try:
        await delete_segment(
            session, restaurant_id=restaurant.id, segment_id=segment_id
        )
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg:
            raise HTTPException(status.HTTP_404_NOT_FOUND, msg)
        raise HTTPException(status.HTTP_409_CONFLICT, msg)
    await session.commit()


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
        ephemeral=body.ephemeral,
    )
    session.add(tpl)
    await session.flush()
    await session.commit()
    return _template_response(tpl)


@router.post("/templates/{template_id}/fix", response_model=TemplateResponse)
async def fix_wa_template(
    template_id: int,
    body: TemplateFixRequest | None = None,
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> TemplateResponse:
    try:
        tpl = await fix_template(
            session,
            restaurant_id=restaurant.id,
            template_id=template_id,
            restaurant_name=restaurant.name,
            hint=body.hint if body else None,
        )
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg:
            raise HTTPException(status.HTTP_404_NOT_FOUND, msg)
        if "compliance" in msg:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, msg)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, msg)
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


@router.post("/templates/image/generate", response_model=ImageUploadResponse)
async def generate_template_image(
    body: ImageGenerateRequest,
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> ImageUploadResponse:
    """AI-generate a promo header image and return a public URL (like upload)."""
    if not (body.prompt.strip() or (body.describe or "").strip()):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Provide a prompt or describe your offer",
        )
    try:
        url = await generate_promo_image(
            session,
            restaurant_id=restaurant.id,
            restaurant_name=restaurant.name,
            prompt=body.prompt.strip(),
            describe=body.describe,
            now_utc=datetime.now(timezone.utc),
        )
    except ValueError as exc:
        msg = str(exc)
        if "limit reached" in msg.lower():
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, msg)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, msg)
    await session.commit()
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
    tpl_name = None
    seg_name = None
    if camp.template_id is not None:
        tpl = await session.get(WaTemplate, camp.template_id)
        tpl_name = tpl.meta_template_name if tpl else None
    if camp.segment_id is not None:
        seg = await session.get(Segment, camp.segment_id)
        seg_name = seg.name if seg else None
    return _campaign_response(camp, template_name=tpl_name, segment_name=seg_name)


@router.get("/campaigns")
async def list_campaigns(
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> list[CampaignResponse]:
    rows = (
        await session.scalars(
            select(Campaign)
            .where(Campaign.restaurant_id == restaurant.id)
            .order_by(Campaign.created_at.desc())
        )
    ).all()
    template_ids = {r.template_id for r in rows if r.template_id is not None}
    segment_ids = {r.segment_id for r in rows if r.segment_id is not None}
    templates_by_id: dict[int, WaTemplate] = {}
    if template_ids:
        tpl_rows = (
            await session.scalars(select(WaTemplate).where(WaTemplate.id.in_(template_ids)))
        ).all()
        templates_by_id = {t.id: t for t in tpl_rows}
    segments_by_id: dict[int, Segment] = {}
    if segment_ids:
        seg_rows = (
            await session.scalars(select(Segment).where(Segment.id.in_(segment_ids)))
        ).all()
        segments_by_id = {s.id: s for s in seg_rows}
    # Merge in real sent/delivered/converted from the send ledger so the Reports
    # page (which reads stats.sent / stats.converted) isn't stuck at 0.
    live = await campaign_stats_bulk(session, restaurant_id=restaurant.id)
    return [
        _campaign_response(
            r,
            template_name=(
                templates_by_id[r.template_id].meta_template_name
                if r.template_id in templates_by_id
                else None
            ),
            segment_name=(
                segments_by_id[r.segment_id].name
                if r.segment_id in segments_by_id
                else None
            ),
            live_stats=live.get(r.id, {}),
        )
        for r in rows
    ]


@router.get("/audience", response_model=list[AudienceSegmentOut])
async def list_audience(
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> list[AudienceSegmentOut]:
    """Named RFM buckets + live customer counts for the broadcast Segment pills.

    Counts are mutually exclusive (each customer in exactly one bucket) and
    ``all`` is the whole base, so the named buckets sum to ``all``."""
    counts = await segment_counts(session, restaurant_id=restaurant.id)
    return [
        AudienceSegmentOut(key=key, label=label, count=counts.get(key, 0))
        for key, label in RFM_SEGMENTS
    ]


@router.post(
    "/broadcast",
    response_model=Union[BroadcastResponse, BroadcastScheduleResponse],
    status_code=201,
)
async def broadcast_now(
    body: BroadcastRequest,
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> BroadcastResponse | BroadcastScheduleResponse:
    """Send now or schedule a broadcast for a future time (UTC ``scheduled_at``)."""
    from app.outbox.service import deliver_pending

    if body.segment_id is not None and body.rfm_segment not in (None, "", "all"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Choose a saved segment or an RFM bucket, not both",
        )
    if body.coupon_value is not None:
        try:
            coupon_amt = Decimal(body.coupon_value)
        except InvalidOperation:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "coupon_value must be a decimal string",
            )
        if coupon_amt <= 0:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "coupon_value must be positive",
            )

    now_utc = datetime.now(timezone.utc)
    scheduled = body.scheduled_at
    if scheduled is not None and scheduled.tzinfo is None:
        scheduled = scheduled.replace(tzinfo=timezone.utc)

    try:
        if scheduled is not None and scheduled > now_utc:
            camp, warning = await schedule_broadcast(
                session,
                restaurant_id=restaurant.id,
                template_id=body.template_id,
                scheduled_at=scheduled,
                now_utc=now_utc,
                type=body.type,
                segment_id=body.segment_id,
                rfm_segment=body.rfm_segment,
                coupon_value=body.coupon_value,
            )
            await session.commit()
            return BroadcastScheduleResponse(
                campaign_id=camp.id,
                scheduled_at=scheduled,
                window_warning=warning,
            )

        audience_ids = None
        if body.segment_id is None and body.rfm_segment and body.rfm_segment != "all":
            audience_ids = await segment_customer_ids(
                session, restaurant_id=restaurant.id, key=body.rfm_segment
            )
        camp = await create_campaign(
            session,
            restaurant_id=restaurant.id,
            type=body.type,
            template_id=body.template_id,
            segment_id=body.segment_id,
            coupon_value=body.coupon_value,
        )
        camp.stats = {
            **(camp.stats or {}),
            "rfm_segment": (
                (body.rfm_segment or "all") if body.segment_id is None else None
            ),
            "segment_id": body.segment_id,
        }
        camp.status = "sending"
        await session.flush()
        summary = await run_campaign_send(
            session,
            campaign=camp,
            provider=get_template_provider(),
            now_utc=now_utc,
            audience_ids=audience_ids,
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


@router.delete("/campaigns/{campaign_id}", status_code=204)
async def delete_scheduled_campaign(
    campaign_id: int,
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> None:
    """Cancel a scheduled broadcast before it fires."""
    try:
        await cancel_scheduled_campaign(
            session,
            restaurant_id=restaurant.id,
            campaign_id=campaign_id,
        )
    except ValueError as exc:
        msg = str(exc)
        if msg == "campaign not found":
            raise HTTPException(status.HTTP_404_NOT_FOUND, msg)
        if "only scheduled" in msg:
            raise HTTPException(status.HTTP_409_CONFLICT, msg)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, msg)
    await session.commit()


@router.patch("/campaigns/{campaign_id}/schedule", response_model=BroadcastScheduleResponse)
async def patch_campaign_schedule(
    campaign_id: int,
    body: SchedulePatch,
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> BroadcastScheduleResponse:
    """Reschedule a queued broadcast."""
    scheduled = body.scheduled_at
    if scheduled.tzinfo is None:
        scheduled = scheduled.replace(tzinfo=timezone.utc)
    try:
        camp, warning = await reschedule_campaign(
            session,
            restaurant_id=restaurant.id,
            campaign_id=campaign_id,
            scheduled_at=scheduled,
            now_utc=datetime.now(timezone.utc),
        )
    except ValueError as exc:
        msg = str(exc)
        if msg == "campaign not found":
            raise HTTPException(status.HTTP_404_NOT_FOUND, msg)
        if "only scheduled" in msg:
            raise HTTPException(status.HTTP_409_CONFLICT, msg)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, msg)
    await session.commit()
    return BroadcastScheduleResponse(
        campaign_id=camp.id,
        scheduled_at=scheduled,
        window_warning=warning,
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


@router.get("/automations", response_model=list[AutomationResponse])
async def get_automations(
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> list[AutomationResponse]:
    rows = await list_automations(session, restaurant_id=restaurant.id)
    await session.commit()
    return [AutomationResponse(**r) for r in rows]


@router.patch("/automations/{preset_key}", response_model=AutomationResponse)
async def update_automation(
    preset_key: str,
    body: AutomationPatch,
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> AutomationResponse:
    patch = body.model_dump(exclude_unset=True)
    clear_segment = "segment_id" in patch and patch.get("segment_id") is None
    try:
        await patch_automation(
            session,
            restaurant_id=restaurant.id,
            preset_key=preset_key,
            enabled=patch.get("enabled"),
            template_id=patch.get("template_id"),
            segment_id=patch.get("segment_id"),
            config=(
                body.config.model_dump(exclude_none=True) if body.config is not None else None
            ),
            clear_segment=clear_segment,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await session.commit()
    rows = await list_automations(session, restaurant_id=restaurant.id)
    match = next((r for r in rows if r["preset_key"] == preset_key), None)
    if match is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "automation not found")
    return AutomationResponse(**match)


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
