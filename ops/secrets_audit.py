# ops/secrets_audit.py
"""Production secrets-strength audit.

Standalone, dependency-light gate that fails CI / a cron if any production
secret is weak, default, or unset. Reads from the live ``Settings`` via
``main()`` and NEVER logs secret values. ``audit_secrets`` is a pure function
over a plain dict so it is fully unit-testable without app/DB state.

Run as a deploy-time gate / CI step:

    APP_ENVIRONMENT=production .venv/bin/python -m ops.secrets_audit
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

_MIN_LEN = 32
_ENFORCED_ENVS = {"production", "staging"}
# values that ship as defaults in .env.example / config — never allowed in prod
_KNOWN_DEFAULTS = {
    "dev-insecure-change-me-please-32b!!",
    "dev-secret-change-me-0123456789abcdef",
    "changeme",
    "dev-secret",
}
_REQUIRED_IN_PROD = ("jwt_secret",)


@dataclass(frozen=True)
class Finding:
    field: str
    reason: str


def audit_secrets(values: dict) -> list[Finding]:
    """Return findings for weak/default/unset secrets, enforced only in prod/staging."""
    env = (values.get("environment") or "dev").lower()
    if env not in _ENFORCED_ENVS:
        return []
    findings: list[Finding] = []
    for field in _REQUIRED_IN_PROD:
        if not values.get(field):
            findings.append(Finding(field, "required secret is unset"))
    for field, raw in values.items():
        if field == "environment" or not isinstance(raw, str) or raw == "":
            continue
        if not _is_secret_field(field):
            continue
        if raw in _KNOWN_DEFAULTS:
            findings.append(Finding(field, "uses a known default/example value"))
        elif len(raw.encode()) < _MIN_LEN:
            findings.append(Finding(field, f"shorter than {_MIN_LEN} bytes"))
    return findings


def _is_secret_field(field: str) -> bool:
    f = field.lower()
    return any(t in f for t in ("secret", "key", "token", "password", "dsn"))


def main() -> int:
    from app.config import get_settings

    s = get_settings()
    values = {
        "environment": getattr(s, "environment", "dev"),
        "jwt_secret": _reveal(getattr(s, "jwt_secret", "")),
        "anthropic_api_key": _reveal(getattr(s, "anthropic_api_key", "")),
        "whatsapp_app_secret": _reveal(getattr(s, "whatsapp_app_secret", "")),
    }
    findings = audit_secrets(values)
    for f in findings:
        print(f"SECRET AUDIT FAIL: {f.field}: {f.reason}", file=sys.stderr)
    return 1 if findings else 0


def _reveal(v) -> str:
    return v.get_secret_value() if hasattr(v, "get_secret_value") else (v or "")


if __name__ == "__main__":
    raise SystemExit(main())
