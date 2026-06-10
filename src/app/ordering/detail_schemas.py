# src/app/ordering/detail_schemas.py
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, computed_field


class OrderItemDetailOut(BaseModel):
    dish_number: int
    dish_name: str
    qty: int
    price_aed: Decimal

    @computed_field  # type: ignore[misc]
    @property
    def line_total(self) -> Decimal:
        return self.price_aed * self.qty

    model_config = {"from_attributes": True}


class AddressDetailOut(BaseModel):
    id: int
    room_apartment: str | None
    building: str | None
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

    model_config = {"from_attributes": True}


class RiderDetailOut(BaseModel):
    id: int
    name: str
    phone: str

    model_config = {"from_attributes": True}


class TimelineEventOut(BaseModel):
    ts: datetime
    action: str
    actor: str
    after: dict | None


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
    status: str
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
    timeline: list[TimelineEventOut]
    chat: list[ChatMessageOut]
    route: list[GpsPingOut]


class CustomerPatchIn(BaseModel):
    name: str | None = None
    phone: str | None = None
    marketing_opted_in: bool | None = None


class AddressPatchIn(BaseModel):
    room_apartment: str | None = None
    building: str | None = None
    receiver_name: str | None = None
    additional_details: str | None = None
