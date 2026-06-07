"""Unit tests for the TemplatePort — Mock provider + factory.

Pure / no DB. The Mock provider runs the compliance linter and
auto-approves compliant specs (deterministic, lets the full pipeline
run in tests/dev with no network). The real Meta provider must never
be instantiated under dry-run. See plan Task 14.
"""
import pytest
from unittest.mock import patch

from app.marketing.template_factory import get_template_provider
from app.marketing.template_mock import MockTemplateProvider
from app.marketing.template_port import (
    TemplateSpec,
    TemplateStatus,
)


def _compliant_spec() -> TemplateSpec:
    return TemplateSpec(
        name="daily_special_20260606",
        language="en",
        category="marketing",
        body=(
            "Hi {{1}}, today's special is {{2}}.\n"
            "Visit us before 9pm to enjoy it fresh.\n"
            "See you soon!"
        ),
        footer="Reply STOP to unsubscribe",
        header={"type": "text", "text": "Today's Special"},
        buttons=[
            {"type": "URL", "label": "View Menu", "url": "https://example.com/menu"},
            {"type": "QUICK_REPLY", "label": "Stop"},
        ],
    )


async def test_mock_create_compliant_auto_approves() -> None:
    provider = MockTemplateProvider()
    result = await provider.create(_compliant_spec())

    assert result.status is TemplateStatus.APPROVED
    assert result.meta_template_id
    assert result.rejection_reason is None


async def test_mock_get_status_returns_approved() -> None:
    provider = MockTemplateProvider()
    created = await provider.create(_compliant_spec())

    fetched = await provider.get_status(created.meta_template_id)
    assert fetched.status is TemplateStatus.APPROVED
    assert fetched.meta_template_id == created.meta_template_id


async def test_mock_delete_returns_true() -> None:
    provider = MockTemplateProvider()
    spec = _compliant_spec()
    await provider.create(spec)

    assert await provider.delete(name=spec.name) is True
    # deleting an unknown name returns False
    assert await provider.delete(name="never_created") is False


async def test_mock_create_non_compliant_rejected() -> None:
    provider = MockTemplateProvider()
    spec = _compliant_spec()
    spec.body = "Hi {{1}}, deal here bit.ly/xyz now"

    result = await provider.create(spec)
    assert result.status is TemplateStatus.REJECTED
    assert result.rejection_reason
    assert result.meta_template_id


def test_factory_returns_mock_under_default_dry_run() -> None:
    # Default settings: marketing_send_dry_run=True → mock.
    provider = get_template_provider()
    assert isinstance(provider, MockTemplateProvider)


def test_meta_provider_refuses_dry_run() -> None:
    from app.marketing.template_meta import MetaTemplateProvider

    # Default settings have marketing_send_dry_run=True → constructor must raise.
    with pytest.raises(RuntimeError):
        MetaTemplateProvider()


# ---------------------------------------------------------------------------
# TDD for GAP#3 / phase-6: real resumable image header upload (per transcript,
# spec §4.7, plan Task14, research whatsapp §5.1 + meta-compliance).
# These tests MUST fail first (no _upload_image_header, no wiring in create,
# meta guarded, no settings for app_id). Then impl minimal in template_meta.
# ---------------------------------------------------------------------------

def test_meta_template_provider_exposes_resumable_upload_helper() -> None:
    """Failing until _upload_image_header implemented in MetaTemplateProvider."""
    from app.marketing.template_meta import MetaTemplateProvider

    assert hasattr(MetaTemplateProvider, "_upload_image_header")


async def test_meta_create_with_image_header_triggers_resumable_upload(monkeypatch: pytest.MonkeyPatch) -> None:
    """Failing: Meta create for IMAGE header without pre-handle must perform
    resumable upload (2 POSTs: /app_id/uploads then upload_session) per research,
    obtain 'h:' handle, use in template components example.header_handle.
    Uses env override + httpx patch (no real net, no dry_run)."""
    monkeypatch.setenv("APP_MARKETING_SEND_DRY_RUN", "false")
    monkeypatch.setenv("APP_MARKETING_TEMPLATE_PROVIDER", "meta")
    monkeypatch.setenv("APP_WA_ACCESS_TOKEN", "EAAGfake")
    monkeypatch.setenv("APP_WA_BUSINESS_ACCOUNT_ID", "waba-123")
    monkeypatch.setenv("APP_WA_APP_ID", "app-456")  # required for /uploads (not WABA)
    from app.config import get_settings

    get_settings.cache_clear()

    from app.marketing.template_meta import MetaTemplateProvider
    from app.marketing.template_port import TemplateSpec, TemplateStatus

    # Patch httpx.AsyncClient to simulate resumable flow without network.
    call_log: list[dict] = []

    class _FakeResp:
        def __init__(self, json_data: dict | None = None, status: int = 200, content: bytes | None = None):
            self._json = json_data or {}
            self.status_code = status
            self.content = content or b""
        def json(self):
            return self._json
        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"fake http {self.status_code}")

    class _FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, url: str, **kw):
            call_log.append({"method": "post", "url": url, "kw": kw})
            if "uploads" in url and "app-456" in url:
                return _FakeResp({"id": "upload:session-xyz"})
            if "upload:session-xyz" in url:
                return _FakeResp({"h": "4::aW1hZ2VfaGFuZGxlX2Zha2U="})
            # the final template create POST
            return _FakeResp({"id": "meta-tpl-999", "status": "PENDING"})
        async def get(self, url, **kw):
            call_log.append({"method": "get", "url": url, "kw": kw})
            if "example.test" in url:
                return _FakeResp(content=b"\xff\xd8\xff fake-jpg-bytes-for-resumable")
            return _FakeResp({"data": []})
        async def delete(self, url, **kw):
            call_log.append({"method": "delete", "url": url, "kw": kw})
            return _FakeResp({"success": True})

    with patch("app.marketing.template_meta.httpx.AsyncClient", _FakeClient):
        provider = MetaTemplateProvider()
        spec = TemplateSpec(
            name="daily_img_20260606",
            language="en",
            category="marketing",
            body="Hi {{1}} today's special {{2}}.",
            header={"type": "IMAGE", "image_url": "https://example.test/special.jpg"},  # triggers upload (not pre-handle)
            footer="Reply STOP",
            buttons=[{"type": "QUICK_REPLY", "label": "Stop"}],
        )
        result = await provider.create(spec)

    assert result.status is TemplateStatus.PENDING
    assert result.meta_template_id == "meta-tpl-999"
    # verify resumable was used: saw uploads init + file post + handle in final create
    upload_calls = [c for c in call_log if "uploads" in c["url"] or "upload:" in c.get("url", "")]
    assert len(upload_calls) >= 2, f"expected 2 resumable calls, got {call_log}"
    # final create must have used the handle
    create_call = next((c for c in call_log if "message_templates" in c["url"] and c["method"]=="post"), None)
    assert create_call is not None
    payload = create_call["kw"].get("json", {})
    comps = payload.get("components", [])
    header_comp = next((c for c in comps if c.get("format") == "IMAGE"), None)
    assert header_comp is not None
    assert header_comp.get("example", {}).get("header_handle") == ["4::aW1hZ2VfaGFuZGxlX2Zha2U="]
