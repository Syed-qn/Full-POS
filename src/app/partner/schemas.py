"""Pydantic I/O schemas for the partner integration API."""
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ApiKeyCreateIn(BaseModel):
    label: str = Field(..., min_length=1, max_length=120)


class ApiKeyOut(BaseModel):
    id: int
    label: str
    key_prefix: str
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class ApiKeyCreatedOut(ApiKeyOut):
    """Returned ONLY at creation — carries the full key, shown to the manager
    once and never retrievable again."""

    api_key: str


# ── Partner-facing data (read-only, API-key authed) ──────────────────────────
class PartnerCustomerOut(BaseModel):
    id: int
    name: str | None
    phone: str
    total_orders: int
    total_spend: Decimal
    first_order_at: datetime | None
    last_order_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PartnerCustomerListOut(BaseModel):
    items: list[PartnerCustomerOut]
    limit: int
    offset: int
    # Echo the high-water mark so the POS can resume an incremental sync.
    next_updated_since: datetime | None = None
