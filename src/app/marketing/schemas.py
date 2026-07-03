"""Pydantic v2 request/response schemas for the Marketing REST API."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SegmentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    dsl: dict[str, Any]
    plain_english: str | None = None


class SegmentResponse(BaseModel):
    id: int
    name: str
    last_preview_count: int | None
    plain_english: str | None = None
    updated_at: datetime | None = None


class SegmentCompileRequest(BaseModel):
    plain_english: str = Field(..., min_length=10, max_length=600)


class SegmentCompileResponse(BaseModel):
    dsl: dict[str, Any]
    preview_count: int
    plain_english: str


class SegmentPreviewRequest(BaseModel):
    dsl: dict[str, Any]


class SegmentPreviewResponse(BaseModel):
    preview_count: int


class CampaignCreate(BaseModel):
    type: str  # "promotional" | "reactivation" | "announcement"
    template_id: int | None = None
    segment_id: int | None = None
    image_url: str | None = None
    coupon_value: str | None = None  # Decimal string e.g. "10.00"
    scheduled_at: datetime | None = None


class CampaignResponse(BaseModel):
    id: int
    type: str
    status: str
    stats: dict[str, Any]
    created_at: datetime | None = None
    scheduled_at: datetime | None = None
    template_name: str | None = None
    audience_label: str | None = None
    segment_id: int | None = None
    template_id: int | None = None


class TemplateFixRequest(BaseModel):
    hint: str | None = Field(default=None, max_length=300)


class TemplateCreate(BaseModel):
    meta_template_name: str
    language: str = "en"
    category: str = "MARKETING"
    body: str
    ephemeral: bool = False
    # header is a component dict: {"type":"text","text":...} or
    # {"type":"IMAGE","image_url":...}. None = no header.
    header: dict[str, Any] | None = None
    footer: str | None = None
    buttons: list[dict] | None = None


class TemplateResponse(BaseModel):
    id: int
    meta_template_name: str
    status: str
    rejection_reason: str | None = None
    # Content — lets the dashboard preview the message without a second fetch.
    body: str | None = None
    header: dict[str, Any] | None = None
    footer: str | None = None
    buttons: list[dict] | None = None


class TemplateDraftRequest(BaseModel):
    describe: str = Field(..., min_length=3, max_length=600)
    with_button: bool = False
    button_label: str | None = None
    button_url: str | None = None


class TemplateDraftResponse(BaseModel):
    suggested_name: str
    body: str
    footer: str | None = None
    examples: list[str] = []


class ImageUploadResponse(BaseModel):
    url: str


class ImageGenerateRequest(BaseModel):
    prompt: str = ""
    describe: str | None = None


class BroadcastRequest(BaseModel):
    template_id: int
    segment_id: int | None = None          # None = all opted-in customers
    rfm_segment: str | None = None         # named RFM bucket key, e.g. "champions"; None/"all" = everyone
    coupon_value: str | None = None        # Decimal string, optional promo coupon
    type: str = "promotional"
    scheduled_at: datetime | None = None   # UTC; if set and > now, queue instead of send


class AudienceSegmentOut(BaseModel):
    """One named RFM bucket with its live customer count (for the Segment pills)."""

    key: str
    label: str
    count: int


class BroadcastResponse(BaseModel):
    campaign_id: int
    queued: int
    suppressed_cap: int
    suppressed_optout: int
    suppressed_window: int


class BroadcastScheduleResponse(BaseModel):
    campaign_id: int
    scheduled_at: datetime
    status: str = "scheduled"
    window_warning: str | None = None


class SchedulePatch(BaseModel):
    scheduled_at: datetime


class SendResponse(BaseModel):
    queued: int
    suppressed_cap: int
    suppressed_optout: int
    suppressed_window: int


class AutomationConfig(BaseModel):
    delay_hours: int | None = None
    lead_minutes: int | None = None
    lapsed_days: int | None = None
    cooldown_days: int | None = None


class AutomationResponse(BaseModel):
    preset_key: str
    title: str
    description: str
    enabled: bool
    template_id: int | None
    segment_id: int | None
    segment_name: str | None = None
    config: AutomationConfig
    stats: dict[str, Any]
    last_run_at: datetime | None = None
    save_blocked: bool = False
    save_blocked_reason: str | None = None


class AutomationPatch(BaseModel):
    enabled: bool | None = None
    template_id: int | None = None
    segment_id: int | None = None
    config: AutomationConfig | None = None
