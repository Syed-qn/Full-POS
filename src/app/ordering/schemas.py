# src/app/ordering/schemas.py
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    dish_number: Optional[int]
    name: str          # dish_name field on OrderItem
    qty: int
    price_aed: str     # serialised as string for JS safety


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
    created_at: str
    address: Optional[str]
    lat: Optional[float]
    lng: Optional[float]


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
