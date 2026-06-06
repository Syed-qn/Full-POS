# Observability — Prometheus + Grafana

Provisioning for metrics scraping and dashboards. This is **prep for Phase 7
Task 10** (`/metrics` endpoint + `src/app/obs/metrics.py`). The provisioning
files exist now; the compose wiring below is **deferred** — paste it into
`docker-compose.prod.yml` only **once P7-T10 lands** and the `api` service
actually serves `GET /metrics`.

> Scope note: this doc and the `ops/` tree are owned by the observability prep.
> No application code, compose, or tests were changed. The compose snippets here
> are copy-paste-ready additions, not applied edits.

## What gets scraped

The api container will expose an **unauthenticated** plaintext `/metrics`
endpoint on port 8000 (P7-T10). It is intentionally **not host-published** — only
the in-cluster Prometheus may reach it. The P7-T10 metric set:

| Metric | Type | Labels | Meaning |
| --- | --- | --- | --- |
| `http_requests_total` | Counter | `method`, `path`, `status` | Request counts; `path` = matched route template (bounded cardinality) |
| `http_request_duration_seconds` | Histogram | `method`, `path` | Per-route latency; webhook latency derived by filtering `path="/webhooks/whatsapp"` |
| `outbox_deliveries_total` | Counter | `result` (`sent`/`failed`/`dead`) | Outbox delivery outcomes; `dead` = dead-letter count |
| `sla_breaches_total` | Counter | `restaurant_id` | Orders breaching the 40-minute SLA |
| `rate_limit_rejections_total` | Counter | `scope` (`auth`/`webhook`) | Requests rejected with HTTP 429 |

**Not implemented in P7-T10** (the brief mentioned these, but the plan does not
define them): a standalone `orders_by_status` gauge, a dedicated outbox-depth
gauge, and a separate webhook-latency histogram. The dashboard derives what it
can from the metrics above:
- Outbox queue pressure / dead count → from `outbox_deliveries_total{result}`.
- Webhook p50/p95/p99 → from `http_request_duration_seconds_bucket{path="/webhooks/whatsapp"}`.
- Orders-by-status → a placeholder text panel until the gauge is added. To add it
  later: register `orders_by_status{restaurant_id,status}` on
  `app.obs.metrics.REGISTRY`, refresh it from a beat task, then swap the
  placeholder for `sum by (status) (orders_by_status)` (stacked).

## Files in this repo

```
ops/
  prometheus/prometheus.yml                                  scrape config (api:8000/metrics @15s + self)
  grafana/
    provisioning/datasources/prometheus.yml                  auto-add Prometheus datasource (uid restaurant-prometheus)
    provisioning/dashboards/dashboards.yml                    dashboard provider (loads /var/lib/grafana/dashboards)
    dashboards/restaurant-ops.json                            the Restaurant Ops dashboard (dark, 30s refresh)
```

The Grafana datasource `uid` is `restaurant-prometheus`; the dashboard JSON
references that exact uid, so import is automatic with no manual datasource pick.

## Compose additions (paste into `docker-compose.prod.yml` when P7-T10 lands)

Add these two services under `services:` and the two named volumes under
`volumes:`. They join the same default compose network, so Prometheus reaches the
app as `api:8000` and Grafana reaches Prometheus as `prometheus:9090`. Neither the
app's `/metrics` nor Prometheus is host-published; only Grafana is.

```yaml
  prometheus:
    image: prom/prometheus:v2.54.1
    restart: unless-stopped
    command:
      - --config.file=/etc/prometheus/prometheus.yml
      - --storage.tsdb.path=/prometheus
      - --storage.tsdb.retention.time=15d
    volumes:
      - ./ops/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus_data:/prometheus
    depends_on:
      api:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "-q", "-O", "-", "http://localhost:9090/-/healthy"]
      interval: 30s
      timeout: 5s
      retries: 3
    mem_limit: 512m
    # Internal only — Grafana scrapes it on the compose network.
    expose:
      - "9090"

  grafana:
    image: grafana/grafana:11.2.0
    restart: unless-stopped
    environment:
      GF_SECURITY_ADMIN_USER: ${GRAFANA_ADMIN_USER:-admin}
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:?set GRAFANA_ADMIN_PASSWORD}
      GF_USERS_ALLOW_SIGN_UP: "false"
      GF_AUTH_ANONYMOUS_ENABLED: "false"
    volumes:
      - ./ops/grafana/provisioning:/etc/grafana/provisioning:ro
      - ./ops/grafana/dashboards:/var/lib/grafana/dashboards:ro
      - grafana_data:/var/lib/grafana
    depends_on:
      prometheus:
        condition: service_healthy
    ports:
      - "${GRAFANA_PORT:-3000}:3000"
    mem_limit: 512m
```

Append to the existing `volumes:` block:

