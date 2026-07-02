#!/usr/bin/env python3
"""Live Phase 0 test: local webhook receiver + API test ping.

Usage (from repo root, API running on :8000):
  .venv/Scripts/python scripts/test_phase0_webhook_live.py

Requires: docker db up, uvicorn on port 8000, APP_OUTBOX_SYNC_DELIVERY=true in .env
so the webhook delivers in-process without Celery.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx

API = os.environ.get("TEST_API_BASE", "http://127.0.0.1:8000")
WEBHOOK_PORT = int(os.environ.get("TEST_WEBHOOK_PORT", "8765"))
SECRET = "phase0-test-secret"

received: list[dict] = []


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        received.append(
            {
                "path": self.path,
                "event": self.headers.get("X-Partner-Event"),
                "idem": self.headers.get("X-Partner-Idempotency-Key"),
                "signature": self.headers.get("X-Partner-Signature"),
                "body": json.loads(body.decode("utf-8")) if body else None,
            }
        )
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def main() -> int:
    server = HTTPServer(("127.0.0.1", WEBHOOK_PORT), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    webhook_url = f"http://127.0.0.1:{WEBHOOK_PORT}/hooks/whatsapp"
    phone = f"+97150{int(time.time()) % 10000000:07d}"

    with httpx.Client(base_url=API, timeout=30.0) as client:
        print(f"1. Signup restaurant {phone}...")
        r = client.post(
            "/api/v1/auth/signup",
            json={
                "name": "Phase0 Test Kitchen",
                "phone": phone,
                "password": "testpass123!",
                "lat": 25.2048,
                "lng": 55.2708,
            },
        )
        if r.status_code not in (200, 201, 409):
            print("Signup failed:", r.status_code, r.text)
            return 1

        print("2. Login...")
        token = client.post(
            "/api/v1/auth/login",
            json={"phone": phone, "password": "testpass123!"},
        ).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        print(f"3. Configure webhook → {webhook_url}")
        r = client.patch(
            "/api/v1/partner-integration/config",
            headers=headers,
            json={
                "partner_enabled": True,
                "partner_webhook_url": webhook_url,
                "partner_webhook_secret": SECRET,
                "pos_store_id": "TEST-PHASE0",
            },
        )
        print("   config:", r.status_code, r.json())

        print("4. Send test webhook...")
        r = client.post("/api/v1/partner-integration/webhooks/test", headers=headers)
        print("   test:", r.status_code, r.json())
        if r.status_code != 200 or not r.json().get("queued"):
            return 1

        print("5. Wait for delivery...")
        for _ in range(20):
            time.sleep(0.25)
            if received:
                break

    server.shutdown()

    if not received:
        print("FAIL: webhook receiver got nothing.")
        print("Tip: set APP_OUTBOX_SYNC_DELIVERY=true in .env and restart uvicorn.")
        return 1

    hit = received[0]
    print("6. Received webhook:")
    print(json.dumps(hit, indent=2))
    assert hit["event"] == "integration.ping"
    assert hit["signature"] and hit["signature"].startswith("sha256=")
    assert hit["body"]["event"] == "integration.ping"
    print("\nPASS — Phase 0 live webhook test OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())