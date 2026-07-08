from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class StationIn(BaseModel):
    name: str
    printer_ip: str | None = None
    printer_port: int | None = None


class StationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    printer_ip: str | None
    printer_port: int | None


class TicketItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    order_id: int
    dish_name: str
    variant_name: str | None
    qty: int
    kitchen_status: str
    notes: str | None
    created_at: datetime
    # OrderItem stores this under `allergens_snapshot` (snapshotted from Dish.allergens
    # at add-item time); exposed here under the shorter name the KDS ticket UI expects.
    allergens: list = Field(default_factory=list, validation_alias="allergens_snapshot")
    packaging_checked: bool = False
    quality_checked: bool = False


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


class ReadyForPickupItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    dish_name: str
    variant_name: str | None
    qty: int
    kitchen_status: str
    allergens: list = Field(default_factory=list, validation_alias="allergens_snapshot")


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


class PrinterHeartbeatIn(BaseModel):
    healthy: bool = True


class PrinterStatusOut(BaseModel):
    station_id: int
    healthy: bool
    last_heartbeat_at: datetime
