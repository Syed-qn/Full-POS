import uuid
from decimal import Decimal

from app.payments.port import ChargeResult, RefundResult


class MockPaymentProcessor:
    """Always succeeds. Used for dev/tests and any restaurant that hasn't
    connected a real PSP yet — same role as WhatsApp's MockAdapter."""

    async def charge(self, *, amount_aed: Decimal, tender_type: str, reference: str) -> ChargeResult:
        return ChargeResult(
            success=True, provider_charge_id=f"mock_ch_{uuid.uuid4().hex[:16]}", status="succeeded",
        )

    async def refund(self, *, provider_charge_id: str, amount_aed: Decimal) -> RefundResult:
        return RefundResult(
            success=True, provider_refund_id=f"mock_re_{uuid.uuid4().hex[:16]}", status="succeeded",
        )
