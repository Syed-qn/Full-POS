from decimal import Decimal

from pydantic import BaseModel, Field


class ChargeIn(BaseModel):
    order_id: int
    tender_type: str  # cash | card | apple_pay | google_pay | wallet
    amount_aed: Decimal
    tip_aed: Decimal = Decimal("0.00")


class RefundIn(BaseModel):
    amount_aed: Decimal


class CredentialsIn(BaseModel):
    provider: str  # stripe
    secret_key: str


class CreditNoteIn(BaseModel):
    amount_aed: Decimal = Field(gt=0)
    reason: str | None = None


class DepositIn(BaseModel):
    amount_aed: Decimal = Field(gt=0)


class HouseAccountChargeIn(BaseModel):
    amount_aed: Decimal = Field(gt=0)


class HouseAccountSettleIn(BaseModel):
    amount_aed: Decimal = Field(gt=0)
