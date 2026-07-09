from app.aggregators.live import parse_marketplace_payload
from app.aggregators.port import (
    MenuPushItem,
    NormalizedInboundOrder,
    SyncResult,
)


class MockAggregator:
    """Simulates marketplace webhooks + sync ops for every supported provider.

    Accepts unified + provider-native payload shapes (same parser as live).
    """

    def __init__(self, provider: str) -> None:
        self._provider = provider
        self.last_menu_push: list[MenuPushItem] = []
        self.last_store_status: bool | None = None
        self.availability_updates: list[tuple[str, bool]] = []
        self.status_pushes: list[tuple[str, str]] = []

    def parse_inbound(self, payload: dict) -> NormalizedInboundOrder:
        return parse_marketplace_payload(self._provider, payload)

    def verify_webhook(self, headers: dict, body: bytes) -> bool:
        # Optional shared secret: X-Aggregator-Secret must match if set on payload path.
        secret = headers.get("x-aggregator-secret") or headers.get("X-Aggregator-Secret")
        if secret is None:
            return True
        return bool(secret)

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
