from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol


@dataclass
class NormalizedOrderItem:
    dish_name: str
    qty: int
    price_aed: Decimal
    external_sku: str | None = None


@dataclass
class NormalizedInboundOrder:
    provider: str
    provider_order_ref: str
    customer_phone: str
    customer_name: str
    items: list[NormalizedOrderItem]
    total_aed: Decimal
    notes: str | None = None
    delivery_fee_aed: Decimal = Decimal("0.00")


@dataclass
class MenuPushItem:
    dish_id: int
    dish_number: int
    name: str
    price_aed: Decimal
    is_available: bool
    channels_allowed: list[str] = field(default_factory=list)


@dataclass
class SyncResult:
    success: bool
    provider: str
    action: str
    detail: str | None = None
    items_touched: int = 0


class AggregatorPort(Protocol):
    """Port for food-marketplace integrations (Talabat, Deliveroo, Careem, …).

    Mock adapters always succeed. Real HTTP adapters plug in when credentials exist
    (per-restaurant settings.channels.<provider>).
    """

    def parse_inbound(self, payload: dict) -> NormalizedInboundOrder: ...

    def verify_webhook(self, headers: dict, body: bytes) -> bool:
        """HMAC/signature check; mock always True."""
        ...

    async def push_menu(self, items: list[MenuPushItem]) -> SyncResult: ...

    async def set_item_availability(
        self, *, external_sku: str, available: bool
    ) -> SyncResult: ...

    async def set_store_status(self, *, accepting: bool) -> SyncResult: ...

    async def accept_order(self, *, provider_order_ref: str) -> SyncResult: ...

    async def reject_order(
        self, *, provider_order_ref: str, reason: str = "out_of_stock"
    ) -> SyncResult: ...

    async def push_order_status(
        self, *, provider_order_ref: str, status: str
    ) -> SyncResult:
        """Push kitchen/delivery status to marketplace (optional on mock)."""
        ...

    async def health_check(self) -> SyncResult:
        """Partner API connectivity probe."""
        ...
