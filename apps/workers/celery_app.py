from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

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
        "sla.monitor_tick": {"queue": "sla_monitor"},
        "dispatch.*": {"queue": "dispatch"},
        "ml.*": {"queue": "ml"},
        "marketing.*": {"queue": "marketing"},
    },
    beat_schedule={
        "sla-monitor-tick": {
            "task": "sla.monitor_tick",
            "schedule": 60.0,  # every 60 seconds
        },
        "nightly-forecast-all-tenants": {
            "task": "ml.forecast_all_tenants",
            "schedule": crontab(hour=2, minute=0),  # 2am Asia/Dubai
        },
        "nightly-marketing-campaigns": {
            "task": "marketing.send_scheduled_campaigns",
            "schedule": crontab(hour=9, minute=0),  # 9am when UAE window opens
        },
    },
)
celery_app.autodiscover_tasks(
    ["app.outbox", "app.sla", "app.predictions", "app.marketing"],
    related_name="worker",
)
