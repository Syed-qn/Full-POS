# Load / Stress Harness

Simulates peak-hour traffic for the WhatsApp restaurant platform.

`locust` is a **dev-only** dependency (`[project.optional-dependencies] dev`).
It is never imported by app or test code.

## SLOs (pass/fail gates)

| Metric                         | Target                         |
|--------------------------------|--------------------------------|
| Webhook p95 latency            | < 250 ms                       |
| Webhook error rate (5xx)       | < 0.5 %                        |
| /auth/login p95                | < 400 ms (argon2 cost)         |
| Dashboard GET /orders p95      | < 300 ms                       |
| Outbox delivery throughput     | ≥ 50 msg/s (mock provider)     |
| Sustained RPS without 5xx      | ≥ 200 RPS for 5 min            |

These bound the operational headroom needed to keep the 40-min customer SLA
(internal 30-min target) under realistic burst load.

## Traffic shapes

The locustfile defines three weighted user classes:

| User class          | Weight | Simulates                                            |
|---------------------|:------:|------------------------------------------------------|
| `WebhookBurstUser`  | 5      | Meta delivering inbound messages in peak-hour bursts |
| `DashboardPollUser` | 2      | Manager dashboard polling live order/rider state     |
| `SendFloodUser`     | 1      | Inbound flood that fans out to the outbound outbox   |

## Run

1. Start the stack: `docker compose up -d` + `uvicorn app.main:app --port 8000`.
2. Seed a manager + menu (see `scripts/seed_demo.py`).
3. Export the credentials/secrets the harness reads:
   - `LOAD_MANAGER_PHONE`, `LOAD_MANAGER_PASSWORD` (required by `DashboardPollUser`)
   - `APP_WHATSAPP_APP_SECRET` (optional — when set, webhook payloads are HMAC-signed)
4. `.venv/bin/locust -f load/locustfile.py --host http://localhost:8000`
5. Open http://localhost:8089, set users/spawn rate, run.
6. Compare the Locust stats table + `/metrics` (`outbox_deliveries_total`,
   `http_request_duration_seconds` histogram) against the SLO table above.

### Headless smoke (30 s)

```bash
.venv/bin/locust -f load/locustfile.py --host http://localhost:8000 \
  --headless -u 20 -r 5 -t 30s
```

Confirm non-zero requests and no Locust import/usage errors. This is **not** a
CI gate — it needs a running server. Record observed p95 vs the SLO table in
`understanding.txt`.

## Signed webhooks

The webhook verifies `X-Hub-Signature-256`. To load-test the real path, export
`APP_WHATSAPP_APP_SECRET`; the harness then computes
`hmac_sha256(app_secret, body)` per request and adds the header automatically
(see `_sign()` in `locustfile.py` — same algorithm as the `signed_webhook_payload`
test helper).

For pure capacity testing of the ASGI layer, leave `APP_WHATSAPP_APP_SECRET`
unset and point at a dev instance running with
`APP_WHATSAPP_VERIFY_SIGNATURE=false`. **Production must keep signature
verification on** — the toggle exists only for raw-capacity load testing and is
flagged in the deployment doc and secrets/config audit.
