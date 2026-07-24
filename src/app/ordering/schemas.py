# src/app/ordering/schemas.py
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    dish_number: Optional[int]
    name: str          # dish_name field on OrderItem
    qty: int
    price_aed: str     # serialised as string for JS safety
    variant_name: Optional[str] = None  # serving size, if any
    notes: Optional[str] = None          # special request (e.g. "double masala") — for kitchen
    cancelled: bool = False              # partial cancellation — item struck without voiding order
    cancelled_reason: Optional[str] = None
    course_number: int = 1
    course_held: bool = False
    is_takeaway: bool = False
    seat_number: Optional[int] = None


class OrderOut(BaseModel):
    """Enriched order response — includes customer, items, rider, and address."""
    id: int
    order_number: str
    # Human-facing daily queue token (e.g. 626); null for legacy rows.
    daily_token: Optional[int] = None
    status: str
    # Kitchen progress for on-premise orders (dine-in/takeaway), whose ORDER
    # status stays "confirmed" the whole time — only the items move through the
    # kitchen. "preparing" = on the pass with items not yet all bumped; "ready" =
    # every item bumped (plated); None = not sent to the kitchen yet. Lets the
    # cashier/manager pill read Preparing -> Ready instead of a stuck "confirmed".
    kitchen_stage: Optional[str] = None
    customer_name: Optional[str]
    customer_phone: str
    items: list[OrderItemOut]
    total_aed: str
    rider_id: Optional[int]
    rider_name: Optional[str]
    sla_started_at: Optional[str]   # ISO 8601 of sla_confirmed_at
    prep_deadline: Optional[str]    # ISO 8601 — kitchen "plate by" time (distance-driven)
    cook_estimate_minutes: Optional[int]  # est. cook time; start-by = prep_deadline − this
    created_at: str
    address: Optional[str]
    lat: Optional[float]
    lng: Optional[float]
    # Batching: when this order shares a rider trip with others, batch_size > 1 and
    # batch_order_numbers lists every order on that trip (in delivery sequence) so the
    # dashboard can show the manager which orders go out together.
    batch_id: Optional[int] = None
    batch_size: Optional[int] = None
    batch_order_numbers: list[str] = Field(default_factory=list)
    # Forecast (pre-assignment): a label ("A", "B", …) shared by still-unassigned
    # orders whose drop-offs are close enough to ride together, so the list can flag
    # an upcoming batch BEFORE a rider is assigned. Null when the order would ride alone.
    batch_preview: Optional[str] = None
    # Set on resale copies (…-RS rows). Null on the cancelled original.
    resale_of_order_id: Optional[int] = None
    # Why the order was cancelled — lets the UI tell a real cancel apart from a
    # merge ("Merged into order …"), which shouldn't read as "Cancelled".
    cancellation_reason: Optional[str] = None
    # Category-1 POS fields
    order_type: Optional[str] = "delivery"
    priority: Optional[str] = "normal"
    held_at: Optional[str] = None
    held_reason: Optional[str] = None
    table_id: Optional[int] = None
    staff_id: Optional[int] = None
    scheduled_for: Optional[str] = None
    is_preorder: bool = False
    customer_allergy_notes: Optional[str] = None
    # Category-8 channel inbox
    aggregator_source: Optional[str] = None
    aggregator_order_ref: Optional[str] = None
    source_channel: Optional[str] = None
    # SLA breach acknowledged on the Live Ops board (ISO 8601), plus who did it.
    # The order stays late — this only takes it off the alert queue.
    sla_acked_at: Optional[str] = None
    sla_acked_by_staff_id: Optional[int] = None


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    restaurant_id: int
    phone: str
    name: Optional[str]
    total_orders: int
    total_spend: Decimal
    first_order_at: Optional[datetime]
    last_order_at: Optional[datetime]


class ManualOrderItemIn(BaseModel):
    dish_id: int
    qty: int = Field(ge=1, le=50)
    notes: str | None = None


class ManualOrderAddressIn(BaseModel):
    apt_room: str = Field(min_length=1)
    building: str = Field(min_length=1)
    receiver_name: str = Field(min_length=1)
    notes: str | None = None
    # Exact pin from the map picker (manager searched/dropped a pin). When
    # present these are used as-is; otherwise the building text is geocoded.
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class AddressOut(BaseModel):
    apt_room: str
    building: str
    receiver_name: str
    notes: str | None
    # Saved drop-off pin, so a returning customer's exact map location is restored
    # on lookup instead of being re-geocoded from the building text (or lost).
    latitude: float | None = None
    longitude: float | None = None


