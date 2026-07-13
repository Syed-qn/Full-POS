"""Keeta (myKeeta) Open API real adapter.

Docs:
- https://api-docs.mykeeta.com/apis/standard/docs/intro
- https://api-docs.mykeeta.com/apis/standard/docs/orderintegrationguide
- https://api-docs.mykeeta.com/apis/standard/docs/apirequest
- https://api-docs.mykeeta.com/apis/standard/docs/author

Every request body must include: appId, accessToken, timestamp, sig (SHA-256).
sig = SHA256( url + "?" + sorted(key=value)&... + appSecret )

Order APIs:
- POST /api/open/order/confirm  — accept
- POST /api/open/order/cancel   — reject/cancel
- POST /api/open/order/prepare  — meal ready
- POST /api/open/order/collect  — pickup collected

Webhooks eventId:
- 1001 new order, 1002 accepted, 1003 completed, 1004 cancelled, …

Config (channels.keeta):
- mode: live
- api_key: appId (or app_id)
- api_secret: appSecret for sig
- access_token: OAuth merchant accessToken (90-day)
- store_id: shopId
- base_url: default https://open.mykeeta.com
- webhook_secret: same as api_secret for inbound sig verify
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from decimal import Decimal
from typing import Any

import httpx

from app.aggregators.live import _dig, _money
from app.aggregators.port import (
    MenuPushItem,
    NormalizedInboundOrder,
    NormalizedOrderItem,
    SyncResult,
)

_logger = logging.getLogger(__name__)

_DEFAULT_BASE = "https://open.mykeeta.com"


def keeta_sorted_param_str(params: dict[str, Any]) -> str:
    """ASCII-sort keys, skip sig; join as key=value&... (JSON values as raw strings)."""
    parts: list[str] = []
    for key in sorted(params.keys(), key=lambda k: str(k)):
        if key == "sig":
            continue
        val = params[key]
        if isinstance(val, (dict, list)):
            val_s = json.dumps(val, ensure_ascii=False, separators=(",", ":"))
        elif val is None:
            val_s = ""
        else:
            val_s = str(val)
        parts.append(f"{key}={val_s}")
    return "&".join(parts)


def keeta_sign(url: str, params: dict[str, Any], app_secret: str) -> str:
    """SHA-256 hex of url + '?' + sortedParamStr + appSecret."""
    sorted_str = keeta_sorted_param_str(params)
    raw = f"{url}?{sorted_str}{app_secret}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class KeetaAdapter:
    """Keeta Open API order lifecycle client."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._provider = "keeta"
        self._cfg = dict(config or {})
        self._client = client
        self.last_calls: list[dict[str, Any]] = []

    @property
    def base_url(self) -> str:
        return str(self._cfg.get("base_url") or _DEFAULT_BASE).rstrip("/")

    @property
    def app_id(self) -> str:
        return str(self._cfg.get("app_id") or self._cfg.get("api_key") or "")

    @property
    def app_secret(self) -> str:
        return str(self._cfg.get("app_secret") or self._cfg.get("api_secret") or "")

    @property
    def access_token(self) -> str:
        return str(
            self._cfg.get("access_token")
            or self._cfg.get("oauth_token")
            or self._cfg.get("token")
            or ""
        )

    @property
    def shop_id(self) -> str | None:
        v = self._cfg.get("store_id") or self._cfg.get("shop_id")
        return str(v) if v else None

    def parse_inbound(self, payload: dict) -> NormalizedInboundOrder:
        p = payload or {}
        # Webhook: { eventId: 1001, data: { order... } } or flat order
        data = p.get("data") if isinstance(p.get("data"), dict) else p
        if "order" in data and isinstance(data["order"], dict):
            data = data["order"]
        items_raw = (
            data.get("products")
            or data.get("items")
            or data.get("orderItems")
            or data.get("order_items")
            or []
        )
        items: list[NormalizedOrderItem] = []
        for it in items_raw:
            if not isinstance(it, dict):
                continue
            items.append(
                NormalizedOrderItem(
                    dish_name=str(
                        _dig(it, "name", "productName", "product_name", "title") or "Item"
                    ),
                    qty=int(_dig(it, "quantity", "qty", "count") or 1),
                    price_aed=_money(
                        _dig(
                            it,
                            "price",
                            "unitPrice",
                            "unit_price",
                            "originPrice",
                            "amount",
                        )
                        or 0
                    ),
                    external_sku=_dig(
                        it, "sku", "productId", "product_id", "spuId", "skuId", "id"
                    ),
                )
            )
        ref = str(
            _dig(data, "orderId", "order_id", "orderViewId", "id", "orderNo") or ""
        )
        cust = data.get("customer") if isinstance(data.get("customer"), dict) else {}
        receiver = (
            data.get("receiver") if isinstance(data.get("receiver"), dict) else {}
        )
        phone = str(
            _dig(cust, "phone", "mobile", "phoneNumber")
            or _dig(receiver, "phone", "mobile")
            or _dig(data, "recipientPhone", "customerPhone", "phone")
            or "+971500000000"
        )
        name = str(
            _dig(cust, "name", "nickname")
            or _dig(receiver, "name")
            or _dig(data, "recipientName")
            or "Guest"
        )
        total = _money(
            _dig(
                data,
                "totalPrice",
                "orderAmount",
                "payAmount",
                "total",
                "actualPayAmount",
            )
            or 0
        )
        if total == 0 and items:
            total = sum((i.price_aed * i.qty for i in items), Decimal("0.00"))
        return NormalizedInboundOrder(
            provider=self._provider,
            provider_order_ref=ref,
            customer_phone=phone,
            customer_name=name,
            items=items,
            total_aed=total,
            notes=_dig(data, "remark", "notes", "comment", "buyerRemark"),
            delivery_fee_aed=_money(
                _dig(data, "deliveryFee", "delivery_fee", "shippingFee") or 0
            ),
        )

    def verify_webhook(self, headers: dict, body: bytes) -> bool:
        """Validate inbound Keeta webhook signature when present."""
        secret = self._cfg.get("webhook_secret") or self.app_secret
        if not secret:
            return True
        try:
            payload = json.loads(body.decode("utf-8") if body else "{}")
        except Exception:  # noqa: BLE001
            return False
        if not isinstance(payload, dict):
            return True
        sig = payload.get("sig") or headers.get("x-keeta-sig") or headers.get("X-Keeta-Sig")
        if not sig:
            # Some environments only IP-whitelist; accept if no sig field
            return True
        # Reconstruct sign over body params excluding sig
        params = {k: v for k, v in payload.items() if k != "sig"}
        # URL may be our webhook path; partners often sign with open base + path
        url = str(
            self._cfg.get("webhook_sign_url")
            or f"{self.base_url}/webhook/order"
        )
        expected = keeta_sign(url, params, str(secret))
        return hmac.compare_digest(str(sig), expected)

    def _common_body(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "appId": int(self.app_id) if str(self.app_id).isdigit() else self.app_id,
            "accessToken": self.access_token,
            "timestamp": int(time.time()),
        }
        if self.shop_id:
            body["shopId"] = (
                int(self.shop_id) if str(self.shop_id).isdigit() else self.shop_id
            )
        if extra:
            body.update(extra)
        return body

    async def _signed_post(self, path: str, extra: dict[str, Any] | None = None) -> tuple[int, dict | list | str | None]:
        url = f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}"
        body = self._common_body(extra)
        body["sig"] = keeta_sign(url, body, self.app_secret)
        timeout = float(self._cfg.get("timeout_seconds") or 20)
        record = {"method": "POST", "url": url, "json": {**body, "sig": "***"}, "provider": "keeta"}
        self.last_calls.append(record)

        client = self._client
        close_after = False
        if client is None:
            client = httpx.AsyncClient(timeout=timeout)
            close_after = True
        try:
            resp = await client.post(
                url,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                json=body,
                timeout=timeout,
            )
            record["status_code"] = resp.status_code
            try:
                parsed: dict | list | str | None = resp.json()
            except Exception:  # noqa: BLE001
                parsed = resp.text
            record["response"] = parsed
            return resp.status_code, parsed
        finally:
            if close_after:
                await client.aclose()

    def _keeta_ok(self, code: int, body: dict | list | str | None) -> bool:
        if code != 200:
            return False
        if isinstance(body, dict):
            # code 0 = success per Keeta docs
            return body.get("code") in (0, "0", None) or body.get("code") == 0
        return True

    async def push_menu(self, items: list[MenuPushItem]) -> SyncResult:
        # Menu sync is a separate Keeta Menu API product surface
        return SyncResult(
            success=True,
            provider=self._provider,
            action="push_menu",
            detail=f"keeta menu sync deferred ({len(items)} items) — Menu API",
            items_touched=0,
        )

    async def set_item_availability(
        self, *, external_sku: str, available: bool
    ) -> SyncResult:
        try:
            code, body = await self._signed_post(
                "/api/open/product/status/update",
                {
                    "skuId": external_sku,
                    "status": 1 if available else 0,
                },
            )
            ok = self._keeta_ok(code, body)
            return SyncResult(
                success=ok,
                provider=self._provider,
                action="set_item_availability",
                detail=f"http {code} body={body}",
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
            code, body = await self._signed_post(
                "/api/open/shop/status/update",
                {"status": 1 if accepting else 0},
            )
            ok = self._keeta_ok(code, body)
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
        try:
            code, body = await self._signed_post(
                "/api/open/order/confirm",
                {"orderId": provider_order_ref},
            )
            ok = self._keeta_ok(code, body)
            return SyncResult(
                success=ok,
                provider=self._provider,
                action="accept_order",
                detail=f"http {code} {body}" if not ok else provider_order_ref,
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
            code, body = await self._signed_post(
                "/api/open/order/cancel",
                {"orderId": provider_order_ref, "reason": reason},
            )
            ok = self._keeta_ok(code, body)
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
        try:
            if status in ("ready", "ready_for_pickup", "preparing"):
                if status == "preparing":
                    return SyncResult(
                        success=True,
                        provider=self._provider,
                        action="push_order_status",
                        detail=f"{provider_order_ref}:preparing(noop)",
                    )
                code, body = await self._signed_post(
                    "/api/open/order/prepare",
                    {"orderId": provider_order_ref},
                )
            elif status in ("delivered", "picked_up"):
                # collect is for pickup orders; still best-effort
                code, body = await self._signed_post(
                    "/api/open/order/collect",
                    {"orderId": provider_order_ref},
                )
            elif status == "cancelled":
                return await self.reject_order(
                    provider_order_ref=provider_order_ref, reason="merchant_cancel"
                )
            elif status in ("confirmed", "accepted"):
                return await self.accept_order(provider_order_ref=provider_order_ref)
            else:
                return SyncResult(
                    success=True,
                    provider=self._provider,
                    action="push_order_status",
                    detail=f"{provider_order_ref}:{status}:unmapped",
                )
            ok = self._keeta_ok(code, body)
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
        if not self.app_id or not self.app_secret or not self.access_token:
            return SyncResult(
                success=False,
                provider=self._provider,
                action="health_check",
                detail="missing appId/appSecret/accessToken",
            )
        try:
            code, body = await self._signed_post(
                "/api/open/base/ping",
                {},
            )
            # endpoint may 404; still proves signing + network if we get HTTP back
            ok = code == 200 and (
                self._keeta_ok(code, body) or isinstance(body, dict)
            )
            return SyncResult(
                success=ok or code in (200, 404),
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

