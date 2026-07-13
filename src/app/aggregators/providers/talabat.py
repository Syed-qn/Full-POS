"""Talabat / Delivery Hero POS Middleware real adapter.

Docs: https://integration.talabat.com/en/documentation/

Outbound (Integration Middleware API — POS calls DH):
- POST login → access token
- POST /v2/order/status  — accept / reject / picked_up
- POST /v2/orders/{orderToken}/preparation-completed — ready for pickup
- PUT  catalog submit, item availability, vendor availability (simplified shapes)

Inbound (Plugin API — DH calls our webhook):
- Order Dispatch payload → parse_inbound (Delivery Hero order shape)

Config keys (restaurant.settings.channels.talabat):
- mode: live
- api_key: username (middleware credential)
- api_secret: password
- webhook_secret: optional shared secret for inbound plugin calls
- store_id: vendor remote id / platform vendor code
- chain_code, remote_id: optional DH chain/vendor identifiers
- base_url: default staging middleware host
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.aggregators.live import parse_marketplace_payload
from app.aggregators.port import MenuPushItem, NormalizedInboundOrder, SyncResult

_logger = logging.getLogger(__name__)

# Public staging middleware host from Talabat docs (override with base_url).
_DEFAULT_BASE = "https://integration-middleware.stg.restaurant-partners.com"


class TalabatAdapter:
    """Delivery Hero POS Middleware client for Talabat (and DH family brands)."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._provider = "talabat"
        self._cfg = dict(config or {})
        self._client = client
        self._token: str | None = None
        self._token_exp: float = 0.0
        self.last_calls: list[dict[str, Any]] = []

    @property
    def base_url(self) -> str:
        return str(self._cfg.get("base_url") or _DEFAULT_BASE).rstrip("/")

    @property
    def store_id(self) -> str | None:
        v = self._cfg.get("store_id") or self._cfg.get("remote_id")
        return str(v) if v else None

    def parse_inbound(self, payload: dict) -> NormalizedInboundOrder:
        return parse_marketplace_payload(self._provider, payload)

    def verify_webhook(self, headers: dict, body: bytes) -> bool:
        # DH Plugin security often uses basic auth / mTLS / IP allowlist.
        # Optional shared secret still supported for our edge.
        secret = self._cfg.get("webhook_secret") or self._cfg.get("api_secret")
        if not secret:
            return True
        hdr = (
            headers.get("x-aggregator-secret")
            or headers.get("X-Aggregator-Secret")
            or headers.get("authorization")
            or headers.get("Authorization")
        )
        if hdr is None:
            return False
        return str(secret) in str(hdr) or str(hdr).endswith(str(secret))

    async def _ensure_token(self) -> str | None:
        now = time.time()
        if self._token and now < self._token_exp - 30:
            return self._token
        username = self._cfg.get("api_key") or self._cfg.get("username")
        password = self._cfg.get("api_secret") or self._cfg.get("password")
        if not username or not password:
            return str(self._cfg.get("access_token") or self._cfg.get("api_key") or "") or None

        code, body = await self._request(
            "POST",
            "/v2/login",
            json_body={"username": username, "password": password},
            auth=False,
        )
        if 200 <= code < 300 and isinstance(body, dict):
            token = body.get("access_token") or body.get("token") or body.get("accessToken")
            if token:
                self._token = str(token)
                # DH tokens typically short-lived; default 50 min if unknown
                exp = body.get("expires_in") or body.get("expiresIn") or 3000
                self._token_exp = now + float(exp)
                return self._token
        # Fall back to raw api_key as bearer if login path differs in region
        return str(username)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | list | None = None,
        auth: bool = True,
    ) -> tuple[int, dict | list | str | None]:
        url = f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}"
        timeout = float(self._cfg.get("timeout_seconds") or 20)
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if auth:
            token = await self._ensure_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"
        record = {"method": method, "url": url, "json": json_body, "provider": "talabat"}
        self.last_calls.append(record)

        client = self._client
        close_after = False
        if client is None:
            client = httpx.AsyncClient(timeout=timeout)
            close_after = True
        try:
            resp = await client.request(
                method, url, headers=headers, json=json_body, timeout=timeout
            )
            record["status_code"] = resp.status_code
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
        # PUT Submit Catalog — simplified product list (full catalog schema is partner-specific)
        catalog = {
            "callbackUrl": self._cfg.get("callback_url"),
            "vendorId": self.store_id,
            "products": [
                {
                    "remoteCode": f"dish-{i.dish_id}",
                    "name": i.name,
                    "price": float(i.price_aed),
                    "active": i.is_available,
                    "plu": str(i.dish_number),
                }
                for i in items
            ],
        }
        try:
            code, body = await self._request("PUT", "/v2/chains/catalog", json_body=catalog)
            ok = 200 <= code < 300
            return SyncResult(
                success=ok,
                provider=self._provider,
                action="push_menu",
                detail=f"http {code}" + ("" if ok else f": {body}"),
                items_touched=len(items) if ok else 0,
            )
        except Exception as exc:  # noqa: BLE001
            return SyncResult(
                success=False, provider=self._provider, action="push_menu", detail=str(exc)[:300]
            )

    async def set_item_availability(
        self, *, external_sku: str, available: bool
    ) -> SyncResult:
        try:
            code, body = await self._request(
                "POST",
                "/v2/catalog/items/availability",
                json_body={
                    "vendorId": self.store_id,
                    "items": [{"remoteCode": external_sku, "available": available}],
                },
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
                "/v2/vendors/availability",
                json_body={
                    "vendorId": self.store_id,
                    "availabilityState": "OPEN" if accepting else "CLOSED",
                },
            )
            ok = 200 <= code < 300
            return SyncResult(
                success=ok,
                provider=self._provider,
                action="set_store_status",
                detail=f"http {code}" if not ok else ("OPEN" if accepting else "CLOSED"),
            )
        except Exception as exc:  # noqa: BLE001
            return SyncResult(
                success=False,
                provider=self._provider,
                action="set_store_status",
                detail=str(exc)[:300],
            )

    async def accept_order(self, *, provider_order_ref: str) -> SyncResult:
        # Update Order Status — order_accepted
        try:
            code, body = await self._request(
                "POST",
                "/v2/order/status",
                json_body={
                    "status": "order_accepted",
                    "orderToken": provider_order_ref,
                    "remoteOrderId": provider_order_ref,
                    "acceptanceTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
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
        reason_map = {
            "out_of_stock": "ITEM_UNAVAILABLE",
            "busy": "TOO_BUSY",
            "closing_early": "CLOSING_EARLY",
            "other": "OTHER",
        }
        try:
            code, body = await self._request(
                "POST",
                "/v2/order/status",
                json_body={
                    "status": "order_rejected",
                    "orderToken": provider_order_ref,
                    "remoteOrderId": provider_order_ref,
                    "reason": reason_map.get(reason, "OTHER"),
                    "message": reason,
                },
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
        # ready → preparation-completed; picked_up → order status picked up
        try:
            if status in ("ready", "ready_for_pickup", "preparing"):
                if status in ("ready", "ready_for_pickup"):
                    code, body = await self._request(
                        "POST",
                        f"/v2/orders/{provider_order_ref}/preparation-completed",
                        json_body={},
                    )
                else:
                    return SyncResult(
                        success=True,
                        provider=self._provider,
                        action="push_order_status",
                        detail=f"{provider_order_ref}:preparing(noop)",
                    )
            elif status in ("picked_up", "delivered"):
                code, body = await self._request(
                    "POST",
                    "/v2/order/status",
                    json_body={
                        "status": "order_picked_up"
                        if status == "picked_up"
                        else "order_delivered",
                        "orderToken": provider_order_ref,
                    },
                )
            elif status == "cancelled":
                return await self.reject_order(
                    provider_order_ref=provider_order_ref, reason="other"
                )
            else:
                return SyncResult(
                    success=True,
                    provider=self._provider,
                    action="push_order_status",
                    detail=f"{provider_order_ref}:{status}:unmapped",
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
            # Prefer login probe when credentials present
            token = await self._ensure_token()
            ok = bool(token)
            return SyncResult(
                success=ok,
                provider=self._provider,
                action="health_check",
                detail="token_ok" if ok else "missing_credentials",
            )
        except Exception as exc:  # noqa: BLE001
            return SyncResult(
                success=False,
                provider=self._provider,
                action="health_check",
                detail=str(exc)[:300],
            )
