import uuid
from decimal import Decimal

from app.payments.port import ChargeResult, RefundResult

# Map POS tenders to mock wallet/session prefixes for Apple/Google/Tap/online.
_WALLET_TENDERS = frozenset({"apple_pay", "google_pay", "tap_to_pay", "online"})


class MockPaymentProcessor:
    """Always succeeds. Used for dev/tests and any restaurant that hasn't
    connected a real PSP yet — same role as WhatsApp's MockAdapter."""

    async def charge(self, *, amount_aed: Decimal, tender_type: str, reference: str) -> ChargeResult:
        prefix = "mock_ws" if tender_type in _WALLET_TENDERS else "mock_ch"
        return ChargeResult(
            success=True,
            provider_charge_id=f"{prefix}_{uuid.uuid4().hex[:16]}",
            status="succeeded",
        )

    async def refund(self, *, provider_charge_id: str, amount_aed: Decimal) -> RefundResult:
        return RefundResult(
            success=True, provider_refund_id=f"mock_re_{uuid.uuid4().hex[:16]}", status="succeeded",
        )

    async def create_wallet_session(
        self, *, amount_aed: Decimal, tender_type: str, reference: str
    ) -> dict:
        """Simulate Apple Pay / Google Pay / Tap-to-Pay session minting."""
        sid = f"mock_session_{uuid.uuid4().hex[:12]}"
        return {
            "session_id": sid,
            "tender_type": tender_type,
            "amount_aed": str(amount_aed),
            "reference": reference,
            "client_secret": f"cs_{sid}",
        }
