"""Middleware-mediated marketplace adapters (Careem Food, Noon Food).

Native Careem / Noon Food partner APIs are **not public** (see
``docs/AGGREGATOR_API_REFERENCE.md``). Production integrations go through
certified middleware (Deliverect, Foodics, GetOrder, etc.).

This module implements a **POS connector** shape commonly used by those
middlewares:

Inbound order webhook (middleware → our POS):
```json
{
  "channelOrderId": "C-1001",
  "channelOrderDisplayId": "1001",
  "channel": "careem",
  "items": [{"plu": "101", "name": "Shawarma", "quantity": 1, "price": 2500}],
  "customer": {"name": "Ali", "phoneNumber": "+9715..."},
  "payment": {"amount": 2500},
  "note": "no onion"
}
```
Prices may be major units (AED) or minor units (fils) — heuristic: >= 100 integer → /100.

Outbound status (our POS → middleware callback):
- POST {base_url}/orders/{channelOrderId}/status
  body: { status, channel, storeId, reason? }

Config (channels.careem | channels.noon):
- mode: live
- api_key: middleware API key / account id
- api_secret: middleware secret (webhook HMAC)
- store_id: location / channelLink id
- base_url: middleware callback host (required for live pushes)
- channel: optional override of channel name in payloads
- webhook_secret: HMAC for inbound
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from decimal import Decimal
from typing import Any

import httpx

from app.aggregators.live import _dig, _money, parse_marketplace_payload
from app.aggregators.port import (
    MenuPushItem,
    NormalizedInboundOrder,
    NormalizedOrderItem,
    SyncResult,
)

_logger = logging.getLogger(__name__)

# Placeholders only — real URLs come from middleware partner onboarding.
_DEFAULT_BASE: dict[str, str] = {
    "careem": "https://api.middleware.local/careem",
    "noon": "https://api.middleware.local/noon",
}

# Map internal kitchen/order statuses → middleware POS status vocabulary.
_STATUS_MAP = {
    "accepted": "accepted",
    "confirmed": "accepted",
    "preparing": "preparing",
    "ready": "prepared",
    "prepared": "prepared",
    "picked_up": "pickup_complete",
    "delivered": "finalized",
    "cancelled": "canceled",
    "canceled": "canceled",
    "rejected": "canceled",
}


class MiddlewareChannelAdapter:
    """Deliverect/Foodics-style connector for Careem / Noon (and similar)."""

    def __init__(
        self,
        provider: str,
        config: dict[str, Any] | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._provider = (provider or "").strip().lower()
        if self._provider not in ("careem", "noon"):
            raise ValueError(f"MiddlewareChannelAdapter only for careem/noon, got {provider}")
        self._cfg = dict(config or {})
        self._client = client
        self.last_calls: list[dict[str, Any]] = []

    @property
    def base_url(self) -> str:
        raw = self._cfg.get("base_url") or _DEFAULT_BASE.get(self._provider) or ""
        return str(raw).rstrip("/")

    @property
    def store_id(self) -> str | None:
        v = self._cfg.get("store_id") or self._cfg.get("channel_link_id") or self._cfg.get(
            "location_id"
        )
        return str(v) if v else None

    @property
    def channel_name(self) -> str:
        return str(self._cfg.get("channel") or self._provider)

    def parse_inbound(self, payload: dict) -> NormalizedInboundOrder:
        p = payload or {}
        # Deliverect-style
        if "channelOrderId" in p or "channelOrderDisplayId" in p:
            return self._parse_deliverect_style(p)
        # Nested
        order = p.get("order") if isinstance(p.get("order"), dict) else None
        if order and ("channelOrderId" in order or "items" in order):
            return self._parse_deliverect_style(order)
        try:
            return parse_marketplace_payload(self._provider, p)
        except ValueError:
            if order:
                return parse_marketplace_payload(self._provider, order)
            raise

    def _price_units(self, raw: Any) -> Decimal:
        try:
            pv = Decimal(str(raw if raw is not None else "0"))
        except Exception:  # noqa: BLE001
            return Decimal("0.00")
        # Minor units heuristic (fils): integer-ish and large
        if pv >= 100 and pv == pv.to_integral_value():
            return (pv / Decimal("100")).quantize(Decimal("0.01"))
        return pv.quantize(Decimal("0.01"))

    def _parse_deliverect_style(self, order: dict) -> NormalizedInboundOrder:
        items: list[NormalizedOrderItem] = []
        for it in order.get("items") or order.get("products") or []:
            if not isinstance(it, dict):
                continue
            items.append(
                NormalizedOrderItem(
                    dish_name=str(_dig(it, "name", "productName", "title") or "Item"),
                    qty=int(_dig(it, "quantity", "qty") or 1),
                    price_aed=self._price_units(
                        _dig(it, "price", "unitPrice", "unit_price", "price_aed") or 0
                    ),
                    external_sku=_dig(it, "plu", "sku", "productId", "id"),
                )
            )
        ref = str(
            _dig(order, "channelOrderId", "channel_order_id", "orderId", "id") or ""
        )
        cust = order.get("customer") if isinstance(order.get("customer"), dict) else {}
        phone = str(
            _dig(cust, "phoneNumber", "phone", "mobile", "phone_number")
            or _dig(order, "customer_phone")
            or "+971500000000"
        )
        name = str(_dig(cust, "name", "firstName", "first_name") or "Guest")
        payment = order.get("payment") if isinstance(order.get("payment"), dict) else {}
        total = self._price_units(
            _dig(payment, "amount", "total")
            or _dig(order, "paymentAmount", "total", "orderTotal", "grandTotal")
            or 0
        )
        if total == 0 and items:
            total = sum((i.price_aed * i.qty for i in items), Decimal("0.00"))
        return NormalizedInboundOrder(
            provider=self._provider,
            provider_order_ref=ref,
            customer_phone=phone,
            customer_name=name,
            items=items
            or [
                NormalizedOrderItem(
                    dish_name=f"{self._provider} order",
                    qty=1,
                    price_aed=Decimal("0.00"),
                )
            ],
            total_aed=total,
            notes=_dig(order, "note", "notes", "remark", "specialInstructions"),
            delivery_fee_aed=self._price_units(
                _dig(order, "deliveryCost", "deliveryFee", "delivery_fee") or 0
            ),
        )

    def verify_webhook(self, headers: dict, body: bytes) -> bool:
        secret = (
            self._cfg.get("webhook_secret")
            or self._cfg.get("api_secret")
            or self._cfg.get("api_key")
        )
        if not secret:
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
            or headers.get("x-hmac-sha256")
            or headers.get("X-Hmac-Sha256")
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

    def _headers(self) -> dict[str, str]:
        token = self._cfg.get("api_secret") or self._cfg.get("access_token") or self._cfg.get(
            "api_key"
        )
        h = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Channel": self.channel_name,
        }
        key = self._cfg.get("api_key")
        if key and str(key) != str(token):
            h["X-Api-Key"] = str(key)
        if self.store_id:
            h["X-Store-Id"] = self.store_id
            h["X-Channel-Link-Id"] = self.store_id
        return h

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | list | None = None,
    ) -> tuple[int, dict | list | str | None]:
        url = f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}"
        timeout = float(self._cfg.get("timeout_seconds") or 20)
        record = {
            "method": method,
            "url": url,
            "json": json_body,
            "provider": self._provider,
        }
        self.last_calls.append(record)
        client = self._client
        close_after = False
        if client is None:
            client = httpx.AsyncClient(timeout=timeout)
            close_after = True
        try:
            resp = await client.request(
                method, url, headers=self._headers(), json=json_body, timeout=timeout
            )
            record["status_code"] = resp.status_code
            if resp.status_code == 204:
                return 204, None
            try:
                body: dict | list | str | None = resp.json()
            except Exception:  # noqa: BLE001
                body = resp.text
            record["response"] = body
            return resp.status_code, body
        finally:
            if close_after:
                await client.aclose()

    async def push_menu(self, items: list[MenuPushItem]) -> SyncResult:
        # Middleware often owns catalog; push best-effort product list.
        payload = {
            "storeId": self.store_id,
            "channel": self.channel_name,
            "items": [
                {
                    "plu": str(i.dish_number),
                    "name": i.name,
                    "price": int(Decimal(str(i.price_aed)) * 100),
                    "available": i.is_available,
                }
                for i in items
            ],
        }
        try:
            code, body = await self._request("POST", "/menu", json_body=payload)
            ok = 200 <= code < 300 or code == 204
            return SyncResult(
                success=ok,
                provider=self._provider,
                action="push_menu",
                detail=(
                    f"http {code} middleware menu"
                    if not ok
                    else f"middleware menu {len(items)} items"
                ),
                items_touched=len(items) if ok else 0,
            )
        except Exception as exc:  # noqa: BLE001
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
                json_body={
                    "available": available,
                    "storeId": self.store_id,
                    "channel": self.channel_name,
                },
            )
            ok = 200 <= code < 300 or code == 204
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
                    "storeId": self.store_id,
                    "channel": self.channel_name,
                    "status": "ONLINE" if accepting else "PAUSED",
                    "accepting": accepting,
                },
            )
            ok = 200 <= code < 300 or code == 204
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
        return await self.push_order_status(
            provider_order_ref=provider_order_ref, status="accepted"
        )

    async def reject_order(
        self, *, provider_order_ref: str, reason: str = "out_of_stock"
    ) -> SyncResult:
        try:
            code, body = await self._request(
                "POST",
                f"/orders/{provider_order_ref}/status",
                json_body={
                    "status": "canceled",
                    "reason": reason,
                    "channel": self.channel_name,
                    "storeId": self.store_id,
                },
            )
            ok = 200 <= code < 300 or code == 204
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
        mapped = _STATUS_MAP.get((status or "").lower(), status or "unknown")
        try:
            code, body = await self._request(
                "POST",
                f"/orders/{provider_order_ref}/status",
                json_body={
                    "status": mapped,
                    "channel": self.channel_name,
                    "storeId": self.store_id,
                },
            )
            ok = 200 <= code < 300 or code == 204
            return SyncResult(
                success=ok,
                provider=self._provider,
                action="push_order_status",
                detail=f"http {code}" if not ok else f"{provider_order_ref}:{mapped}",
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
                detail=f"http {code} middleware",
            )
        except Exception as exc:  # noqa: BLE001
            return SyncResult(
                success=False,
                provider=self._provider,
                action="health_check",
                detail=str(exc)[:300],
            )
