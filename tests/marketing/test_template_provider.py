"""Unit tests for the TemplatePort — Mock provider + factory.

Pure / no DB. The Mock provider runs the compliance linter and
auto-approves compliant specs (deterministic, lets the full pipeline
run in tests/dev with no network). The real Meta provider must never
be instantiated under dry-run. See plan Task 14.
"""
import pytest

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
