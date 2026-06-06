from celery import Celery

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
    },
    beat_schedule={
        "sla-monitor-tick": {
            "task": "sla.monitor_tick",
            "schedule": 60.0,  # every 60 seconds
        },
    },
)
celery_app.autodiscover_tasks(
    ["app.outbox", "app.sla"],
    related_name="worker",
)
