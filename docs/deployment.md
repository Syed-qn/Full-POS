# Production Deployment Runbook

Deployment artifacts for the Restaurant WhatsApp Platform (modular monolith:
FastAPI API + Celery worker/beat, PostgreSQL/PostGIS, Redis).

The **frontend dashboard ships separately** (its own static build/host) and is
intentionally excluded from these images and the `.dockerignore`.

## Artifacts

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage API image (builder → non-root runtime, `uvicorn`). |
| `Dockerfile.worker` | Multi-stage Celery worker/beat image. |
| `docker-compose.prod.yml` | Full prod topology: `db`, `redis`, `migrate`, `api`, `worker`, `beat`. |
| `.dockerignore` | Keeps tests/docs/frontend/venv/secrets out of the build context. |
| `scripts/prod-smoke.sh` | Boots the stack, asserts `/health` + webhook handshake, tears down. |

## 1. Build

```bash
docker compose -f docker-compose.prod.yml build
# or individually:
docker build -t restaurant-api:latest -f Dockerfile .
docker build -t restaurant-worker:latest -f Dockerfile.worker .
```

Both images are multi-stage: a `builder` stage compiles dependency wheels (with
`build-essential` for argon2/asyncpg), and a slim `runtime` stage installs only
runtime dependencies from those wheels and runs as the **non-root `app` user**
(uid 10001). No dev dependencies (`pytest`, `ruff`, `httpx`) reach the runtime
image.

## 2. Environment variables

Copy `.env.example` to `.env` and fill in production values. The compose file
injects `.env` into every service via `env_file` and **overrides**
`APP_DATABASE_URL` / `APP_REDIS_URL` so services reach `db` / `redis` over the
compose network (you do not need to set those two in `.env`).

| Variable | Required | Secret | Notes |
|----------|----------|--------|-------|
| `APP_ENV` | yes | no | Set to `prod`. |
| `APP_DATABASE_URL` | auto | — | Overridden by compose to `...@db:5432/...`. Only set for non-compose deploys. |
| `APP_REDIS_URL` | auto | — | Overridden by compose to `redis://:${REDIS_PASSWORD}@redis:6379/0`. |
| `REDIS_PASSWORD` | yes | **YES** | Redis auth (broker + backend). Compose fails fast if unset. |
| `APP_JWT_SECRET` | yes | **YES** | Manager-dashboard JWT signing key. Generate a long random value. |
| `APP_JWT_TTL_MINUTES` | no | no | Token lifetime (default 60). |
| `APP_LLM_PROVIDER` | yes | no | `fake` \| `claude`. Use `claude` in prod for menu/ordering AI. |
| `APP_ANTHROPIC_API_KEY` | if `claude` | **YES** | Anthropic API key. |
| `APP_CLAUDE_MODEL` | no | no | Default `claude-opus-4-8`. |
| `APP_UPLOAD_DIR` | no | no | Menu-image upload dir (default `var/uploads`; container-local). |
| `APP_WHATSAPP_PROVIDER` | yes | no | **Must be `cloud` in prod** (see Scaling). `mock` is dev only. |
| `APP_WA_VERIFY_TOKEN` | yes | **YES** | Token you register in the Meta webhook handshake. |
| `APP_WA_ACCESS_TOKEN` | if `cloud` | **YES** | Meta WhatsApp Cloud API access token. |
| `APP_WA_PHONE_NUMBER_ID` | if `cloud` | no | Meta phone number ID. |
| `APP_WA_APP_SECRET` | if `cloud` | **YES** | Meta app secret (inbound payload signature verification). |
| `APP_GEO_PROVIDER` | yes | no | `fake` \| `google_maps`. Use `google_maps` in prod. |
| `APP_GOOGLE_MAPS_API_KEY` | if `google_maps` | **YES** | Google Maps Distance Matrix key. |

| `APP_CORS_ALLOW_ORIGINS` | no | no | Comma-separated list of allowed CORS origins (e.g. `https://dashboard.yourdomain.com`). Empty = no CORS headers. |
| `APP_HSTS_ENABLED` | no | no | Set to `true` in prod to add `Strict-Transport-Security` header. Default `false`. |
| `APP_RATE_LIMIT_ENABLED` | no | no | Enable Redis token-bucket rate limiting on auth + webhook. Default `true`. |
| `APP_AUTH_RATE_LIMIT` | no | no | Auth endpoint rate limit spec, e.g. `5/minute`. |
| `APP_WEBHOOK_RATE_LIMIT` | no | no | Webhook endpoint rate limit spec, e.g. `120/minute`. |
| `APP_WEBHOOK_REPLAY_WINDOW_SECONDS` | no | no | Reject inbound Meta messages older than N seconds. Default `300`. |
| `APP_LOG_LEVEL` | no | no | Log level (default `info`). |

Compose-level (set in `.env` or shell, not `APP_`-prefixed):

| Variable | Default | Notes |
|----------|---------|-------|
| `POSTGRES_USER` | `app` | DB role. |
| `POSTGRES_PASSWORD` | — (**required**) | Compose fails fast if unset. **Secret.** |
| `POSTGRES_DB` | `restaurant` | DB name. |
| `API_PORT` | `8000` | Host port published for the API. |
| `APP_WORKERS` | `4` | uvicorn worker processes (multi-worker safe). |
| `APP_CONCURRENCY` | `4` | Celery worker concurrency. |

