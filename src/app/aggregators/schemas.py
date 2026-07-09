"""Pydantic I/O for aggregator / channel APIs."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ChannelConfigOut(BaseModel):
    enabled: bool = False
    accepting: bool = True
    commission_pct: float = 0.0
    mode: str = "mock"  # mock | live
    api_key: Optional[str] = None
    api_key_set: bool = False
    store_id: Optional[str] = None
    base_url: Optional[str] = None
    webhook_secret_set: bool = False
    order_url: Optional[str] = None
    slug: Optional[str] = None


class ChannelsOut(BaseModel):
    channels: dict[str, ChannelConfigOut]
    providers: list[str]
    public_slug: Optional[str] = None
    order_links: dict[str, str] = Field(default_factory=dict)


class ChannelPatchIn(BaseModel):
    enabled: Optional[bool] = None
    accepting: Optional[bool] = None
    commission_pct: Optional[float] = Field(default=None, ge=0, le=100)
    mode: Optional[str] = None  # mock | live
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    webhook_secret: Optional[str] = None
    store_id: Optional[str] = None
    base_url: Optional[str] = None
    order_url: Optional[str] = None
    slug: Optional[str] = None


class ChannelsUpdateIn(BaseModel):
    channels: dict[str, ChannelPatchIn] = Field(default_factory=dict)


class SyncProvidersIn(BaseModel):
    providers: Optional[list[str]] = None


class SyncResultOut(BaseModel):
    provider: str
    success: bool
    action: str
    detail: Optional[str] = None
    items_touched: int = 0


class SettlementIn(BaseModel):
    provider: str
    period_start: date
    period_end: date
    order_count: int = Field(ge=0)
    gross_revenue_aed: Decimal
    commission_aed: Decimal
    net_aed: Optional[Decimal] = None
    external_ref: Optional[str] = None
    notes: Optional[str] = None


class SettlementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    period_start: date
    period_end: date
    order_count: int
    gross_revenue_aed: str
    commission_aed: str
    net_aed: str
    status: str
    external_ref: Optional[str] = None
    notes: Optional[str] = None


class PublicOrderItemIn(BaseModel):
    dish_id: int
    qty: int = Field(ge=1, le=50)
    notes: Optional[str] = None


class PublicStoreOrderIn(BaseModel):
    customer_phone: str = Field(min_length=7, max_length=32)
    customer_name: Optional[str] = None
    items: list[PublicOrderItemIn] = Field(min_length=1)
    channel: str = "website"
    table_id: Optional[int] = None
    notes: Optional[str] = None


class PublicMenuItemOut(BaseModel):
    id: int
    dish_number: Optional[int] = None
    name: str
    description: Optional[str] = None
    price_aed: str
    category: Optional[str] = None
    image_url: Optional[str] = None
    is_available: bool = True


class SlugEnsureIn(BaseModel):
    slug: Optional[str] = None
