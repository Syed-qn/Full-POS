"""Test outbox exponential backoff (P7-T1)."""


def test_backoff_countdown_progression():
    """Verify countdown doubles: 10, 20, 40, 80, 160."""
    from app.outbox.worker import _backoff_countdown
    assert _backoff_countdown(0) == 10
    assert _backoff_countdown(1) == 20
    assert _backoff_countdown(2) == 40
    assert _backoff_countdown(3) == 80
    assert _backoff_countdown(4) == 160


def test_permanent_failure_marked_dead():
    """4xx HTTP errors should mark the message dead, not retry."""
    from app.outbox.worker import _is_permanent_failure
    # 404 = permanent
    assert _is_permanent_failure(404) is True
    # 400 = permanent
    assert _is_permanent_failure(400) is True
    # 422 = permanent
    assert _is_permanent_failure(422) is True
    # 429 = transient (rate limit — should retry)
    assert _is_permanent_failure(429) is False
    # 500 = transient
    assert _is_permanent_failure(500) is False
    # 503 = transient
    assert _is_permanent_failure(503) is False
    # 200 = not a failure
    assert _is_permanent_failure(200) is False
