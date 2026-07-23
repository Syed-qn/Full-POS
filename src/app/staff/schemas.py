from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: The only roles a person can be given. "owner" is not here on purpose — that
#: is the restaurant account itself, not an assignable staff role.
ASSIGNABLE_ROLES = ("manager", "waiter", "cashier", "kitchen")


class StaffIn(BaseModel):
    name: str
    phone: str | None = None
    role: str = "waiter"
    pin: str

    @field_validator("role")
    @classmethod
    def _known_role(cls, v: str) -> str:
        r = (v or "").strip().lower()
        if r not in ASSIGNABLE_ROLES:
            raise ValueError(
                f"role must be one of {', '.join(ASSIGNABLE_ROLES)}"
            )
        return r


class StaffOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    phone: str | None
    role: str
    is_active: bool = True
    training_mode: bool = False


class ClockIn(BaseModel):
    type: str  # clock_in | clock_out | break_start | break_end


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
    status: str = "scheduled"
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None


class ManagerPinIn(BaseModel):
    pin: str = Field(min_length=4, max_length=128)
    action_type: str = "manager_override"
    order_id: Optional[int] = None
    amount_aed: Optional[Decimal] = None
    reason: Optional[str] = None
    requested_by_staff_id: Optional[int] = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    action_type: str
    status: str
    requested_by_staff_id: Optional[int] = None
    approved_by_staff_id: Optional[int] = None
    order_id: Optional[int] = None
    amount_aed: Optional[str] = None
    reason: Optional[str] = None
    created_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None


class MistakeIn(BaseModel):
    staff_id: int
    mistake_type: str
    order_id: Optional[int] = None
    amount_aed: Decimal = Decimal("0.00")
    notes: Optional[str] = None


class MistakeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    staff_id: int
    mistake_type: str
    order_id: Optional[int] = None
    amount_aed: str
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


class TrainingModeIn(BaseModel):
    training_mode: bool


class AttributeTipIn(BaseModel):
    order_id: int
    staff_id: int


class SuspiciousOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    alert_type: str
    severity: str
    staff_id: Optional[int] = None
    detail: dict[str, Any] = Field(default_factory=dict)
    acknowledged: bool = False
    created_at: Optional[datetime] = None