class ManualOrderIn(BaseModel):
    customer_phone: str = Field(min_length=7)
    customer_name: str | None = None
    items: list[ManualOrderItemIn] = Field(min_length=1)
    address: ManualOrderAddressIn
    delivery_fee_aed: Decimal = Decimal("0.00")
    scheduled_for: datetime | None = None
    order_type: str = "delivery"
    priority: str = "normal"
    is_preorder: bool = False
    table_id: int | None = None
    staff_id: int | None = None
    customer_allergy_notes: str | None = None
    # Cashier "KOT" intent: send the order to the kitchen immediately after it is
    # created. Delivery/online orders are KOT-gated (no tickets at confirm), so
    # without this a cashier Home Delivery would sit at "confirmed" with no ticket
    # unless a second /advance call fired it — and a lost/failed advance would
    # silently strand the order off the kitchen board. Firing here makes it atomic.
    fire_to_kitchen: bool = False


class PosOrderItemIn(BaseModel):
    dish_id: int
    qty: int = Field(ge=1, le=50)
    notes: str | None = None
    course_number: int = Field(default=1, ge=1, le=20)
    course_held: bool = False
    # Parcel this line even though the order is dine-in (same bill, boxed).
    is_takeaway: bool = False
    seat_number: int | None = Field(default=None, ge=1, le=50)


class PosOrderIn(BaseModel):
    """Unified POS create for dine-in / takeaway / drive-thru / delivery / online / tableside."""

    order_type: str
    customer_phone: str = Field(min_length=7)
    customer_name: str | None = None
    items: list[PosOrderItemIn] = Field(min_length=1)
    table_id: int | None = None
    covers: int | None = Field(default=None, ge=1, le=50)
    staff_id: int | None = None
    address: ManualOrderAddressIn | None = None
    delivery_fee_aed: Decimal = Decimal("0.00")
    scheduled_for: datetime | None = None
    is_preorder: bool = False
    priority: str = "normal"
    customer_allergy_notes: str | None = None
    auto_confirm: bool = True


class AddOrderItemsIn(BaseModel):
    """Append more lines to an already-open order (dine-in tab: another round)."""

    items: list[PosOrderItemIn] = Field(min_length=1)


class HoldOrderIn(BaseModel):
    reason: str | None = Field(default=None, max_length=256)


class PriorityIn(BaseModel):
    priority: str = Field(min_length=1, max_length=16)


class FireCourseIn(BaseModel):
    course_number: int = Field(ge=1, le=20)


class CoversIn(BaseModel):
    """Update a dine-in party size after seating (guests joined / left)."""

    covers: int = Field(ge=1, le=50)


class RepeatLastOrderIn(BaseModel):
    customer_phone: str = Field(min_length=7)


class RefundOrderIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class QrOrderIn(BaseModel):
    customer_phone: str = Field(min_length=7)
    customer_name: str | None = None
    items: list[PosOrderItemIn] = Field(min_length=1)


class CustomerLookupOut(BaseModel):
    name: str | None
    last_address: AddressOut | None


class CancelOrderIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class ReassignOrderIn(BaseModel):
    rider_id: int


class CancelOrderItemIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class SplitOrderByItemsIn(BaseModel):
    item_ids: list[int] = Field(min_length=1)


class SplitOrderBySeatIn(BaseModel):
    seat_number: int


class MergeOrdersIn(BaseModel):
    primary_order_id: int
    secondary_order_id: int


class TransferOrderStaffIn(BaseModel):
    staff_id: int


class EditOrderItemIn(BaseModel):
    qty: int | None = Field(default=None, ge=1, le=50)
    notes: str | None = Field(default=None, max_length=512)


class DeliveryPhotoIn(BaseModel):
    photo_url: str | None = Field(default=None, max_length=512)
    photo_base64: str | None = None


class VerifyDeliveryOtpIn(BaseModel):
    otp: str = Field(min_length=4, max_length=4)


class DeliveryFailedIn(BaseModel):
    reason: str = Field(min_length=1, max_length=256)