```yaml
  prometheus_data:
  grafana_data:
```

New env vars for `.env` / `.env.example`:

```
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=         # required — fail-fast :? in compose
GRAFANA_PORT=3000
```

> The dashboard provider mounts `ops/grafana/provisioning` at
> `/etc/grafana/provisioning` (datasource + provider yml) and the JSON at
> `/var/lib/grafana/dashboards` (the `path` in `dashboards.yml`). Keep both mounts
> or the dashboard will not load.

Bring up after P7-T10 is merged:

```bash
docker compose -f docker-compose.prod.yml up -d prometheus grafana
# Verify the scrape target is UP:
docker compose -f docker-compose.prod.yml exec prometheus \
  wget -qO- 'http://localhost:9090/api/v1/targets' | grep restaurant-api
# Grafana → http://localhost:3000 → folder "Restaurant Ops" → "Restaurant Ops" dashboard.
```

## Alerting suggestions

Wire these as Prometheus rules (`ops/prometheus/rules.yml`, then uncomment
`rule_files` + add an Alertmanager target in `prometheus.yml`) or as Grafana
alert rules on the corresponding panels. Thresholds match the dashboard.

| Alert | Expression (PromQL) | For | Severity |
| --- | --- | --- | --- |
| SLA breach detected | `sum(increase(sla_breaches_total[5m])) > 0` | 5m | critical |
| Outbox dead-letter | `sum(increase(outbox_deliveries_total{result="dead"}[5m])) > 0` | 0m (immediate) | critical |
| Webhook p95 latency high | `histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{path="/webhooks/whatsapp"}[5m]))) > 0.5` | 5m | warning |
| Elevated 5xx error rate | `sum(rate(http_requests_total{status=~"5.."}[5m])) / clamp_min(sum(rate(http_requests_total[5m])),1) > 0.02` | 5m | warning |
| Rising outbox failures | `sum(increase(outbox_deliveries_total{result="failed"}[5m])) > 20` | 10m | warning |
| Auth brute-force | `sum(rate(rate_limit_rejections_total{scope="auth"}[5m])) > 1` | 5m | warning |

Rationale for the three headline alerts the brief calls out:
- **SLA breach > 0 over 5 min** — any breach is a customer-facing failure that
  also triggers an automatic coupon (spec), so operators must see it promptly.
- **Outbox dead > 0** — a dead-lettered WhatsApp message means a customer never
  received an order update; it needs manual intervention (spec §5 manager alert).
- **Webhook p95 > 500ms** — inbound ingest latency directly delays order
  processing against the 40-minute clock; the load harness SLO (`load/README.md`)
  targets webhook p95 < 250ms, so 500ms is a generous alarm ceiling.

## Dashboard description (`restaurant-ops.json`)

**Theme:** dark. **Refresh:** 30s. **Timezone:** Asia/Dubai. **Default range:**
last 3h. **Datasource:** Prometheus (`uid: restaurant-prometheus`). Tooltips are
shared-crosshair across panels. A `status` template variable (multi, include-all)
is sourced from `label_values(http_requests_total, status)`.

Layout, top to bottom, in collapsible rows:

1. **Outbox delivery** —
   - *Outbox queue throughput by result (stacked bars):* `sent` (green) /
     `failed` (orange) / `dead` (red) rates from `outbox_deliveries_total`.
   - *Dead-letter count (stat):* cumulative `result="dead"`; background turns red
     at ≥ 1.
   - *Failed last 5m (stat):* `increase(...{result="failed"}[5m])`; yellow ≥ 5,
     red ≥ 20.
2. **SLA** —
   - *SLA breach rate per restaurant (lines):* `rate(sla_breaches_total[5m])` by
     `restaurant_id`.
   - *SLA breaches last 5m (stat):* all-tenant `increase(...[5m])`; red ≥ 1.
3. **HTTP traffic** —
   - *Request rate by endpoint (lines):* `rate(http_requests_total[5m])` by
     route-template `path`.
   - *Error rate (lines, % of total):* 5xx (red) and 4xx (orange) shares of
     `http_requests_total`.
4. **Webhook latency** —
   - *Webhook p50/p95/p99 (lines):* `histogram_quantile` over
     `http_request_duration_seconds_bucket{path="/webhooks/whatsapp"}`; p50 green,
     p95 yellow, p99 red.
   - *Rate-limit rejections by scope (stacked bars):* `rate_limit_rejections_total`
     split `auth` vs `webhook`.
5. **Order status** —
   - *Placeholder text panel* explaining there is no `orders_by_status` gauge in
     P7-T10 yet and how to add the stacked panel when it ships.

When viewing live: green/quiet panels = healthy; any red stat (dead-letter, SLA
breach), a rising p95/p99 webhook line crossing ~0.5s, or a climbing 5xx line are
the at-a-glance trouble signals.
