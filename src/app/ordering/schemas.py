# src/app/ordering/schemas.py
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dish_number: int
    dish_name: str
    price_aed: Decimal
    qty: int
    notes: Optional[str]


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    restaurant_id: int
    customer_id: int
    order_number: str
    status: str
    priority: str
    subtotal: Decimal
    delivery_fee_aed: Decimal
    total: Decimal
    distance_km: Optional[float]
    weather_delay_disclosed: bool
    sla_confirmed_at: Optional[datetime]
    sla_deadline: Optional[datetime]
    promised_eta: Optional[datetime]
    delivered_at: Optional[datetime]
    late: Optional[bool]
    additional_details: Optional[str]
    address_id: Optional[int]
    cancellation_reason: Optional[str]
    cancelled_at: Optional[datetime]
    resale_of_order_id: Optional[int]
    created_at: datetime
    updated_at: datetime


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
