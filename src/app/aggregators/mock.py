from decimal import Decimal

from app.aggregators.port import NormalizedInboundOrder, NormalizedOrderItem


class MockAggregator:
    """Simulates a real aggregator's inbound-order webhook shape closely enough
    to exercise the full ingestion pipeline before any real partner contract
    exists. Expected payload shape mirrors the common fields Talabat/Deliveroo/
    Careem webhooks all share: order id, customer contact, line items, total."""

    def __init__(self, provider: str) -> None:
        self._provider = provider

    def parse_inbound(self, payload: dict) -> NormalizedInboundOrder:
        items = [
            NormalizedOrderItem(
                dish_name=item["name"], qty=int(item["quantity"]), price_aed=Decimal(str(item["price"])),
            )
            for item in payload["items"]
        ]
        return NormalizedInboundOrder(
            provider=self._provider,
            provider_order_ref=str(payload["order_id"]),
            customer_phone=payload["customer"]["phone"],
            customer_name=payload["customer"].get("name", "Guest"),
            items=items,
            total_aed=Decimal(str(payload["total"])),
        )
