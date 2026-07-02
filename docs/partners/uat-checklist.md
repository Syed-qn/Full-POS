# Partner Integration — End-to-End UAT Checklist

Use this checklist before handing off to a POS engineering team. Run against the
partner sandbox (`scripts/seed_partner_sandbox.py`) or a staging store.

## Prerequisites

- [ ] Docker Postgres + Redis running (`docker compose up -d`)
- [ ] API running (`uvicorn app.main:app --reload --port 8000`)
- [ ] Partner sandbox seeded (`python scripts/seed_partner_sandbox.py`)
- [ ] Webhook receiver running (`python scripts/test_phase0_webhook_live.py`) OR POS endpoint configured
- [ ] `APP_OUTBOX_SYNC_DELIVERY=true` for in-process webhook delivery (no Celery worker)

## Critical path (OPS engine)

- [ ] **Menu push** — `PUT /api/v1/partner/menu/items` → item appears on WhatsApp catalog
- [ ] **Customer orders** — WhatsApp confirm → POS receives `order.created` webhook (or poll `GET /partner/orders`)
- [ ] **POS ack** — `POST /partner/orders/{id}/ack` → `pos_order_id` stored on order
- [ ] **POS preparing** — `POST /partner/orders/{id}/status` `{status: preparing}` → customer WhatsApp ping
- [ ] **POS ready** — `{status: ready}` → rider app push + dispatch assignment
- [ ] **Rider pickup** — rider taps pickup → POS gets `order.picked_up` webhook
- [ ] **Rider delivered** — rider taps delivered → POS gets `order.delivered` + `cod_collected`
- [ ] **Dashboard parity** — same order state on dispatch map (no drift vs POS)
- [ ] **POS-only ops** — restaurant never needs manager dashboard for daily flow

## Supporting flows

- [ ] **Menu patch** — `PATCH /partner/menu/items/{pos_id}` sold-out / price change
- [ ] **Menu pull signal** — `POST /partner/events/menu-changed` queues full POS pull
- [ ] **Delivery poll** — `GET /partner/orders/{id}/delivery` matches webhook payload
- [ ] **Rider location** — `GET /partner/riders/{id}/location` returns latest GPS
- [ ] **SLA late** — order past 40 min → `order.late` webhook with coupon code
- [ ] **Cancel** — `POST /partner/orders/{id}/status` `{status: cancelled}` before ready

## Security

- [ ] Revoked API key returns **401** immediately
- [ ] Partner endpoints rate-limited (**60 req/min** per key)
- [ ] Partner calls appear in `audit_log` with `actor=pos`
- [ ] Webhook HMAC verified by POS (`X-Partner-Signature: sha256=...`)

## Sign-off

| Role | Name | Date |
|------|------|------|
| Platform QA | | |
| POS engineering | | |
| Restaurant pilot | | |