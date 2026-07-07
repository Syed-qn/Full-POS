from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass
class ChargeResult:
    success: bool
    provider_charge_id: str
    status: str  # succeeded | failed
    error: str | None = None


@dataclass
class RefundResult:
    success: bool
    provider_refund_id: str
    status: str
    error: str | None = None


class PaymentPort(Protocol):
    async def charge(
        self, *, amount_aed: Decimal, tender_type: str, reference: str
    ) -> ChargeResult: ...

    async def refund(
        self, *, provider_charge_id: str, amount_aed: Decimal
    ) -> RefundResult: ...
