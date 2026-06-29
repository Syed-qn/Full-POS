from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

# Register ALL model metadata in the worker process. Tasks (e.g. outbox.deliver)
# touch OutboxMessage, whose restaurant_id FK targets the `restaurants` table; if
# the Restaurant model (and its siblings) are never imported here, SQLAlchemy
# cannot resolve that foreign key at commit time and raises NoReferencedTableError
# — the send succeeds but the status write fails, so Celery retries and the
# customer receives duplicate WhatsApp messages. Keep this list in sync with
# alembic/env.py and tests/conftest.py.
import app.audit.models  # noqa: F401,E402
import app.identity.models  # noqa: F401,E402
import app.menu.models  # noqa: F401,E402
import app.webhook.models  # noqa: F401,E402
import app.outbox.models  # noqa: F401,E402
import app.conversation.models  # noqa: F401,E402
import app.ordering.models  # noqa: F401,E402
import app.dispatch.models  # noqa: F401,E402
import app.sla.models  # noqa: F401,E402
import app.coupons.models  # noqa: F401,E402
import app.cod.models  # noqa: F401,E402
import app.marketing.models  # noqa: F401,E402
import app.predictions.models  # noqa: F401,E402

settings = get_settings()
celery_app = Celery(
    "restaurant",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_default_queue="default",
    timezone="Asia/Dubai",
    task_routes={
        "outbox.deliver": {"queue": "outbox"},
        "outbox.sweep_failed": {"queue": "outbox"},
        "sla.monitor_tick": {"queue": "sla_monitor"},
        "conversation.*": {"queue": "default"},
        "dispatch.*": {"queue": "dispatch"},
        "ml.*": {"queue": "ml"},
        "marketing.*": {"queue": "marketing"},
        "wallet.*": {"queue": "maintenance"},
        "loyalty.*": {"queue": "maintenance"},
    },
    beat_schedule={
        "sla-monitor-tick": {
            "task": "sla.monitor_tick",
            "schedule": 30.0,  # every 30s — spec §4.5 heartbeat (GAP#6: was 60s)
        },
        "dispatch-sweep-ready": {
            "task": "dispatch.sweep_ready",
            # Re-dispatch restaurants with ready+unassigned orders: releases held
            # (batch-window) orders once matured and retries stuck no-rider orders.
            "schedule": settings.dispatch_sweep_seconds,
        },
        "nightly-forecast-all-tenants": {
            "task": "ml.forecast_all_tenants",
            "schedule": crontab(hour=2, minute=0),  # 2am Asia/Dubai
        },
        # GAP#5: weekly retrain (producer=beat using settings crontab; default Mon 04:00 per spec §4.6; no hardcode)
        "weekly-retrain-all-tenants": {
            "task": "ml.retrain_all_tenants",
            "schedule": crontab(
                day_of_week=settings.predictions_weekly_retrain_dow,
                hour=settings.predictions_weekly_retrain_hour,
                minute=settings.predictions_weekly_retrain_minute,
            ),
        },
        "nightly-marketing-campaigns": {
            "task": "marketing.send_scheduled_campaigns",
            "schedule": crontab(hour=9, minute=0),  # 9am when UAE window opens
        },
        "outbox-sweep-failed": {
            "task": "outbox.sweep_failed",
            "schedule": 300.0,  # every 5 minutes — orphan recovery
        },
        "abandoned-cart-sweep": {
            "task": "conversation.abandoned_cart_sweep",
            "schedule": 300.0,  # every 5 minutes — nudge stale draft carts
        },
        # GAP#3 / phase-6: poll Meta approval status (every N min from settings), EOD ephemeral delete (23:30 Dubai from settings)
        "marketing-poll-template-statuses": {
            "task": "marketing.poll_template_statuses",
            "schedule": crontab(minute=f"*/{settings.marketing_template_poll_minutes}"),
        },
        "marketing-cleanup-ephemeral-templates": {
            "task": "marketing.cleanup_ephemeral_templates",
            "schedule": crontab(
                hour=settings.marketing_ephemeral_delete_hour,
                minute=settings.marketing_ephemeral_delete_minute,
            ),
        },
        "wallet-expire-credits": {
            "task": "wallet.expire_credits_all_tenants",
            "schedule": crontab(hour=3, minute=0),  # 3am Asia/Dubai
        },
        "wallet-reconcile": {
            "task": "wallet.reconcile_all_tenants",
            "schedule": crontab(hour=3, minute=30),  # 3:30am Asia/Dubai
        },
        "loyalty-recompute-tiers": {
            "task": "loyalty.recompute_all_tenants",
            "schedule": crontab(hour=4, minute=0),  # 4am Asia/Dubai (after reconcile)
        },
    },
)
celery_app.autodiscover_tasks(
    ["app.outbox", "app.sla", "app.predictions", "app.marketing", "app.conversation",
     "app.dispatch", "app.wallet", "app.loyalty"],
    related_name="worker",
)
