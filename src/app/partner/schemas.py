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


# ── Partner integration config (Phase 0) ───────────────────────────────────
class PartnerIntegrationConfigOut(BaseModel):
    partner_enabled: bool = False
    partner_webhook_url: str = ""
    partner_webhook_secret_set: bool = False
    pos_store_id: str = ""
    pos_order_push_mode: str = "webhook"


class PartnerIntegrationConfigIn(BaseModel):
    partner_enabled: bool | None = None
    partner_webhook_url: str | None = None
    partner_webhook_secret: str | None = None
    pos_store_id: str | None = None
    pos_order_push_mode: str | None = None


class PartnerStoreOut(BaseModel):
    """Read-only store identity for POS (API-key authed)."""
    restaurant_id: int
    name: str
    phone: str
    pos_store_id: str
    partner_enabled: bool
    pos_order_push_mode: str


class PartnerWebhookTestOut(BaseModel):
    queued: bool
    delivery_id: int | None = None
    detail: str


# ── Partner orders (Phase 1) ─────────────────────────────────────────────────
class PartnerOrderItemOut(BaseModel):
    dish_number: int | None
    name: str
    variant_name: str | None = None
    qty: int
    price: float
    notes: str | None = None


class PartnerOrderCustomerOut(BaseModel):
    id: int | None
    name: str | None
    phone: str | None


class PartnerOrderAddressOut(BaseModel):
    room_apartment: str | None = None
    building: str | None = None
    receiver_name: str | None = None
    additional_details: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class PartnerOrderOut(BaseModel):
    order_id: int
    order_number: str
    pos_store_id: str
    status: str
    pos_order_id: str | None = None
    pos_push_status: str | None = None
    customer: PartnerOrderCustomerOut
    items: list[PartnerOrderItemOut]
    additional_details: str | None = None
    address: PartnerOrderAddressOut | None = None
    subtotal: float
    delivery_fee: float
    wallet_applied: float
    total: float
    cod_due: float
    payment: str = "COD"
    distance_km: float | None = None
    promised_eta: str | None = None
    sla_deadline: str | None = None
    created_at: str | None = None


class PartnerOrderListOut(BaseModel):
    items: list[PartnerOrderOut]
    limit: int
    offset: int


class PartnerOrderAckIn(BaseModel):
    pos_order_id: str = Field(..., min_length=1, max_length=64)


class PartnerOrderStatusIn(BaseModel):
    status: str = Field(
        ...,
        description="POS kitchen status: accepted | preparing | ready | cancelled",
    )
    reason: str | None = Field(default=None, max_length=256)


class PartnerOrderStatusOut(BaseModel):
    order_id: int
    order_number: str
    status: str
    rider_assigned: bool


# ── Partner menu (Phase 3) ───────────────────────────────────────────────────
class PartnerMenuItemIn(BaseModel):
    pos_id: str = Field(..., min_length=1, max_length=64)
    dish_number: int | None = Field(default=None, ge=1)
    name: str = Field(..., min_length=1, max_length=256)
    price: float = Field(..., gt=0)
    category: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    is_available: bool = True


class PartnerMenuBulkIn(BaseModel):
    items: list[PartnerMenuItemIn] = Field(..., min_length=1, max_length=500)


class PartnerMenuPatchIn(BaseModel):
    price: float | None = Field(default=None, gt=0)
    is_available: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=256)


class PartnerMenuUpsertOut(BaseModel):
    created: int
    updated: int
    images: int
    errors: list[str] = Field(default_factory=list)


class PartnerMenuItemOut(BaseModel):
    pos_id: str
    dish_number: int
    name: str
    price: float
    category: str | None = None
    is_available: bool


class PartnerMenuChangedIn(BaseModel):
    changed_at: datetime | None = None


class PartnerMenuChangedOut(BaseModel):
    queued: bool
    mode: str
    detail: str


class PartnerMenuSyncStatusOut(BaseModel):
    pos_dish_count: int
    last_pos_pull: dict = Field(default_factory=dict)


# ── Partner delivery (Phase 4) ───────────────────────────────────────────────
class PartnerRiderOut(BaseModel):
    id: int
    name: str
    phone: str


class PartnerDeliveryOut(BaseModel):
    order_id: int
    order_number: str
    pos_store_id: str
    pos_order_id: str | None = None
    status: str
    rider: PartnerRiderOut | None = None
    batch_id: int | None = None
    eta_minutes: int | None = None
    promised_eta: str | None = None
    delivered_at: str | None = None
    late: bool = False
    cod_due: float
    cod_collected: float | None = None


class PartnerRiderLocationOut(BaseModel):
    rider_id: int
    latitude: float
    longitude: float
    updated_at: str


# ── Partner integration health (Phase 5) ───────────────────────────────────
class PartnerWebhookHealthOut(BaseModel):
    delivery_id: int
    event_type: str
    status: str
    attempts: int
    last_error: str | None = None
    delivered_at: str | None = None
    created_at: str | None = None


class PartnerIntegrationHealthOut(BaseModel):
    partner_enabled: bool
    webhook_url_set: bool
    webhook_secret_set: bool
    pos_store_id: str
    pos_order_push_mode: str
    pending_webhook_count: int
    last_webhook: PartnerWebhookHealthOut | None = None
    menu_sync: PartnerMenuSyncStatusOut | None = None
