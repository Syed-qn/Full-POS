from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StationIn(BaseModel):
    name: str
    station_type: str = "general"
    kitchen_code: str = "main"
    printer_ip: str | None = None
    printer_port: int | None = None
    fallback_station_id: int | None = None
    is_active: bool = True


class StationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    station_type: str = "general"
    kitchen_code: str = "main"
    printer_ip: str | None
    printer_port: int | None
    fallback_station_id: int | None = None
    is_active: bool = True


class CategoryDefaultIn(BaseModel):
    category: str
    station_id: int


class CategoryDefaultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    category: str
    station_id: int


class TicketItemOut(BaseModel):
    """Full KDS ticket row — timer, ETA, allergens, modifiers, checklists."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    order_id: int
    order_number: str | None = None
    order_priority: str | None = None
    order_type: str | None = None
    dish_name: str
    variant_name: str | None
    qty: int
    kitchen_status: str
    notes: str | None
    created_at: datetime
    kitchen_received_at: datetime | None = None
    allergens: list[Any] = Field(default_factory=list)
    selected_modifiers: list[Any] = Field(default_factory=list)
    packaging_checked: bool = False
    quality_checked: bool = False
    missing_item_confirmed: bool = False
    missing_item_note: str | None = None
    course_number: int = 1
    course_held: bool = False
    customer_allergy_notes: str | None = None
    estimated_ready_at: str | None = None
    age_seconds: int = 0
    age_minutes: float = 0.0
    urgency: str = "ok"
    is_delayed: bool = False
    station_id: int | None = None
    kitchen_code: str | None = None
    # Real menu category ("Popcorn", "Paratha Spot") — shown on the board
    # instead of the generic station preset name.
    category: str | None = None
    # Dine-in source table: the kitchen plates by table, not by order number.
    table_id: int | None = None
    table_label: str | None = None
    # Parcel line on a dine-in bill — this one gets boxed, not plated.
    is_takeaway: bool = False
    # The bill is already settled and the order closed, but this line is still
    # on the pass: the guest has paid and is standing at the counter waiting.
    order_settled: bool = False


class PackagingCheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    order_id: int
    packaging_checked: bool


class QualityCheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    order_id: int
    quality_checked: bool


class MissingItemIn(BaseModel):
    note: str | None = None


class MissingItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    order_id: int
    missing_item_confirmed: bool
    missing_item_note: str | None = None


class ReadyForPickupItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    dish_name: str
    variant_name: str | None
    qty: int
    kitchen_status: str
    allergens: list = Field(default_factory=list, validation_alias="allergens_snapshot")
    packaging_checked: bool = False
    quality_checked: bool = False
    missing_item_confirmed: bool = False


class ReadyForPickupOrderOut(BaseModel):
    order_id: int
    order_number: str
    items: list[ReadyForPickupItemOut]


class PrintJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    station_id: int
    order_id: int
    payload: str
    status: str
    via_fallback: bool = False
    original_station_id: int | None = None


class PrinterHeartbeatIn(BaseModel):
    healthy: bool = True


class PrinterStatusOut(BaseModel):
    station_id: int
    healthy: bool
    last_heartbeat_at: datetime


class BumpIn(BaseModel):
    staff_id: int | None = None


class KitchenPerformanceOut(BaseModel):
    ticket_count: int
    bumped_count: int
    late_ticket_count: int
    avg_prep_minutes: float | None
    by_station: list[dict[str, Any]]
