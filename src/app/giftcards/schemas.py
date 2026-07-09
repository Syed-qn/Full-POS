from decimal import Decimal

from pydantic import BaseModel, Field


class GiftCardPurchaseIn(BaseModel):
    recipient_phone: str
    amount_aed: Decimal
    purchase_reference: str


class GiftCardIssueIn(BaseModel):
    amount_aed: Decimal = Field(gt=0)
    pin: str
    code: str | None = None
    customer_id: int | None = None


class GiftCardRedeemIn(BaseModel):
    code: str
    pin: str
    order_id: int
    amount_aed: Decimal = Field(gt=0)
