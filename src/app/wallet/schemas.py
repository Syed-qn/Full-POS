from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class WalletCreditIn(BaseModel):
    amount_aed: Decimal = Field(gt=0)
    reason: str = Field(min_length=1)


class WalletBalanceOut(BaseModel):
    customer_id: int
    balance_aed: Decimal
    available_aed: Decimal
    status: str


class WalletEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    amount_aed: Decimal
    type: str
    status: str
    order_id: int | None
    ticket_id: int | None
    reason_note: str | None
    created_by: str
    created_at: datetime
