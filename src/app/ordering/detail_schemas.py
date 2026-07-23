# src/app/ordering/detail_schemas.py
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, computed_field


class OrderItemDetailOut(BaseModel):
    dish_number: int
    dish_name: str
    variant_name: str | None = None
    qty: int
    price_aed: Decimal
    notes: str | None = None  # special request (e.g. "double masala") — shown to kitchen
    # Held lines are on the bill but deliberately withheld from the kitchen
    # until the course is fired — the UI needs this to offer "fire held".
    course_held: bool = False
    is_takeaway: bool = False

    @computed_field  # type: ignore[misc]
    @property
    def line_total(self) -> Decimal:
        return self.price_aed * self.qty

    model_config = {"from_attributes": True}


class AddressDetailOut(BaseModel):
    id: int
    room_apartment: str | None
    building: str | None
    floor: str | None = None
    receiver_name: str | None
    additional_details: str | None
    latitude: float | None
    longitude: float | None

    model_config = {"from_attributes": True}


class CustomerDetailOut(BaseModel):
    id: int
    name: str | None
    phone: str
    total_orders: int
    total_spend: Decimal
    first_order_at: datetime | None
    last_order_at: datetime | None
    marketing_opted_in: bool
    allergy_notes: str | None = None
    notes: str | None = None
    birthday: date | None = None
    anniversary: date | None = None
    is_vip: bool = False
    loyalty_points: int = 0
    average_order_value_aed: Decimal | None = None
    customer_lifetime_value_aed: Decimal | None = None

    model_config = {"from_attributes": True}


class RiderDetailOut(BaseModel):
    id: int
    name: str
    phone: str

    model_config = {"from_attributes": True}


class TimelineEventOut(BaseModel):
    ts: datetime
    action: str
    actor: str                       # the ROLE that acted
    actor_name: str | None = None    # the person, when a staff session did it
    after: dict | None


class PaymentDetailOut(BaseModel):
    """One tender against the bill — how the guest actually paid. A split bill
    produces several rows, which is why this is a list and not a single field."""

    id: int
    tender_type: str          # cash | card | wallet | ...
    amount_aed: Decimal
    tip_aed: Decimal
    status: str               # pending | succeeded | failed | refunded
    channel: str              # till | pos_cod | link | ...
    provider: str
    refunded_amount_aed: Decimal
    reference_meta: str | None = None
    created_at: datetime


class ChatMessageOut(BaseModel):
    direction: str   # "inbound" | "outbound"
    text: str | None
    ts: int          # unix epoch


class GpsPingOut(BaseModel):
    latitude: float
    longitude: float
    ts: datetime


class OrderDetailOut(BaseModel):
    id: int
    order_number: str
    daily_token: int | None = None
    status: str
    order_type: str | None = None
    items: list[OrderItemDetailOut]
    address: AddressDetailOut | None
    customer: CustomerDetailOut
    rider: RiderDetailOut | None
    subtotal: Decimal
    delivery_fee_aed: Decimal
    total: Decimal
    created_at: datetime
    delivered_at: datetime | None
    sla_deadline: datetime | None
    sla_started_at: datetime | None = None
    prep_deadline: datetime | None
    cook_estimate_minutes: int | None
    # ── A→Z service record: who took it, when the kitchen saw it, when it was
    #    ready, and how it was settled. Populated for every order type.
    table_label: str | None = None
    covers: int | None = None
    staff_name: str | None = None          # who opened the tab (waiter / cashier)
    kitchen_sent_at: datetime | None = None    # first item shown to the kitchen (KOT)
    kitchen_ready_at: datetime | None = None   # last item bumped — whole order plated
    kitchen_ready_by: str | None = None        # who bumped the last item
    kitchen_pending_items: int = 0             # items not yet bumped
    payments: list[PaymentDetailOut] = []
    paid_total_aed: Decimal | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None
    timeline: list[TimelineEventOut]
    chat: list[ChatMessageOut]
    convo_summary: str | None = None  # kitchen digest: item notes + persisted order/address details
    route: list[GpsPingOut]
    batch_preview_label: str | None = None
    dispatch_explain: dict | None = None


class CustomerPatchIn(BaseModel):
    name: str | None = None
    phone: str | None = None
    marketing_opted_in: bool | None = None
    allergy_notes: str | None = None
    notes: str | None = None
    birthday: date | None = None
    anniversary: date | None = None
    is_vip: bool | None = None
    tags: dict[str, Any] | None = None


class AddressPatchIn(BaseModel):
    room_apartment: str | None = None
    building: str | None = None
    floor: str | None = None
    receiver_name: str | None = None
    additional_details: str | None = None


class OrderSummaryOut(BaseModel):
    id: int
    order_number: str
    status: str
    total: Decimal
    created_at: datetime
    resale_of_order_id: int | None = None
    order_type: str | None = None

    model_config = {"from_attributes": True}


class FavoriteOut(BaseModel):
    dish_id: int | None = None
    dish_name: str
    order_count: int


class PhoneHistoryOut(BaseModel):
    phone: str
    changed_by: str
    created_at: datetime | None = None


class StampCardOut(BaseModel):
    stamps: int
    stamps_required: int
    rewards_redeemed: int


class CustomerProfileOut(BaseModel):
    id: int
    name: str | None
    phone: str
    total_orders: int
    total_spend: Decimal
    first_order_at: datetime | None
    last_order_at: datetime | None
    usual_order_time: str | None = None
    marketing_opted_in: bool
    allergy_notes: str | None = None
    notes: str | None = None
    birthday: date | None = None
    anniversary: date | None = None
    is_vip: bool = False
    loyalty_points: int = 0
    average_order_value_aed: Decimal | None = None
    customer_lifetime_value_aed: Decimal | None = None
    tags: dict
    loyalty_tier: str | None = None
    loyalty_tier_locked: bool = False
    addresses: list[AddressDetailOut]
    recent_orders: list[OrderSummaryOut]
    favorites: list[FavoriteOut] = []
    phone_history: list[PhoneHistoryOut] = []
    stamp_card: StampCardOut | None = None
    referral_code: str | None = None

    model_config = {"from_attributes": True}


class CustomerListOut(BaseModel):
    items: list[CustomerDetailOut]
    limit: int
    offset: int
