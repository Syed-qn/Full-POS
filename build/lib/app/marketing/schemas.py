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
    header: str | None = None
    footer: str | None = None
    buttons: list[dict] | None = None


class TemplateResponse(BaseModel):
    id: int
    meta_template_name: str
    status: str
    rejection_reason: str | None = None


class SendResponse(BaseModel):
    queued: int
    suppressed_cap: int
    suppressed_optout: int
    suppressed_window: int
