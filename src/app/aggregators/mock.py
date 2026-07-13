import hashlib
import hmac
from typing import Any

from app.aggregators.live import parse_marketplace_payload
from app.aggregators.port import (
    MenuPushItem,
    NormalizedInboundOrder,
    SyncResult,
)


class MockAggregator:
    """Simulates marketplace webhooks + sync ops for every supported provider.

    Accepts unified + provider-native payload shapes (same parser as live).
    When the restaurant set a webhook_secret / api_secret, mock still enforces it
    (multi-tenant: partners cannot hit another restaurant without the secret).
    """

    def __init__(self, provider: str, config: dict[str, Any] | None = None) -> None:
        self._provider = provider
        self._cfg = dict(config or {})
        self.last_menu_push: list[MenuPushItem] = []
        self.last_store_status: bool | None = None
        self.availability_updates: list[tuple[str, bool]] = []
        self.status_pushes: list[tuple[str, str]] = []

    def parse_inbound(self, payload: dict) -> NormalizedInboundOrder:
        return parse_marketplace_payload(self._provider, payload)

    def verify_webhook(self, headers: dict, body: bytes) -> bool:
        secret = (
            self._cfg.get("webhook_secret")
            or self._cfg.get("api_secret")
            or self._cfg.get("api_key")
        )
        if not secret:
            # Dev mock with no tenant secret configured — open (local tests).
            return True
        hdr_secret = (
            headers.get("x-aggregator-secret")
            or headers.get("X-Aggregator-Secret")
            or headers.get("x-webhook-secret")
            or headers.get("X-Webhook-Secret")
        )
        if hdr_secret is not None:
            return hmac.compare_digest(str(hdr_secret), str(secret))
        sig = (
            headers.get("x-signature")
            or headers.get("X-Signature")
            or headers.get("x-hub-signature-256")
        )
        if not sig:
            return False
        sig = str(sig)
        if sig.startswith("sha256="):
            sig = sig[7:]
        digest = hmac.new(
            str(secret).encode("utf-8"), body or b"", hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(digest, sig)

    async def push_menu(self, items: list[MenuPushItem]) -> SyncResult:
        self.last_menu_push = list(items)
        return SyncResult(
            success=True,
            provider=self._provider,
            action="push_menu",
            detail=f"mock pushed {len(items)} items",
            items_touched=len(items),
        )

    async def set_item_availability(
        self, *, external_sku: str, available: bool
    ) -> SyncResult:
        self.availability_updates.append((external_sku, available))
        return SyncResult(
            success=True,
            provider=self._provider,
            action="set_item_availability",
            detail=f"{external_sku}={'on' if available else 'off'}",
            items_touched=1,
        )

    async def set_store_status(self, *, accepting: bool) -> SyncResult:
        self.last_store_status = accepting
        return SyncResult(
            success=True,
            provider=self._provider,
            action="set_store_status",
            detail="accepting" if accepting else "paused",
        )

    async def accept_order(self, *, provider_order_ref: str) -> SyncResult:
        return SyncResult(
            success=True,
            provider=self._provider,
            action="accept_order",
            detail=provider_order_ref,
        )

    async def reject_order(
        self, *, provider_order_ref: str, reason: str = "out_of_stock"
    ) -> SyncResult:
        return SyncResult(
            success=True,
            provider=self._provider,
            action="reject_order",
            detail=f"{provider_order_ref}:{reason}",
        )

    async def push_order_status(
        self, *, provider_order_ref: str, status: str
    ) -> SyncResult:
        self.status_pushes.append((provider_order_ref, status))
        return SyncResult(
            success=True,
            provider=self._provider,
            action="push_order_status",
            detail=f"{provider_order_ref}:{status}",
        )

    async def health_check(self) -> SyncResult:
        return SyncResult(
            success=True,
            provider=self._provider,
            action="health_check",
            detail="mock ok",
        )