**Never commit `.env`** — it is gitignored.

## 3. First boot (migrations)

The `migrate` service runs `alembic upgrade head` exactly once and must exit 0
before `api`, `worker`, and `beat` start (`depends_on:
service_completed_successfully`). You do not run migrations by hand.

```bash
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml logs -f migrate   # confirm "upgrade head" succeeded
```

Migrations create the PostGIS extension and all schema/triggers. If `migrate`
fails, `api` will not start — inspect its logs, fix, and re-run `up`.

## 4. WhatsApp webhook registration with Meta

The API exposes the Meta Cloud API webhook at **`/webhooks/whatsapp`**.

1. Expose the API over HTTPS at a stable public URL (reverse proxy / load
   balancer terminating TLS in front of port 8000).
2. In the Meta App dashboard → WhatsApp → Configuration → Webhooks, set:
   - **Callback URL**: `https://YOUR_DOMAIN/webhooks/whatsapp`
   - **Verify token**: the exact value of `APP_WA_VERIFY_TOKEN`.
3. Meta sends a **GET handshake**: `GET /webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=<token>&hub.challenge=<nonce>`.
   The API returns the `hub.challenge` value verbatim (HTTP 200) only when the
   token matches; otherwise HTTP 403. A wrong token = failed verification.
4. Subscribe to the **`messages`** field so inbound customer messages POST to the
   same URL.

Local verification of the handshake (also done by the smoke script):

```bash
curl "http://localhost:8000/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=$APP_WA_VERIFY_TOKEN&hub.challenge=ping123"
# expect: ping123
```

## 5. Scaling notes

- **`api` and `worker` are horizontally scalable.** uvicorn runs `APP_WORKERS`
  processes; state lives in Postgres/Redis (no in-process state), so multiple
  replicas are safe: `docker compose -f docker-compose.prod.yml up -d --scale api=3 --scale worker=2`.
- **`beat` must remain a single instance** — multiple schedulers would double-fire
  periodic tasks (SLA monitor, schedulers). Never scale `beat` above 1.
- **MockProvider caveat:** the in-memory WhatsApp mock/simulator (`APP_WHATSAPP_PROVIDER=mock`)
  is **single-process dev-only** — its state is not shared across replicas and it
  never delivers to Meta. **Production must set `APP_WHATSAPP_PROVIDER=cloud`**;
  the cloud adapter is stateless and multi-worker/multi-replica safe. With `mock`
  the simulator router also mounts, which you do not want in prod.

## 6. Backup

State lives in two named volumes: `pgdata` (Postgres) and `redisdata` (Redis
AOF). Postgres is the source of truth; Redis is broker/cache.

```bash
# Logical DB dump (preferred — portable, restorable):
docker compose -f docker-compose.prod.yml exec -T db \
  pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > backup-$(date +%F).sql.gz

# Restore:
gunzip -c backup-YYYY-MM-DD.sql.gz | \
  docker compose -f docker-compose.prod.yml exec -T db psql -U "$POSTGRES_USER" "$POSTGRES_DB"
```

Uploaded menu images under `APP_UPLOAD_DIR` are container-local; mount an
external volume or object store and back that up separately if you rely on them.

## 7. Logs

```bash
docker compose -f docker-compose.prod.yml logs -f api
docker compose -f docker-compose.prod.yml logs -f worker beat
docker compose -f docker-compose.prod.yml ps      # health/status of all services
```

All services log to stdout/stderr (12-factor); ship them to your log aggregator
via the Docker logging driver.

## 8. Smoke test

```bash
./scripts/prod-smoke.sh
```

Brings the stack up, waits for `api` to be healthy, asserts `/health` returns
`ok` and the webhook GET handshake echoes the challenge, then tears the stack
down. See the script header for overridable env vars.

## 9. Metrics

The API exposes Prometheus metrics at **`/metrics`** (plain text, no auth).

> **Important:** Never publish `/metrics` to the internet. Scrape it from inside the cluster only (Prometheus → api:8000/metrics over the compose network).

Ops provisioning at `ops/prometheus/prometheus.yml` and `ops/grafana/dashboards/restaurant-ops.json`.

Key series:

| Metric | Labels | Description |
|--------|--------|-------------|
| `http_requests_total` | method, endpoint, status_code | Request count by route template |
| `http_request_duration_seconds` | method, endpoint | Latency histogram |
| `outbox_deliveries_total` | status (sent/retry/dead) | Outbox delivery outcomes |
| `sla_breaches_total` | restaurant_id | 40-min SLA breaches |
| `rate_limit_rejections_total` | endpoint | Rate-limit 429 rejections |

## 10. Pre-deploy gates

Run these before every production deploy:

```bash
# 1. Full test suite (deprecation-strict)
.venv/bin/pytest -W error::DeprecationWarning -q

# 2. Lint
.venv/bin/ruff check src apps tests

# 3. Migration round-trip
APP_DATABASE_URL=postgresql+asyncpg://...@db:5432/restaurant_migtest .venv/bin/alembic upgrade head
.venv/bin/alembic downgrade base && .venv/bin/alembic upgrade head

# 4. Secrets audit (requires prod-level secrets)
APP_ENVIRONMENT=production .venv/bin/python -m ops.secrets_audit
```
