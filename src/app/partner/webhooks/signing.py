"""HMAC-SHA256 signing for outbound partner webhooks."""
from __future__ import annotations

import hashlib
import hmac


def sign_body(secret: str, body: bytes) -> str:
    """Return the value for ``X-Partner-Signature`` (``sha256=<hex>``)."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    """Verify ``X-Partner-Signature`` from an inbound request (future use)."""
    if not header or not header.startswith("sha256="):
        return False
    expected = sign_body(secret, body)
    return hmac.compare_digest(expected, header)