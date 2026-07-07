from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass
class NormalizedOrderItem:
    dish_name: str
    qty: int
    price_aed: Decimal


@dataclass
class NormalizedInboundOrder:
    provider: str
    provider_order_ref: str
    customer_phone: str
    customer_name: str
    items: list[NormalizedOrderItem]
    total_aed: Decimal


class AggregatorPort(Protocol):
    def parse_inbound(self, payload: dict) -> NormalizedInboundOrder: ...
