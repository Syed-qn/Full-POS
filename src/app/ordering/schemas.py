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


class OrderOut(BaseModel):
    """Enriched order response — includes customer, items, rider, and address."""
    id: int
    order_number: str
    status: str
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


class ManualOrderIn(BaseModel):
    customer_phone: str = Field(min_length=7)
    customer_name: str | None = None
    items: list[ManualOrderItemIn] = Field(min_length=1)
    address: ManualOrderAddressIn
    delivery_fee_aed: Decimal = Decimal("0.00")
    scheduled_for: datetime | None = None


class CustomerLookupOut(BaseModel):
    name: str | None
    last_address: AddressOut | None


class CancelOrderIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class ReassignOrderIn(BaseModel):
    rider_id: int


class CancelOrderItemIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class EditOrderItemIn(BaseModel):
    qty: int | None = Field(default=None, ge=1, le=50)
    notes: str | None = Field(default=None, max_length=512)


class DeliveryPhotoIn(BaseModel):
    photo_url: str = Field(min_length=1, max_length=512)


class VerifyDeliveryOtpIn(BaseModel):
    otp: str = Field(min_length=4, max_length=4)


class DeliveryFailedIn(BaseModel):
    reason: str = Field(min_length=1, max_length=256)
