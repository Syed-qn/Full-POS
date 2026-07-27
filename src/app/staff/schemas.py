from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    #: Branch-local number the person signs in with (1, 2, 3… per restaurant).
    staff_code: int | None = None
    name: str
    phone: str | None
    role: str
    is_active: bool = True
    training_mode: bool = False


class ManagerCreateIn(BaseModel):
    """Owner-only: create a manager staff member (role is forced to manager)."""

    name: str = Field(min_length=1, max_length=128)
    phone: str | None = None
    pin: str = Field(min_length=4, max_length=128)


class ManagerUpdateIn(BaseModel):
    """Owner-only: patch a manager. Every field optional; pin only reset if given."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    phone: str | None = None
    pin: str | None = Field(default=None, min_length=4, max_length=128)
    is_active: bool | None = None


class StaffPatchIn(BaseModel):
    """Edit a non-manager staff member (waiter/cashier/kitchen). Every field
    optional; the PIN is only reset when a new one is supplied."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    phone: str | None = None
    pin: str | None = Field(default=None, min_length=4, max_length=128)
    is_active: bool | None = None


class ClockIn(BaseModel):
    type: str  # clock_in | clock_out | break_start | break_end


class StaffLoginIn(BaseModel):
    """Branch-scoped staff sign-in.

    ``store`` is mandatory: without it the server cannot tell restaurant A's
    "manager 1" from restaurant C's, and the lookup degrades to the platform-wide
    search that let staff sign into the wrong tenant.
    """

    #: Branch id — the ``location`` half of account+location. A provisioned
    #: terminal sends this; ``store`` remains for the typed short-code path.
    location: str | None = Field(default=None, min_length=4, max_length=64)
    #: Owning business. Optional, and checked as a second factor when present:
    #: a link whose account does not own the location is refused.
    account: str | None = Field(default=None, min_length=4, max_length=64)
    store: str | None = Field(default=None, min_length=4, max_length=64)
    staff_code: int | None = Field(default=None, ge=0)
    #: Legacy surrogate id — still accepted, but now resolved inside ``store`` only.
    staff_id: int | None = Field(default=None, ge=0)
    pin: str

    # A model validator, not field validators: pydantic skips field validators for
    # fields that were never supplied, which is exactly the case being rejected
    # here — a body with no branch at all must fail loudly, not fall through to
    # an empty lookup and surface as "wrong PIN".
    @model_validator(mode="after")
    def _need_branch_and_identifier(self):
        if not (self.location or self.store):
            raise ValueError("location (or store) is required")
        if self.staff_code is None and self.staff_id is None:
            raise ValueError("staff_code (or staff_id) is required")
        return self


class StorePairingOut(BaseModel):
    """What a terminal shows BEFORE anyone signs in, so whoever is pairing it can
    see which branch the link resolved to.

    Two branches a few streets apart have unrelated ids but near-identical
    coordinates, so the NAME is what makes a wrong link obvious to a human; the
    coordinates are shown only as a secondary confirmation.
    """

    name: str
    lat: float
    lng: float


class StoreIdentityOut(BaseModel):
    """Owner-only. The pairing keys an operator types once when setting up a
    terminal — shown in Settings, never on the public site."""

    model_config = ConfigDict(from_attributes=True)
    #: The pair a terminal link carries. ``account`` is null for a standalone
    #: restaurant that is not under an organization yet.
    account_uuid: str | None = None
    location_uuid: str
    #: Short typeable form of location_uuid, for keypad entry with no link.
    store_code: str
    name: str


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
