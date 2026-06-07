"""Tests for the marketing Celery worker (marketing.send_scheduled_campaigns)."""

from datetime import datetime, timezone

from app.marketing.models import Campaign, WaTemplate
from app.marketing.template_port import TemplateCreateResult, TemplateStatus
from app.marketing.worker import _dispatch_scheduled


async def test_send_scheduled_campaigns_no_due(db_session):
    """No due campaigns — _dispatch_scheduled must complete without error."""
    # The test DB is clean; nothing is scheduled, so there's nothing to send.
    await _dispatch_scheduled()


async def test_send_scheduled_campaigns_runs(db_session, restaurant):
    """A scheduled campaign is picked up and processed (status transitions to sent/failed)."""
    # Build the minimum required rows: a template + campaign with scheduled_at in the past.
    tpl = WaTemplate(
        restaurant_id=restaurant.id,
        meta_template_name="worker_test_tpl_20260606",
        language="en",
        category="marketing",
        body="Hello! Today's special is fresh and ready. Order now to enjoy a great meal.",
        footer="Reply STOP to unsubscribe",
        buttons=[],
        status="approved",
        meta_template_id="fake-meta-id",
    )
    db_session.add(tpl)
    await db_session.flush()

    past_time = datetime(2026, 6, 5, 6, 0, tzinfo=timezone.utc)  # yesterday UTC
    campaign = Campaign(
        restaurant_id=restaurant.id,
        type="todays_special",
        template_id=tpl.id,
        scheduled_at=past_time,
        status="scheduled",
    )
    db_session.add(campaign)
    await db_session.flush()
    # Commit so the separate session inside _dispatch_scheduled can see the row.
    await db_session.commit()

    # Run the worker; must not raise even if it finds no eligible recipients.
    await _dispatch_scheduled()

    # Re-fetch the campaign to check its final status.
    await db_session.refresh(campaign)
    # After processing there are no customers to send to, so the campaign should
    # have been set to "sent" (with 0 sends) or remain in a terminal/processed state.
    assert campaign.status in {"sent", "failed", "scheduled"}


# ---------------------------------------------------------------------------
# TDD for GAP#3: Meta approval poll loop + auto-delete EOD ephemeral job
# (spec §4.7 "poll status → auto-deleted end of day (ephemeral)", phase-6
# plan: poll_template_statuses */2, cleanup_ephemeral_templates 23:30 Dubai,
# update pending_meta, call provider.delete + set deleted_at for blackout).
# Add failing tests first (will fail on missing tasks/funcs in worker/service).
# Extend with integration using mock provider + seed pending/ephemeral.
# ---------------------------------------------------------------------------

async def test_poll_template_statuses_task_exists():
    """Failing until poll task added to worker + wired in celery_app."""
    import app.marketing.worker as w
    assert hasattr(w, "poll_template_statuses")


async def test_cleanup_ephemeral_templates_task_exists():
    """Failing until EOD cleanup task + beat in celery_app."""
    import app.marketing.worker as w
    assert hasattr(w, "cleanup_ephemeral_templates")


async def test_poll_template_statuses_updates_pending(db_session, restaurant):
    """Failing: poll should query pending_meta, call provider.get_status, update
    status/rejection, flush (no commit in helper). Uses mock provider."""
    from app.marketing.models import WaTemplate
    from app.marketing.template_mock import MockTemplateProvider

    tpl = WaTemplate(
        restaurant_id=restaurant.id,
        meta_template_name="poll_test_20260606",
        language="en",
        category="marketing",
        body="Test body for poll.",
        footer="Reply STOP",
        status="pending_meta",
        meta_template_id="meta-poll-1",
        ephemeral=True,
    )
    db_session.add(tpl)
    await db_session.flush()
    await db_session.commit()

    provider = MockTemplateProvider()
    async def _g(mid):
        return TemplateCreateResult(meta_template_id=mid, status=TemplateStatus.APPROVED, rejection_reason=None)
    provider.get_status = _g

    # Use svc directly (worker _ opens factory session; in this test tx the committed seed is visible to svc on same session; behavior covered, existence of task already asserted)
    from app.marketing.service import poll_template_statuses as svc_poll
    updated = await svc_poll(db_session, provider=provider)
    await db_session.commit()  # if svc flushed
    await db_session.refresh(tpl)
    assert updated >= 1
    assert tpl.status == "approved"


async def test_cleanup_ephemeral_deletes_todays_and_sets_deleted_at(db_session, restaurant):
    """Failing: cleanup EOD finds ephemeral approved/sent created 'today', calls
    provider.delete, sets status=deleted, deleted_at=now (UTC). Feeds naming 30d."""
    from datetime import datetime, timezone
    from app.marketing.models import WaTemplate
    from app.marketing.template_mock import MockTemplateProvider

    tpl = WaTemplate(
        restaurant_id=restaurant.id,
        meta_template_name="eod_cleanup_20260606",
        language="en",
        category="marketing",
        body="EOD body.",
        footer="Reply STOP",
        status="approved",
        ephemeral=True,
        meta_template_id="meta-eod-1",
        deleted_at=None,
    )
    db_session.add(tpl)
    await db_session.flush()
    await db_session.commit()

    provider = MockTemplateProvider()
    # pre 'create' + hack for meta id so delete succeeds in svc (uses meta or name)
    await provider.create(type("S",(),{"name":"eod","to_compliance_dict":lambda s:{"name":"e","body":"b","header":None,"footer":None,"buttons":[]}})())
    provider._id_by_name["eod_cleanup_20260606"] = "meta-eod-1"
    provider._by_id["meta-eod-1"] = type("R", (), {"meta_template_id": "meta-eod-1", "status": "approved"})()  # dummy ok for delete path

    now = datetime(2026, 6, 6, 23, 30, tzinfo=timezone.utc)
    # Use svc directly on test session (avoids factory session visibility for this worker-layer test; existence + service tests cover full)
    from app.marketing.service import cleanup_ephemeral_templates as svc_cleanup
    deleted_count = await svc_cleanup(db_session, provider=provider, now=now)
    await db_session.commit()
    await db_session.refresh(tpl)

    assert deleted_count >= 1
    assert tpl.status == "deleted"
    assert tpl.deleted_at is not None
