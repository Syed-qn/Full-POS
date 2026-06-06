"""Tests for Prometheus metrics (P7-T10)."""


def test_metrics_importable():
    from app.metrics import (
        HTTP_REQUESTS,
        HTTP_DURATION,
        OUTBOX_DELIVERIES,
        SLA_BREACHES,
        RATE_LIMIT_REJECTIONS,
        REGISTRY,
        metrics_response,
    )
    assert HTTP_REQUESTS is not None
    assert REGISTRY is not None


def test_metrics_response_returns_bytes():
    from app.metrics import metrics_response
    body, content_type = metrics_response()
    assert isinstance(body, bytes)
    assert "text/plain" in content_type


def test_counter_increments():
    from app.metrics import OUTBOX_DELIVERIES, REGISTRY
    from prometheus_client import generate_latest
    OUTBOX_DELIVERIES.labels(status="test_inc").inc()
    output = generate_latest(REGISTRY).decode()
    assert "test_inc" in output
