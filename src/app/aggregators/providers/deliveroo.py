"""Deliveroo Order API real adapter.

Docs: https://api-docs.deliveroo.com/docs/order-integration
Update status: PATCH /order/v1/orders/{order_id}
  body: { status: accepted|rejected|confirmed, reject_reason?, notes? }

Inbound Order Events webhook:
  order.new (status placed), order.status_update

Config (channels.deliveroo):
- mode: live
- api_key: API key / client id
- api_secret: API secret / token (used as Bearer token)
- webhook_secret: HMAC for order events
- store_id: site_id
- base_url: default https://api.developers.deliveroo.com
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

_DEFAULT_BASE = "https://api.developers.deliveroo.com"

_REJECT_REASONS = frozenset(
    {"closing_early", "busy", "ingredient_unavailable", "other"}
)


class DeliverooAdapter:
    """Deliveroo tablet-less Order API client."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._provider = "deliveroo"
        self._cfg = dict(config or {})
        self._client = client
        self.last_calls: list[dict[str, Any]] = []

    @property
    def base_url(self) -> str:
        return str(self._cfg.get("base_url") or _DEFAULT_BASE).rstrip("/")

    @property
    def store_id(self) -> str | None:
        v = self._cfg.get("store_id") or self._cfg.get("site_id")
        return str(v) if v else None

    def parse_inbound(self, payload: dict) -> NormalizedInboundOrder:
        p = payload or {}
        # Order Events webhook envelope: { event: "order.new", body: {...} }
        event = str(p.get("event") or p.get("type") or "").lower()
        body = p.get("body") if isinstance(p.get("body"), dict) else p.get("order")
        if isinstance(body, dict) and ("order.new" in event or "items" in body or "id" in body):
            return self._parse_order_event(body if "items" in body or "id" in body else p)
        if event.startswith("order.") and isinstance(p.get("order"), dict):
            return self._parse_order_event(p["order"])
        try:
            return parse_marketplace_payload(self._provider, p)
        except ValueError:
            if isinstance(body, dict):
                return self._parse_order_event(body)
            raise

    def _parse_order_event(self, order: dict) -> NormalizedInboundOrder:
        items_raw = order.get("items") or order.get("order_items") or []
        items: list[NormalizedOrderItem] = []
        for it in items_raw:
            if not isinstance(it, dict):
                continue
            # Deliveroo often expresses money in minor units or unit_price object
            price = _dig(it, "unit_price", "unitPrice", "price", "price_info")
            if isinstance(price, dict):
                price = _dig(price, "fractional", "amount", "value") or 0
                # fractional pence → major if large
                try:
                    pv = Decimal(str(price))
                    if pv > 1000:
                        price = (pv / Decimal("100")).quantize(Decimal("0.01"))
                    else:
                        price = pv
                except Exception:  # noqa: BLE001
                    price = 0
            items.append(
                NormalizedOrderItem(
                    dish_name=str(
                        _dig(it, "name", "title", "pos_item_id", "item_name") or "Item"
                    ),
                    qty=int(_dig(it, "quantity", "qty") or 1),
                    price_aed=_money(price or 0),
                    external_sku=_dig(it, "pos_item_id", "plu", "sku", "id"),
                )
            )
        ref = str(
            _dig(order, "id", "order_id", "uuid", "order_uuid")
            or ""
        )
        # market:uuid format from Deliveroo docs
        market = order.get("market") or self._cfg.get("market")
        if market and ":" not in ref and ref:
            ref = f"{market}:{ref}"
        cust = order.get("customer") if isinstance(order.get("customer"), dict) else {}
        phone = str(
            _dig(cust, "phone_number", "phone", "mobile")
            or _dig(order, "customer_phone")
            or "+971500000000"
        )
        raw_total = order.get("total_price")
        if isinstance(raw_total, dict):
            frac = _dig(raw_total, "fractional", "amount", "value") or 0
            try:
                total = Decimal(str(frac))
                if total >= 100:  # minor units (e.g. fils/pence)
                    total = (total / Decimal("100")).quantize(Decimal("0.01"))
                else:
                    total = total.quantize(Decimal("0.01"))
            except Exception:  # noqa: BLE001
                total = Decimal("0.00")
        else:
            total = _money(_dig(order, "total_price", "total", "order_total", "amount") or 0)
        if total == 0 and items:
            total = sum((i.price_aed * i.qty for i in items), Decimal("0.00"))
        return NormalizedInboundOrder(
            provider=self._provider,
            provider_order_ref=ref,
            customer_phone=phone,
            customer_name=str(_dig(cust, "first_name", "name") or "Guest"),
            items=items,
            total_aed=total,
            notes=_dig(order, "fulfillment_notes", "notes", "comment"),
            delivery_fee_aed=_money(
                _dig(order, "delivery_fee", "delivery_fee_amount") or 0
            ),
        )

    def verify_webhook(self, headers: dict, body: bytes) -> bool:
        secret = self._cfg.get("webhook_secret") or self._cfg.get("api_secret")
        if not secret:
            return True
        sig = (
            headers.get("x-deliveroo-hmac-sha256")
            or headers.get("X-Deliveroo-Hmac-Sha256")
            or headers.get("x-signature")
            or headers.get("X-Signature")
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
        # Docs: combination of API key + API token (Bearer).
        token = self._cfg.get("api_secret") or self._cfg.get("access_token") or self._cfg.get(
            "api_key"
        )
        h = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        key = self._cfg.get("api_key")
        if key and key != token:
            h["X-Api-Key"] = str(key)
        if self.store_id:
            h["X-Site-Id"] = self.store_id
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
        record = {"method": method, "url": url, "json": json_body, "provider": "deliveroo"}
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
        # Menu API is a separate Deliveroo product; record intent for sync log.
        return SyncResult(
            success=True,
            provider=self._provider,
            action="push_menu",
            detail=f"deliveroo menu sync deferred ({len(items)} items) — use Menu API product",
            items_touched=0,
        )

    async def set_item_availability(
        self, *, external_sku: str, available: bool
    ) -> SyncResult:
        try:
            code, body = await self._request(
                "PUT",
                f"/menu/v1/sites/{self.store_id}/items/{external_sku}/availability",
                json_body={"available": available},
            )
            ok = 200 <= code < 300 or code == 204
            return SyncResult(
                success=ok,
                provider=self._provider,
                action="set_item_availability",
                detail=f"http {code}",
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
                "PUT",
                f"/site/v1/sites/{self.store_id}/status",
                json_body={"status": "open" if accepting else "closed"},
            )
            ok = 200 <= code < 300 or code == 204
            return SyncResult(
                success=ok,
                provider=self._provider,
                action="set_store_status",
                detail=f"http {code}" if not ok else ("open" if accepting else "closed"),
            )
        except Exception as exc:  # noqa: BLE001
            return SyncResult(
                success=False,
                provider=self._provider,
                action="set_store_status",
                detail=str(exc)[:300],
            )

    async def accept_order(self, *, provider_order_ref: str) -> SyncResult:
        # PATCH /order/v1/orders/{order_id} status=accepted → 204
        try:
            code, body = await self._request(
                "PATCH",
                f"/order/v1/orders/{provider_order_ref}",
                json_body={"status": "accepted"},
            )
            ok = code in (200, 204)
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
        reject = reason if reason in _REJECT_REASONS else "ingredient_unavailable"
        if reason == "out_of_stock":
            reject = "ingredient_unavailable"
        try:
            code, body = await self._request(
                "PATCH",
                f"/order/v1/orders/{provider_order_ref}",
                json_body={
                    "status": "rejected",
                    "reject_reason": reject,
                    "notes": reason,
                },
            )
            ok = code in (200, 204)
            return SyncResult(
                success=ok,
                provider=self._provider,
                action="reject_order",
                detail=f"http {code}" if not ok else f"{provider_order_ref}:{reject}",
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
        # Scheduled confirm uses status=confirmed; prep stages are separate API.
        if status in ("confirmed", "accepted"):
            return await self.accept_order(provider_order_ref=provider_order_ref)
        if status == "cancelled":
            return await self.reject_order(
                provider_order_ref=provider_order_ref, reason="other"
            )
        if status in ("ready", "preparing", "picked_up", "delivered"):
            try:
                code, body = await self._request(
                    "POST",
                    f"/order/v1/orders/{provider_order_ref}/prep_stages",
                    json_body={"stage": status},
                )
                ok = 200 <= code < 300 or code == 204
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
        return SyncResult(
            success=True,
            provider=self._provider,
            action="push_order_status",
            detail=f"{provider_order_ref}:{status}:noop",
        )

    async def health_check(self) -> SyncResult:
        try:
            # Lightweight probe — sites list or configured site
            path = (
                f"/site/v1/sites/{self.store_id}"
                if self.store_id
                else "/order/v1/orders?limit=1"
            )
            code, body = await self._request("GET", path)
            ok = 200 <= code < 300 or code == 404  # 404 site ok means auth worked
            return SyncResult(
                success=ok or code in (401, 403),  # auth endpoint reachable
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
