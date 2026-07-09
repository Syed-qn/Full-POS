"""Live HTTP aggregator adapters (Talabat / Deliveroo / Careem / Uber / Noon / Zomato).

Selected when restaurant channel config has ``mode=live`` + ``api_key``.
Uses httpx against partner REST endpoints (base_url overridable per channel).
Without live credentials the factory keeps MockAggregator.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from decimal import Decimal
from typing import Any

import httpx

from app.aggregators.port import (
    MenuPushItem,
    NormalizedInboundOrder,
    NormalizedOrderItem,
    SyncResult,
)

_logger = logging.getLogger(__name__)

# Default partner API bases — override with channels.<provider>.base_url.
_DEFAULT_BASE: dict[str, str] = {
    "talabat": "https://api.partners.talabat.com/v1",
    "deliveroo": "https://api.developers.deliveroo.com/v1",
    "careem": "https://partners.careem.com/v1",
    "ubereats": "https://api.uber.com/v1/eats",
    "noon": "https://api.noon.partners/v1",
    "zomato": "https://api.zomato.com/partner/v1",
}


def _money(v: Any) -> Decimal:
    return Decimal(str(v if v is not None else "0")).quantize(Decimal("0.01"))


def _dig(d: dict, *keys: str, default=None):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] is not None:
            return d[k]
    return default


class LiveHttpAggregator:
    """Real HTTP implementation of AggregatorPort.

    Parameters
    ----------
    provider:
        Marketplace key (talabat, deliveroo, …).
    config:
        Channel config dict: api_key, api_secret, webhook_secret, base_url,
        store_id, timeout_seconds.
    client:
        Optional httpx.AsyncClient (tests inject MockTransport).
    """

    def __init__(
        self,
        provider: str,
        config: dict[str, Any] | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._provider = (provider or "").strip().lower()
        self._cfg = dict(config or {})
        self._client = client
        self._owns_client = client is None
        self.last_calls: list[dict[str, Any]] = []

    @property
    def base_url(self) -> str:
        raw = (self._cfg.get("base_url") or _DEFAULT_BASE.get(self._provider) or "").rstrip(
            "/"
        )
        return raw

    @property
    def api_key(self) -> str:
        return str(self._cfg.get("api_key") or "")

    @property
    def store_id(self) -> str | None:
        v = self._cfg.get("store_id")
        return str(v) if v else None

    def _headers(self) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Provider": self._provider,
        }
        if self.store_id:
            h["X-Store-Id"] = self.store_id
        secret = self._cfg.get("api_secret")
        if secret:
            h["X-Api-Secret"] = str(secret)
        return h

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | list | None = None,
    ) -> tuple[int, dict | list | str | None]:
        url = f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}"
        timeout = float(self._cfg.get("timeout_seconds") or 15)
        record = {"method": method, "url": url, "json": json_body}
        self.last_calls.append(record)

        client = self._client
        close_after = False
        if client is None:
            client = httpx.AsyncClient(timeout=timeout)
            close_after = True
        try:
            resp = await client.request(
                method,
                url,
                headers=self._headers(),
                json=json_body,
                timeout=timeout,
            )
            record["status_code"] = resp.status_code
            body: dict | list | str | None
            try:
                body = resp.json()
            except Exception:  # noqa: BLE001
                body = resp.text
            record["response"] = body if not isinstance(body, str) or len(body) < 500 else body[:500]
            return resp.status_code, body
        finally:
            if close_after:
                await client.aclose()

    def parse_inbound(self, payload: dict) -> NormalizedInboundOrder:
        """Normalize marketplace webhook payloads (unified + provider-native shapes)."""
        return parse_marketplace_payload(self._provider, payload)

    def verify_webhook(self, headers: dict, body: bytes) -> bool:
        """HMAC-SHA256 over body using webhook_secret, or shared secret header."""
        secret = (
            self._cfg.get("webhook_secret")
            or self._cfg.get("api_secret")
            or self._cfg.get("api_key")
        )
        if not secret:
            # Live mode without secret still accepts (partner may use mTLS/IP allowlist).
            return True

        # Shared secret header (compatible with mock tests + many partners)
        hdr_secret = (
            headers.get("x-aggregator-secret")
            or headers.get("X-Aggregator-Secret")
            or headers.get("x-webhook-secret")
            or headers.get("X-Webhook-Secret")
        )
        if hdr_secret is not None:
            return hmac.compare_digest(str(hdr_secret), str(secret))

        # Signature headers
        sig = (
            headers.get("x-signature")
            or headers.get("X-Signature")
            or headers.get("x-hub-signature-256")
            or headers.get("X-Hub-Signature-256")
            or headers.get("x-deliveroo-hmac-sha256")
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
        payload = {
            "store_id": self.store_id,
            "items": [
                {
                    "sku": f"dish-{i.dish_id}",
                    "plu": str(i.dish_number),
                    "name": i.name,
                    "price": str(i.price_aed),
                    "available": i.is_available,
                    "channels": i.channels_allowed,
                }
                for i in items
            ],
        }
        try:
            code, body = await self._request("POST", "/menu", json_body=payload)
            ok = 200 <= code < 300
            return SyncResult(
                success=ok,
                provider=self._provider,
                action="push_menu",
                detail=f"http {code}" + (f": {body}" if not ok else f" pushed {len(items)}"),
                items_touched=len(items) if ok else 0,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning("live push_menu failed: %s", exc)
            return SyncResult(
                success=False,
                provider=self._provider,
                action="push_menu",
                detail=str(exc)[:300],
            )

    async def set_item_availability(
        self, *, external_sku: str, available: bool
    ) -> SyncResult:
        try:
            code, body = await self._request(
                "PATCH",
                f"/items/{external_sku}/availability",
                json_body={"available": available, "store_id": self.store_id},
            )
            ok = 200 <= code < 300
            return SyncResult(
                success=ok,
                provider=self._provider,
                action="set_item_availability",
                detail=f"http {code}" if not ok else f"{external_sku}={'on' if available else 'off'}",
                items_touched=1 if ok else 0,
            )
        except Exception as exc:  # noqa: BLE001
            return SyncResult(
                success=False,
                provider=self._provider,
                action="set_item_availability",
                detail=str(exc)[:300],
            )

    async def set_store_status(self, *, accepting: bool) -> SyncResult:
        try:
            code, body = await self._request(
                "POST",
                "/store/status",
                json_body={
                    "store_id": self.store_id,
                    "accepting": accepting,
                    "status": "ONLINE" if accepting else "PAUSED",
                },
            )
            ok = 200 <= code < 300
            return SyncResult(
                success=ok,
                provider=self._provider,
                action="set_store_status",
                detail=f"http {code}" if not ok else ("accepting" if accepting else "paused"),
            )
        except Exception as exc:  # noqa: BLE001
            return SyncResult(
                success=False,
                provider=self._provider,
                action="set_store_status",
                detail=str(exc)[:300],
            )

    async def accept_order(self, *, provider_order_ref: str) -> SyncResult:
        try:
            code, body = await self._request(
                "POST",
                f"/orders/{provider_order_ref}/accept",
                json_body={"store_id": self.store_id},
            )
            ok = 200 <= code < 300
            return SyncResult(
                success=ok,
                provider=self._provider,
                action="accept_order",
                detail=f"http {code}" if not ok else provider_order_ref,
            )
        except Exception as exc:  # noqa: BLE001
            return SyncResult(
                success=False,
                provider=self._provider,
                action="accept_order",
                detail=str(exc)[:300],
            )

    async def reject_order(
        self, *, provider_order_ref: str, reason: str = "out_of_stock"
    ) -> SyncResult:
        try:
            code, body = await self._request(
                "POST",
                f"/orders/{provider_order_ref}/reject",
                json_body={"store_id": self.store_id, "reason": reason},
            )
            ok = 200 <= code < 300
            return SyncResult(
                success=ok,
                provider=self._provider,
                action="reject_order",
                detail=f"http {code}" if not ok else f"{provider_order_ref}:{reason}",
            )
        except Exception as exc:  # noqa: BLE001
            return SyncResult(
                success=False,
                provider=self._provider,
                action="reject_order",
                detail=str(exc)[:300],
            )

    async def push_order_status(
        self, *, provider_order_ref: str, status: str
    ) -> SyncResult:
        """Push kitchen/delivery status back to the marketplace."""
        try:
            code, body = await self._request(
                "POST",
                f"/orders/{provider_order_ref}/status",
                json_body={
                    "store_id": self.store_id,
                    "status": status,
                },
            )
            ok = 200 <= code < 300
            return SyncResult(
                success=ok,
                provider=self._provider,
                action="push_order_status",
                detail=f"http {code}" if not ok else f"{provider_order_ref}:{status}",
            )
        except Exception as exc:  # noqa: BLE001
            return SyncResult(
                success=False,
                provider=self._provider,
                action="push_order_status",
                detail=str(exc)[:300],
            )

    async def health_check(self) -> SyncResult:
        try:
            code, body = await self._request("GET", "/health")
            ok = 200 <= code < 300
            return SyncResult(
                success=ok,
                provider=self._provider,
                action="health_check",
                detail=f"http {code}",
            )
        except Exception as exc:  # noqa: BLE001
            return SyncResult(
                success=False,
                provider=self._provider,
                action="health_check",
                detail=str(exc)[:300],
            )


def parse_marketplace_payload(provider: str, payload: dict) -> NormalizedInboundOrder:
    """Normalize common marketplace webhook shapes into NormalizedInboundOrder."""
    p = payload or {}
    provider = (provider or "").strip().lower()

    # Nested order wrapper (some partners send { "order": {...} })
    if "order" in p and isinstance(p["order"], dict) and "items" not in p and "products" not in p:
        p = p["order"]

    # Unified shape (mock / generic partner)
    if "items" in p and ("order_id" in p or "orderId" in p or "id" in p):
        items_raw = p.get("items") or []
        if items_raw and isinstance(items_raw[0], dict):
            # Deliveroo-ish unit_price
            if "unit_price" in items_raw[0] or "unitPrice" in items_raw[0]:
                items = [
                    NormalizedOrderItem(
                        dish_name=str(
                            _dig(it, "name", "title", "item_name") or "Item"
                        ),
                        qty=int(_dig(it, "quantity", "qty") or 1),
                        price_aed=_money(
                            _dig(it, "unit_price", "unitPrice", "price") or 0
                        ),
                        external_sku=_dig(it, "sku", "plu", "id"),
                    )
                    for it in items_raw
                ]
            else:
                items = [
                    NormalizedOrderItem(
                        dish_name=str(_dig(it, "name", "title", "item_name") or "Item"),
                        qty=int(_dig(it, "quantity", "qty") or 1),
                        price_aed=_money(_dig(it, "price", "price_aed", "amount") or 0),
                        external_sku=_dig(it, "sku", "plu", "id"),
                    )
                    for it in items_raw
                ]
            ref = str(_dig(p, "order_id", "orderId", "id") or "")
            cust = p.get("customer") if isinstance(p.get("customer"), dict) else {}
            phone = str(
                _dig(cust, "phone", "mobile", "phone_number", "phoneNumber")
                or _dig(p, "customer_phone", "phone")
                or "+971500000000"
            )
            name = str(_dig(cust, "name", "full_name") or "Guest")
            total = _money(_dig(p, "total", "total_aed", "order_total", "grand_total") or 0)
            if total == 0 and items:
                total = sum((i.price_aed * i.qty for i in items), Decimal("0.00"))
            return NormalizedInboundOrder(
                provider=provider,
                provider_order_ref=ref,
                customer_phone=phone,
                customer_name=name,
                items=items,
                total_aed=total,
                notes=_dig(p, "notes", "special_instructions", "comment"),
                delivery_fee_aed=_money(
                    _dig(p, "delivery_fee", "deliveryFee", "delivery_fee_aed") or 0
                ),
            )

    # Talabat / Careem products[] shape
    products = p.get("products") or p.get("line_items") or []
    if products:
        items = [
            NormalizedOrderItem(
                dish_name=str(_dig(it, "name", "product_name", "title") or "Item"),
                qty=int(_dig(it, "quantity", "qty", "count") or 1),
                price_aed=_money(
                    _dig(it, "price", "unit_price", "unitPrice", "price_aed", "amount")
                    or 0
                ),
                external_sku=_dig(it, "sku", "plu", "product_id", "id"),
            )
            for it in products
            if isinstance(it, dict)
        ]
        ref = str(_dig(p, "order_id", "orderId", "id", "reference") or "")
        cust = p.get("customer") if isinstance(p.get("customer"), dict) else {}
        phone = str(
            _dig(cust, "phone", "mobile", "phone_number")
            or _dig(p, "customer_phone")
            or "+971500000000"
        )
        total = _money(_dig(p, "total", "grand_total", "order_value") or 0)
        if total == 0 and items:
            total = sum((i.price_aed * i.qty for i in items), Decimal("0.00"))
        return NormalizedInboundOrder(
            provider=provider,
            provider_order_ref=ref,
            customer_phone=phone,
            customer_name=str(_dig(cust, "name") or "Guest"),
            items=items,
            total_aed=total,
            notes=_dig(p, "notes", "comment"),
            delivery_fee_aed=_money(_dig(p, "delivery_fee", "delivery_charges") or 0),
        )

    raise ValueError(
        f"unrecognized {provider} webhook payload keys: {list(p.keys())[:12]}"
    )


# Map internal order status → marketplace status vocabulary
MARKETPLACE_STATUS_MAP = {
    "confirmed": "accepted",
    "preparing": "preparing",
    "ready": "ready_for_pickup",
    "assigned": "driver_assigned",
    "picked_up": "picked_up",
    "arriving": "nearby",
    "delivered": "delivered",
    "cancelled": "cancelled",
}
