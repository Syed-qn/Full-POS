"""Uber Eats Marketplace Order API real adapter.

Docs:
- https://developer.uber.com/docs/eats
- Accept: POST /v1/eats/orders/{order_id}/accept_pos_order → 204
- Deny:   POST /v1/eats/orders/{order_id}/deny_pos_order
- Order:  GET  /v2/eats/order/{order_id}
- Store:  POST /v1/eats/stores/{store_id}/status
- Auth:   OAuth2 client_credentials → auth.uber.com/oauth/v2/token
- Webhook: X-Uber-Signature = HMAC-SHA256(body, client_secret) lowercase hex

Config (channels.ubereats):
- mode: live
- api_key: client_id
- api_secret: client_secret
- store_id: Uber Eats store UUID
- access_token: optional pre-issued bearer (skips OAuth when set)
- oauth_url: default https://auth.uber.com/oauth/v2/token
- base_url: default https://api.uber.com
- scope: default "eats.order eats.store eats.store.status.write"
- webhook_secret: same as client_secret for X-Uber-Signature
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import httpx

from app.aggregators.live import _dig, _money, parse_marketplace_payload
from app.aggregators.port import (
    MenuPushItem,
    NormalizedInboundOrder,
    NormalizedOrderItem,
    SyncResult,
)

_logger = logging.getLogger(__name__)

_DEFAULT_BASE = "https://api.uber.com"
_DEFAULT_OAUTH = "https://auth.uber.com/oauth/v2/token"
_DEFAULT_SCOPE = "eats.order eats.store eats.store.status.write"


class UberEatsAdapter:
    """Uber Eats order manager adapter (POS integration)."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._provider = "ubereats"
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
        v = self._cfg.get("store_id") or self._cfg.get("eats_store_id")
        return str(v) if v else None

    def parse_inbound(self, payload: dict) -> NormalizedInboundOrder:
        p = payload or {}
        # Thin notification: fetch path is resource_href / meta.resource_id
        event = str(p.get("event_type") or p.get("event") or p.get("type") or "").lower()
        if "orders.notification" in event or event == "orders.notification":
            meta = p.get("meta") if isinstance(p.get("meta"), dict) else {}
            rid = str(
                _dig(meta, "resource_id", "order_id")
                or _dig(p, "resource_id", "order_id")
                or ""
            )
            # Notification alone has no cart — synthesize minimal order for ack pipeline.
            if rid:
                return NormalizedInboundOrder(
                    provider=self._provider,
                    provider_order_ref=rid,
                    customer_phone="+971500000000",
                    customer_name="Guest",
                    items=[
                        NormalizedOrderItem(
                            dish_name="Uber Eats order (fetch details)",
                            qty=1,
                            price_aed=Decimal("0.00"),
                            external_sku=rid,
                        )
                    ],
                    total_aed=Decimal("0.00"),
                    notes="orders.notification — call GET /v2/eats/order/{id} for cart",
                )
        # Full order payload (cart)
        cart = p.get("cart") if isinstance(p.get("cart"), dict) else None
        if cart or "current_state" in p or "display_id" in p:
            return self._parse_full_order(p)
        order = p.get("order") if isinstance(p.get("order"), dict) else None
        if order:
            return self._parse_full_order(order)
        try:
            return parse_marketplace_payload(self._provider, p)
        except ValueError:
            raise

    def _parse_full_order(self, order: dict) -> NormalizedInboundOrder:
        items: list[NormalizedOrderItem] = []
        cart = order.get("cart") if isinstance(order.get("cart"), dict) else order
        items_raw = (
            cart.get("items")
            or cart.get("line_items")
            or order.get("items")
            or []
        )
        for it in items_raw:
            if not isinstance(it, dict):
                continue
            price = _dig(it, "price", "unit_price", "price_info")
            if isinstance(price, dict):
                # Uber often uses price in minor units under price / unit_price.amount
                price = _dig(price, "unit_price", "amount", "value", "price") or 0
                try:
                    pv = Decimal(str(price))
                    # minor units (cents) when large
                    if pv >= 100 and pv == pv.to_integral_value():
                        price = (pv / Decimal("100")).quantize(Decimal("0.01"))
                    else:
                        price = pv.quantize(Decimal("0.01"))
                except Exception:  # noqa: BLE001
                    price = 0
            title = _dig(it, "title", "name", "external_data") or "Item"
            if isinstance(title, dict):
                title = _dig(title, "translations", "en", "default") or "Item"
            items.append(
                NormalizedOrderItem(
                    dish_name=str(title),
                    qty=int(_dig(it, "quantity", "qty") or 1),
                    price_aed=_money(price or 0),
                    external_sku=_dig(it, "id", "external_data", "sku", "plu"),
                )
            )
        ref = str(
            _dig(order, "id", "order_id", "uuid", "resource_id")
            or _dig(order, "meta", "resource_id")
            or ""
        )
        eater = order.get("eater") if isinstance(order.get("eater"), dict) else {}
        cust = order.get("customer") if isinstance(order.get("customer"), dict) else eater
        phone = str(
            _dig(cust, "phone", "phone_code", "mobile")
            or _dig(eater, "phone")
            or "+971500000000"
        )
        name = str(
            _dig(cust, "first_name", "name", "firstName")
            or "Guest"
        )
        payment = order.get("payment") if isinstance(order.get("payment"), dict) else {}
        total = Decimal("0.00")
        charges = payment.get("charges") if isinstance(payment.get("charges"), dict) else {}
        t = charges.get("total")
        if isinstance(t, dict):
            raw_t = _dig(t, "amount", "value", "price") or 0
            try:
                tv = Decimal(str(raw_t))
                if tv >= 100 and tv == tv.to_integral_value():
                    total = (tv / Decimal("100")).quantize(Decimal("0.01"))
                else:
                    total = tv.quantize(Decimal("0.01"))
            except Exception:  # noqa: BLE001
                total = Decimal("0.00")
        elif t is not None:
            total = _money(t)
        if total == 0:
            raw = _dig(order, "total", "order_total", "total_aed")
            if raw is not None and not isinstance(raw, dict):
                total = _money(raw)
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
                    dish_name="Uber Eats order",
                    qty=1,
                    price_aed=Decimal("0.00"),
                )
            ],
            total_aed=total,
            notes=_dig(order, "special_instructions", "notes", "comment"),
            delivery_fee_aed=_money(_dig(order, "delivery_fee") or 0),
        )

    def verify_webhook(self, headers: dict, body: bytes) -> bool:
        secret = (
            self._cfg.get("webhook_secret")
            or self._cfg.get("api_secret")
            or self._cfg.get("client_secret")
        )
        if not secret:
            return True
        sig = (
            headers.get("x-uber-signature")
            or headers.get("X-Uber-Signature")
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
        return hmac.compare_digest(digest.lower(), sig.lower())

    async def _ensure_token(self) -> str:
        pre = self._cfg.get("access_token") or self._cfg.get("bearer_token")
        if pre:
            return str(pre)
        now = time.time()
        if self._token and now < self._token_exp - 60:
            return self._token
        client_id = self._cfg.get("api_key") or self._cfg.get("client_id")
        client_secret = self._cfg.get("api_secret") or self._cfg.get("client_secret")
        if not client_id or not client_secret:
            raise RuntimeError("ubereats OAuth requires api_key (client_id) and api_secret")

        oauth_url = str(self._cfg.get("oauth_url") or _DEFAULT_OAUTH)
        scope = str(self._cfg.get("scope") or _DEFAULT_SCOPE)
        form = {
            "client_id": str(client_id),
            "client_secret": str(client_secret),
            "grant_type": "client_credentials",
            "scope": scope,
        }
        timeout = float(self._cfg.get("timeout_seconds") or 20)
        record = {"method": "POST", "url": oauth_url, "json": {"grant_type": "client_credentials"}}
        self.last_calls.append(record)

        client = self._client
        close_after = False
        if client is None:
            client = httpx.AsyncClient(timeout=timeout)
            close_after = True
        try:
            resp = await client.request(
                "POST",
                oauth_url,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                content=urlencode(form),
                timeout=timeout,
            )
            record["status_code"] = resp.status_code
            body = resp.json() if resp.content else {}
            record["response"] = body
            if resp.status_code >= 400:
                raise RuntimeError(f"ubereats oauth http {resp.status_code}: {body}")
            token = body.get("access_token")
            if not token:
                raise RuntimeError("ubereats oauth missing access_token")
            self._token = str(token)
            exp = float(body.get("expires_in") or 86400)
            self._token_exp = now + exp
            return self._token
        finally:
            if close_after:
                await client.aclose()

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | list | None = None,
    ) -> tuple[int, dict | list | str | None]:
        token = await self._ensure_token()
        url = f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}"
        timeout = float(self._cfg.get("timeout_seconds") or 20)
        record = {"method": method, "url": url, "json": json_body, "provider": "ubereats"}
        self.last_calls.append(record)
        client = self._client
        close_after = False
        if client is None:
            client = httpx.AsyncClient(timeout=timeout)
            close_after = True
        try:
            resp = await client.request(
                method, url, headers=self._headers(token), json=json_body, timeout=timeout
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
        if not self.store_id:
            return SyncResult(
                success=False,
                provider=self._provider,
                action="push_menu",
                detail="store_id required for Uber menu PUT",
            )
        # Simplified MenuConfiguration — full catalog mapping is partner-specific.
        payload = {
            "menus": [
                {
                    "id": "main",
                    "title": {"translations": {"en": "Main"}},
                    "service_availability": [],
                    "category_ids": ["cat-all"],
                }
            ],
            "categories": [
                {
                    "id": "cat-all",
                    "title": {"translations": {"en": "All"}},
                    "entities": [{"id": f"dish-{i.dish_id}"} for i in items],
                }
            ],
            "items": [
                {
                    "id": f"dish-{i.dish_id}",
                    "title": {"translations": {"en": i.name}},
                    "price_info": {"price": int(Decimal(str(i.price_aed)) * 100)},
                    "external_data": str(i.dish_number),
                    "suspension_info": None if i.is_available else {"suspension": {}},
                }
                for i in items
            ],
            "modifier_groups": [],
            "display_options": {},
        }
        try:
            code, body = await self._request(
                "PUT",
                f"/v2/eats/stores/{self.store_id}/menus",
                json_body=payload,
            )
            ok = 200 <= code < 300 or code == 204
            return SyncResult(
                success=ok,
                provider=self._provider,
                action="push_menu",
                detail=f"http {code}" + ("" if ok else f": {body}"),
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
        if not self.store_id:
            return SyncResult(
                success=False,
                provider=self._provider,
                action="set_item_availability",
                detail="store_id required",
            )
        try:
            body: dict[str, Any] = {}
            if not available:
                body["suspension_info"] = {
                    "suspension": {"suspend_until": int(time.time()) + 86400 * 30}
                }
            else:
                body["suspension_info"] = None
            code, resp = await self._request(
                "POST",
                f"/v2/eats/stores/{self.store_id}/menus/items/{external_sku}",
                json_body=body,
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
        if not self.store_id:
            return SyncResult(
                success=False,
                provider=self._provider,
                action="set_store_status",
                detail="store_id required",
            )
        try:
            code, body = await self._request(
                "POST",
                f"/v1/eats/stores/{self.store_id}/status",
                json_body={"status": "ONLINE" if accepting else "PAUSED"},
            )
            ok = 200 <= code < 300 or code == 204
            return SyncResult(
                success=ok,
                provider=self._provider,
                action="set_store_status",
                detail=f"http {code}" if not ok else ("ONLINE" if accepting else "PAUSED"),
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
                f"/v1/eats/orders/{provider_order_ref}/accept_pos_order",
                json_body={
                    "reason": "Accepted by POS",
                    "fields_relayed": {
                        "order_special_instructions": True,
                        "item_special_instructions": True,
                        "promotions": True,
                    },
                },
            )
            ok = code == 204 or 200 <= code < 300
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
                f"/v1/eats/orders/{provider_order_ref}/deny_pos_order",
                json_body={
                    "deny_reason": {
                        "info": reason,
                        "type": "ITEM_ISSUE" if "stock" in reason.lower() else "OTHER",
                    }
                },
            )
            ok = code == 204 or 200 <= code < 300
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
        # Uber ready/pickup paths vary by integration tier; log best-effort.
        mapped = (status or "").lower()
        if mapped in ("ready", "ready_for_pickup", "prepared"):
            detail = f"ubereats ready signal for {provider_order_ref} (partner-tier endpoint)"
            return SyncResult(
                success=True,
                provider=self._provider,
                action="push_order_status",
                detail=detail,
            )
        return SyncResult(
            success=True,
            provider=self._provider,
            action="push_order_status",
            detail=f"ubereats status '{status}' acknowledged locally for {provider_order_ref}",
        )

    async def health_check(self) -> SyncResult:
        try:
            if self.store_id:
                code, body = await self._request(
                    "GET", f"/v1/eats/stores/{self.store_id}"
                )
            else:
                # Token probe via accept of empty fails; use oauth only
                await self._ensure_token()
                return SyncResult(
                    success=True,
                    provider=self._provider,
                    action="health_check",
                    detail="oauth token ok",
                )
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
