"""Shared E.164-ish phone normalization for tenant matching."""
from __future__ import annotations

import re


def normalize_phone(raw: str) -> str:
    """Normalize a phone to '+<digits>' (E.164-ish), stripping spaces, dashes, etc."""
    digits = re.sub(r"\D", "", raw or "")
    return f"+{digits}" if digits else (raw or "")


def phone_lookup_values(raw: str) -> tuple[str, ...]:
    """Distinct phone strings that should match the same tenant row.

    Covers legacy rows stored without a leading ``+`` and new normalized values."""
    normalized = normalize_phone(raw)
    digits = re.sub(r"\D", "", raw or "")
    values: list[str] = []
    for candidate in (normalized, raw, digits, f"+{digits}" if digits else ""):
        if candidate and candidate not in values:
            values.append(candidate)
    return tuple(values)