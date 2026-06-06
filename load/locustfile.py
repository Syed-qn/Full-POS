"""Peak-hour load profile. Run against a LOCAL stack only:

    .venv/bin/locust -f load/locustfile.py --host http://localhost:8000

DEV-ONLY: never imported by app or tests.

Simulates the three real traffic shapes for the WhatsApp restaurant platform:
  * WebhookBurstUser   — Meta delivering inbound messages in peak-hour bursts.
  * DashboardPollUser  — manager dashboard polling live order/rider state.
  * SendFloodUser      — outbound send flood exercising the outbox path.

See load/README.md for the SLO table and run instructions.
"""

import hashlib
import hmac
import json
import os
import time

from locust import HttpUser, between, task

# Optional app secret — when set, inbound webhook payloads are HMAC-signed with
# X-Hub-Signature-256 so the real verification path is exercised. When unset,
# payloads are posted unsigned (point at a dev instance running with
# APP_WHATSAPP_VERIFY_SIGNATURE=false to capacity-test the raw ASGI layer).
_APP_SECRET = os.environ.get("APP_WHATSAPP_APP_SECRET", "")


def _sign(body: bytes) -> dict[str, str]:
    """Return signature headers for a webhook body (empty if no app secret)."""
    if not _APP_SECRET:
        return {}
    digest = hmac.new(_APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return {"X-Hub-Signature-256": "sha256=" + digest}


class WebhookBurstUser(HttpUser):
    """Simulates Meta delivering inbound messages in peak-hour bursts."""

    weight = 5
    wait_time = between(0.1, 0.5)

    @task
    def inbound_message(self):
        now_ns = time.time_ns()
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "+9715000000{:02d}".format(
                                            int(time.time()) % 100
                                        ),
                                        "id": "wamid.load-{}".format(now_ns),
                                        "timestamp": str(int(time.time())),
                                        "type": "text",
                                        "text": {"body": "1"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ],
        }
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json", **_sign(body)}
        # Against a dev stack with signature check relaxed
        # (APP_WHATSAPP_VERIFY_SIGNATURE=false), post unsigned and expect
        # 200/4xx accordingly. With APP_WHATSAPP_APP_SECRET exported the body
        # is signed and the real HMAC path is exercised.
        self.client.post(
            "/webhooks/whatsapp",
            data=body,
            headers=headers,
            name="POST /webhooks/whatsapp",
        )


class DashboardPollUser(HttpUser):
    """Manager dashboard polling live order/rider state."""

    weight = 2
    wait_time = between(1, 3)

    def on_start(self):
        # Acquire a manager token via /auth/login using seeded creds from env.
        creds = {
            "phone": os.environ["LOAD_MANAGER_PHONE"],
            "password": os.environ["LOAD_MANAGER_PASSWORD"],
        }
        r = self.client.post(
            "/api/v1/auth/login", json=creds, name="POST /auth/login"
        )
        self._auth = (
            {"Authorization": "Bearer " + r.json()["access_token"]}
            if r.ok
            else {}
        )

    @task(3)
    def poll_orders(self):
        self.client.get(
            "/api/v1/orders?status=active",
            headers=self._auth,
            name="GET /orders",
        )

    @task(1)
    def health(self):
        self.client.get("/health", name="GET /health")


class SendFloodUser(HttpUser):
    """Outbound send flood — drives inbound traffic that fans out to the outbox.

    There is no public 'send' endpoint (sends originate from the conversation
    engine and drain via the Celery outbox worker). To stress the outbound
    path we flood inbound messages that trigger replies, then observe
    outbox_deliveries_total throughput on /metrics against the SLO table.
    """

    weight = 1
    wait_time = between(0.2, 0.6)

    @task
    def trigger_reply(self):
        now_ns = time.time_ns()
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "+9715111111{:02d}".format(
                                            int(time.time()) % 100
                                        ),
                                        "id": "wamid.send-{}".format(now_ns),
                                        "timestamp": str(int(time.time())),
                                        "type": "text",
                                        "text": {"body": "hi"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ],
        }
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json", **_sign(body)}
        self.client.post(
            "/webhooks/whatsapp",
            data=body,
            headers=headers,
            name="POST /webhooks/whatsapp [send flood]",
        )
