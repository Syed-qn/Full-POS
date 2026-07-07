from pydantic import BaseModel, ConfigDict


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


class PrintJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    station_id: int
    order_id: int
    payload: str
    status: str
