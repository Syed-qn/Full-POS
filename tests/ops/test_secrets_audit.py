# tests/ops/test_secrets_audit.py
from ops.secrets_audit import Finding, audit_secrets


def test_weak_jwt_secret_flagged():
    findings = audit_secrets(
        {
            "jwt_secret": "short",
            "anthropic_api_key": "sk-ant-xxxxxxxxxxxxxxxxxxxxxxxx",
            "whatsapp_app_secret": "0123456789abcdef0123456789abcdef",
            "environment": "production",
        }
    )
    names = {f.field for f in findings}
    assert "jwt_secret" in names  # < 32 bytes
    assert all(isinstance(f, Finding) for f in findings)


def test_default_dev_secret_flagged():
    findings = audit_secrets(
        {"jwt_secret": "dev-insecure-change-me-please-32b!!", "environment": "production"}
    )
    assert any("default" in f.reason.lower() or "known" in f.reason.lower()
               for f in findings if f.field == "jwt_secret") or \
           any(f.field == "jwt_secret" for f in findings)


def test_strong_prod_secrets_pass():
    findings = audit_secrets(
        {
            "jwt_secret": "x" * 48,
            "anthropic_api_key": "sk-ant-" + "y" * 40,
            "whatsapp_app_secret": "z" * 40,
            "environment": "production",
        }
    )
    assert findings == []


def test_dev_environment_is_lenient():
    findings = audit_secrets({"jwt_secret": "short", "environment": "dev"})
    assert findings == []  # only enforce in production/staging
