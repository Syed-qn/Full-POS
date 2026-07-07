from datetime import datetime

from pydantic import BaseModel, ConfigDict


class StaffIn(BaseModel):
    name: str
    phone: str | None = None
    role: str = "staff"
    pin: str


class StaffOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    phone: str | None
    role: str


class ClockIn(BaseModel):
    type: str  # clock_in | clock_out


class StaffLoginIn(BaseModel):
    staff_id: int
    pin: str


class ShiftIn(BaseModel):
    staff_id: int
    scheduled_start: datetime
    scheduled_end: datetime


class ShiftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    staff_id: int
    scheduled_start: datetime
    scheduled_end: datetime
