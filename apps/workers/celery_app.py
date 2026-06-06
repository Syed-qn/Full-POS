# apps/workers/celery_app.py
from celery import Celery

from app.config import get_settings

settings = get_settings()
celery_app = Celery(
    "restaurant",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(task_default_queue="default", timezone="Asia/Dubai")
