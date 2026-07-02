#!/usr/bin/env python3
"""Temp POS — a standalone fake POS partner you can run to test the integration.

Unlike simulate_pos_lifecycle.py (which drives everything in-process), THIS is a
real external POS: a long-running HTTP server that

  1. RECEIVES your outbound webhooks — verifies the HMAC signature and
     pretty-prints every event (order.created, rider_assigned, picked_up,
     delivered, late, integration.ping).
  2. ACTS as the POS kitchen — when an ``order.created`` arrives it calls your
     API (with X-API-Key) to ack the order, then mark it preparing, then ready
     (which fires dispatch). Toggle with POS_AUTO_ADVANCE=false to just watch.

It points at whatever platform you configure — your local uvicorn or the live
Render deployment.

--------------------------------------------------------------------------------
USAGE
--------------------------------------------------------------------------------
Set these env vars (see defaults below), then run:
  .venv/Scripts/python scripts/temp_pos.py

  POS_BASE_URL        platform API base (default http://127.0.0.1:8000)
  POS_API_KEY         your X-API-Key for that store (required to auto-advance)
  POS_WEBHOOK_SECRET  shared HMAC secret you set in the store's partner config
  POS_PORT            local port this receiver listens on (default 8799)
  POS_AUTO_ADVANCE    "true" (default) = auto ack+preparing+ready on order.created

Then point the store's ``partner_webhook_url`` at this server's URL:
  * Local platform  -> http://127.0.0.1:8799/hooks/whatsapp
  * Live/Render     -> expose this port publicly first (e.g. `ngrok http 8799`)
                       and use the https ngrok URL, because Render can't reach
                       your localhost.

To generate an order to test with, place a real WhatsApp order on that store
(orders only originate from the customer channel — the POS cannot create them).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx

BASE_URL = os.environ.get("POS_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
API_KEY = os.environ.get("POS_API_KEY", "")
SECRET = os.environ.get("POS_WEBHOOK_SECRET", "")
PORT = int(os.environ.get("POS_PORT", "8799"))
AUTO_ADVANCE = os.environ.get("POS_AUTO_ADVANCE", "true").lower() == "true"


def _verify(raw: bytes, header: str | None) -> bool:
    """True if the X-Partner-Signature matches our shared secret (or no secret set)."""
    if not SECRET:
        return True  # not checking — secret not configured on this receiver
    if not header or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


def _api_post(path: str, body: dict) -> None:
    """Call the platform partner API as the POS (X-API-Key)."""
    if not API_KEY:
        print("      ! POS_API_KEY not set — cannot call back, skipping.")
        return
    try:
        r = httpx.post(
            f"{BASE_URL}{path}",
            headers={"X-API-Key": API_KEY},
            json=body,
            timeout=30.0,
        )
        print(f"      -> POST {path} {body}  =>  HTTP {r.status_code} {r.text[:200]}")
    except Exception as exc:  # noqa: BLE001 - surface any transport error
        print(f"      ! POST {path} failed: {exc}")


def _drive_kitchen(order_id: int) -> None:
    """Behave like the POS kitchen: ack -> preparing -> ready (fires dispatch)."""
    print(f"      [auto] acting as kitchen for order {order_id}")
    _api_post(f"/api/v1/partner/orders/{order_id}/ack", {"pos_order_id": f"TEMP-POS-{order_id}"})
    _api_post(f"/api/v1/partner/orders/{order_id}/status", {"status": "preparing"})
    _api_post(f"/api/v1/partner/orders/{order_id}/status", {"status": "ready"})


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        sig = self.headers.get("X-Partner-Signature")
        event = self.headers.get("X-Partner-Event", "?")
        ok = _verify(raw, sig)

        # Always 2xx quickly (real POS must return within 5s), then process.
        self.send_response(200 if ok else 401)
        self.end_headers()
        self.wfile.write(b"ok" if ok else b"bad signature")

        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:  # noqa: BLE001
            body = {"_raw": raw.decode("utf-8", "replace")}
        data = body.get("data", {}) if isinstance(body, dict) else {}

        badge = "HMAC ok" if ok else "BAD SIGNATURE"
        print(f"\n<< received {event}  [{badge}]  idem={body.get('idempotency_key')}")
        print(json.dumps(data, indent=2)[:1500])

        if not ok:
            return
        if event == "order.created" and AUTO_ADVANCE:
            oid = data.get("order_id")
            if oid is not None:
                _drive_kitchen(int(oid))

    def log_message(self, *args) -> None:  # noqa: A003 - silence default logging
        return


def main() -> None:
    print("=" * 64)
    print("TEMP POS — fake POS partner")
    print(f"  platform API : {BASE_URL}")
    print(f"  receiver     : http://127.0.0.1:{PORT}/hooks/whatsapp")
    print(f"  api key      : {'set' if API_KEY else 'NOT SET (cannot auto-advance)'}")
    print(f"  hmac secret  : {'set (verifying)' if SECRET else 'NOT SET (not verifying)'}")
    print(f"  auto-advance : {AUTO_ADVANCE}")
    print("=" * 64)
    print("Point the store's partner_webhook_url at this receiver, then place a")
    print("WhatsApp order on that store. Ctrl+C to stop.\n")
    HTTPServer(("0.0.0.0", PORT), _Handler).serve_forever()


if __name__ == "__main__":
    main()
