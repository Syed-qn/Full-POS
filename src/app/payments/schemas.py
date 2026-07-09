from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ChargeIn(BaseModel):
    order_id: int
    # cash|card|apple_pay|google_pay|wallet|deposit|tap_to_pay|online|pay_later|room_charge|gift_card|house_account
    tender_type: str
    amount_aed: Decimal
    tip_aed: Decimal = Decimal("0.00")
    channel: str = "till"
    room_number: str | None = None
    terminal_id: str | None = None
    wallet_session_id: str | None = None


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


class PaymentLinkIn(BaseModel):
    order_id: int
    amount_aed: Decimal | None = None
    expires_hours: int = 48


class PaymentLinkCompleteIn(BaseModel):
    tender_type: str = "online"  # online | card | apple_pay | google_pay


class WalletSessionIn(BaseModel):
    order_id: int
    tender_type: str  # apple_pay | google_pay | tap_to_pay
    amount_aed: Decimal


class DiscountIn(BaseModel):
    discount_type: str  # manager | staff
    amount_aed: Decimal = Field(gt=0)
    reason: str | None = None
    staff_id: int | None = None
    # Category 9 — required when amount ≥ AED 20 or always for manager discounts.
    manager_pin: str | None = None


class PayLaterIn(BaseModel):
    amount_aed: Decimal | None = None
    due_at: datetime | None = None


class BillingSettingsIn(BaseModel):
    service_charge_pct: float | None = None
    packaging_charge_aed: float | None = None
    min_order_aed: float | None = None


class SettlementLineIn(BaseModel):
    provider_charge_id: str
    amount_aed: Decimal


class SettlementImportIn(BaseModel):
    provider: str = "stripe"
    provider_payout_id: str
    amount_aed: Decimal
    settled_at: datetime | None = None
    notes: str | None = None
    lines: list[SettlementLineIn]
