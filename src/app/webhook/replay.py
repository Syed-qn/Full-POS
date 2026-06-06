"""Webhook replay-window freshness guard (P7-T11).

Raises ReplayError when timestamp is outside the freshness window:
- ts=None or ts=0: exempt (mock/simulator path, no real timestamp)
- stale (> window_seconds ago): replay attack
- far future (> window_seconds ahead): clock skew / forgery
"""
import datetime as dt


class ReplayError(ValueError):
    pass


def assert_fresh(ts: int | None, *, window_seconds: int = 300) -> None:
    """Raise ReplayError if ts is outside the acceptable freshness window.
    Returns None on success (including exempt ts=None/0).
    """
    if ts is None or ts == 0:
        return None
    now = dt.datetime.now(dt.timezone.utc)
    msg_time = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc)
    age_seconds = (now - msg_time).total_seconds()
    if abs(age_seconds) > window_seconds:
        raise ReplayError(
            f"message timestamp {ts} is {abs(age_seconds):.0f}s outside "
            f"the {window_seconds}s freshness window"
        )
    return None
