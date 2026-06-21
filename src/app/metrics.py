"""Prometheus metrics registry (P7-T10).

All metrics are registered in a dedicated CollectorRegistry (not the default
global) so tests can import without polluting the process-wide registry.
The /metrics endpoint exposes this registry via generate_latest().

Cardinality discipline: ``endpoint`` uses route templates (e.g.
``/api/v1/orders/{id}``) never raw URLs — prevents metric explosion from
path params. Middleware resolves the template via ``request.scope["route"]``.
"""
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

REGISTRY = CollectorRegistry(auto_describe=True)

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
    registry=REGISTRY,
)

HTTP_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
    registry=REGISTRY,
)

OUTBOX_DELIVERIES = Counter(
    "outbox_deliveries_total",
    "Outbox message delivery attempts",
    ["status"],
    registry=REGISTRY,
)

SLA_BREACHES = Counter(
    "sla_breaches_total",
    "SLA breaches (40-min threshold)",
    ["restaurant_id"],
    registry=REGISTRY,
)

RATE_LIMIT_REJECTIONS = Counter(
    "rate_limit_rejections_total",
    "Rate-limit rejections",
    ["endpoint"],
    registry=REGISTRY,
)

# Dispatch engine observability (greedy vs ortools).
DISPATCH_RUNS = Counter(
    "dispatch_runs_total",
    "Dispatch engine runs",
    ["engine"],
    registry=REGISTRY,
)

DISPATCH_ORDERS = Counter(
    "dispatch_orders_total",
    "Orders processed by the dispatch engine, by outcome",
    ["engine", "outcome"],  # outcome: assigned | dropped
    registry=REGISTRY,
)

DISPATCH_SOLVE_SECONDS = Histogram(
    "dispatch_solve_seconds",
    "Wall time of one dispatch plan computation",
    ["engine"],
    registry=REGISTRY,
)


def metrics_response() -> tuple[bytes, str]:
    """Return (body_bytes, content_type) for the /metrics handler."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
