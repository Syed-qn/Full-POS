"""Business-hours helper (OPT-IN).

Pure functions over the restaurant's ``settings['open_hours']`` so they are
trivially testable without a DB or a real clock — the caller passes ``now`` as a
timezone-aware UTC datetime and the helper converts to the restaurant's local
zone internally.

Schema (every part optional — an absent/empty ``open_hours`` means ALWAYS OPEN,
so existing restaurants keep working until a manager configures hours):

    settings["open_hours"] = {
        "tz": "Asia/Dubai",            # optional, default Asia/Dubai
        "days": {                       # weekday int as string, 0=Mon .. 6=Sun
            "0": ["11:00", "23:00"],
            "1": ["11:00", "23:00"],
            ...
        },
    }

A weekday missing from ``days`` (or mapped to null/empty) means CLOSED that day.
Cross-midnight windows (close <= open) are not supported and are treated as
closed for safety.
"""
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

_DEFAULT_TZ = "Asia/Dubai"
_WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                  "Saturday", "Sunday"]


def _tz(open_hours: dict) -> ZoneInfo:
    try:
        return ZoneInfo(open_hours.get("tz") or _DEFAULT_TZ)
    except Exception:
        return ZoneInfo(_DEFAULT_TZ)


def _parse_hhmm(value: str) -> time | None:
    try:
        hh, mm = value.strip().split(":")
        return time(int(hh), int(mm))
    except (ValueError, AttributeError):
        return None


def _window_for(open_hours: dict, weekday: int) -> tuple[time, time] | None:
    """Return (open, close) for the weekday, or None if closed/invalid."""
    days = open_hours.get("days") or {}
    raw = days.get(str(weekday))
    if not raw or len(raw) != 2:
        return None
    open_t, close_t = _parse_hhmm(raw[0]), _parse_hhmm(raw[1])
    if open_t is None or close_t is None or close_t <= open_t:
        return None
    return open_t, close_t


def is_open(open_hours: dict | None, now: datetime) -> bool:
    """True if the restaurant is open at ``now`` (UTC). Empty config ⇒ always open."""
    if not open_hours or not open_hours.get("days"):
        return True
    local = now.astimezone(_tz(open_hours))
    window = _window_for(open_hours, local.weekday())
    if window is None:
        return False
    return window[0] <= local.time() < window[1]


def _fmt_time(t: time) -> str:
    """12-hour label, e.g. '11:00 AM' (no leading zero on the hour)."""
    hour12 = t.hour % 12 or 12
    suffix = "AM" if t.hour < 12 else "PM"
    return f"{hour12}:{t.minute:02d} {suffix}"


def next_opening_label(open_hours: dict | None, now: datetime) -> str | None:
    """Human label for the next opening time, scanning up to 7 days ahead.

    Returns e.g. "11:00 AM" (today/later), "tomorrow 11:00 AM", or
    "Monday 11:00 AM". None when always-open or no opening found in a week.
    """
    if not open_hours or not open_hours.get("days"):
        return None
    local = now.astimezone(_tz(open_hours))
    for offset in range(0, 8):
        day = local.weekday() + offset
        window = _window_for(open_hours, day % 7)
        if window is None:
            continue
        open_t = window[0]
        if offset == 0 and local.time() >= open_t:
            continue  # already past today's opening
        label = _fmt_time(open_t)
        if offset == 0:
            return label
        if offset == 1:
            return f"tomorrow {label}"
        return f"{_WEEKDAY_NAMES[day % 7]} {label}"
    return None
