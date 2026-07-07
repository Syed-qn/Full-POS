from decimal import Decimal

from pydantic import BaseModel


class GiftCardPurchaseIn(BaseModel):
    recipient_phone: str
    amount_aed: Decimal
    purchase_reference: str
