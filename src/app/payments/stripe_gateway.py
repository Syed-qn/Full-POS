from decimal import Decimal

import httpx

from app.payments.port import ChargeResult, RefundResult

_API_BASE = "https://api.stripe.com/v1"

# Stripe's payment_method_types accepts these directly; Apple Pay / Google Pay
# ride on top of "card" (they're wallet UIs that produce a card-network token,
# not separate Stripe payment method types) — see Stripe's Payment Element docs.
_TENDER_TO_STRIPE_METHOD = {
    "card": "card",
    "apple_pay": "card",
    "google_pay": "card",
    "tap_to_pay": "card",
    "online": "card",
}


class StripeGateway:
    """Real PSP integration via Stripe's REST API. Needs APP_STRIPE_SECRET_KEY
    set to a real Stripe secret key to actually process a charge — same
    real-code-needs-real-credentials shape as ClaudeExtractor."""

    def __init__(self, secret_key: str, client: httpx.AsyncClient | None = None) -> None:
        self._secret_key = secret_key
        self._client = client or httpx.AsyncClient(base_url=_API_BASE, timeout=10.0)

    async def charge(self, *, amount_aed: Decimal, tender_type: str, reference: str) -> ChargeResult:
        method = _TENDER_TO_STRIPE_METHOD.get(tender_type)
        if method is None:
            return ChargeResult(success=False, provider_charge_id="", status="failed", error=f"unsupported tender_type {tender_type}")
        amount_fils = int((amount_aed * 100).to_integral_value())
        try:
            resp = await self._client.post(
                "/payment_intents",
                data={
                    "amount": amount_fils, "currency": "aed",
                    "payment_method_types[]": method,
                    "metadata[reference]": reference,
                    "confirm": "true",
                },
                auth=(self._secret_key, ""),
            )
        except httpx.HTTPError as exc:
            return ChargeResult(success=False, provider_charge_id="", status="failed", error=str(exc))
        body = resp.json()
        if resp.status_code >= 400:
            return ChargeResult(success=False, provider_charge_id="", status="failed", error=body.get("error", {}).get("message", "stripe error"))
        return ChargeResult(success=True, provider_charge_id=body["id"], status="succeeded")

    async def refund(self, *, provider_charge_id: str, amount_aed: Decimal) -> RefundResult:
        amount_fils = int((amount_aed * 100).to_integral_value())
        try:
            resp = await self._client.post(
                "/refunds",
                data={"payment_intent": provider_charge_id, "amount": amount_fils},
                auth=(self._secret_key, ""),
            )
        except httpx.HTTPError as exc:
            return RefundResult(success=False, provider_refund_id="", status="failed", error=str(exc))
        body = resp.json()
        if resp.status_code >= 400:
            return RefundResult(success=False, provider_refund_id="", status="failed", error=body.get("error", {}).get("message", "stripe error"))
        return RefundResult(success=True, provider_refund_id=body["id"], status="succeeded")

    async def create_wallet_session(
        self, *, amount_aed: Decimal, tender_type: str, reference: str
    ) -> dict:
        """Create a PaymentIntent without confirm for Apple/Google Pay client confirmation."""
        method = _TENDER_TO_STRIPE_METHOD.get(tender_type, "card")
        amount_fils = int((amount_aed * 100).to_integral_value())
        try:
            resp = await self._client.post(
                "/payment_intents",
                data={
                    "amount": amount_fils,
                    "currency": "aed",
                    "payment_method_types[]": method,
                    "metadata[reference]": reference,
                    "metadata[tender]": tender_type,
                },
                auth=(self._secret_key, ""),
            )
        except httpx.HTTPError as exc:
            return {"error": str(exc), "session_id": None}
        body = resp.json()
        if resp.status_code >= 400:
            return {
                "error": body.get("error", {}).get("message", "stripe error"),
                "session_id": None,
            }
        return {
            "session_id": body["id"],
            "client_secret": body.get("client_secret"),
            "tender_type": tender_type,
            "amount_aed": str(amount_aed),
            "reference": reference,
        }
