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


class TemplateCreate(BaseModel):
    meta_template_name: str
    language: str = "en"
    category: str = "MARKETING"
    body: str
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


class BroadcastRequest(BaseModel):
    template_id: int
    segment_id: int | None = None          # None = all opted-in customers
    coupon_value: str | None = None        # Decimal string, optional promo coupon
    type: str = "promotional"


class BroadcastResponse(BaseModel):
    campaign_id: int
    queued: int
    suppressed_cap: int
    suppressed_optout: int
    suppressed_window: int


class SendResponse(BaseModel):
    queued: int
    suppressed_cap: int
    suppressed_optout: int
    suppressed_window: int
