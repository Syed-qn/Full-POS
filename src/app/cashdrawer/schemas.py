from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class OpenSessionIn(BaseModel):
    opening_float_aed: Decimal


class EventIn(BaseModel):
    type: str  # cash_in | cash_out
    amount_aed: Decimal
    reason: str | None = None


class CloseSessionIn(BaseModel):
    closing_count_aed: Decimal


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    opened_by: str
    opening_float_aed: Decimal
    closed_by: str | None
    closing_count_aed: Decimal | None
    variance_aed: Decimal | None
    status: str
