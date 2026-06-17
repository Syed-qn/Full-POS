"""WhatsApp template naming — datestamped names + 30-day reuse blackout.

Pure functions only (no DB, no settings). The marketing service passes
DB-fetched rows in as arguments so these stay unit-testable.

Meta rules (docs/research/meta-template-compliance.md §3.8, §4.5):
- Template names: lowercase ``[a-z0-9_]`` only, max 512 chars.
- After a template is deleted, its name cannot be reused for 30 days.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

_MAX_NAME_LEN = 512
_NAME_RE = re.compile(r"^[a-z0-9_]+$")
_NON_SLUG = re.compile(r"[^a-z0-9_]+")
_REPEAT_UNDERSCORE = re.compile(r"_+")
_BLACKOUT = timedelta(days=30)


def _slugify(prefix: str) -> str:
    """Lowercase, replace non-[a-z0-9_] with '_', collapse repeats, trim '_'."""
    slug = _NON_SLUG.sub("_", prefix.lower())
    slug = _REPEAT_UNDERSCORE.sub("_", slug)
    return slug.strip("_")


def datestamped_name(prefix: str, *, on: date, suffix: int = 0) -> str:
    """Build ``{slug}_{YYYYMMDD}`` (+ ``_{suffix}`` when suffix > 0).

    Raises ``ValueError`` if the prefix sanitizes to nothing, or the result
    is not ``^[a-z0-9_]+$`` or exceeds 512 chars.
    """
    slug = _slugify(prefix)
    if not slug:
        raise ValueError("prefix sanitizes to an empty name")

    name = f"{slug}_{on:%Y%m%d}"
    if suffix:
        name = f"{name}_{suffix}"

    if not _NAME_RE.match(name):
        raise ValueError(f"invalid template name: {name!r}")
    if len(name) > _MAX_NAME_LEN:
        raise ValueError(f"template name exceeds {_MAX_NAME_LEN} chars: {len(name)}")
    return name


def is_name_reusable(
    name: str,
    deleted_history: list[tuple[str, datetime]],
    *,
    now: datetime,
) -> bool:
    """False if ``name`` was deleted within the last 30 days, else True.

    ``deleted_history`` is a list of ``(name, deleted_at)`` tuples. The
    30-day window is inclusive: a deletion exactly 30 days ago still blocks.
    """
    cutoff = now - _BLACKOUT
    for hist_name, deleted_at in deleted_history:
        if hist_name == name and deleted_at >= cutoff:
            return False
    return True


def next_available_name(
    prefix: str,
    *,
    on: date,
    deleted_history: list[tuple[str, datetime]],
    existing_names: set[str],
    now: datetime,
) -> str:
    """Return the first datestamped name that is reusable AND not in use.

    Increments the suffix (0, 1, 2, …) until a name is both outside the
    30-day blackout and absent from ``existing_names``.
    """
    suffix = 0
    while True:
        name = datestamped_name(prefix, on=on, suffix=suffix)
        if name not in existing_names and is_name_reusable(
            name, deleted_history, now=now
        ):
            return name
        suffix += 1
