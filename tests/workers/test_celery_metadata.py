"""Regression: the Celery worker process must register ALL model metadata.

deliver_outbox_message touches OutboxMessage, whose restaurant_id is a FK to
restaurants.id. If the worker entrypoint (apps.workers.celery_app) does not import
the Restaurant model (and its siblings), SQLAlchemy cannot resolve that FK at
commit time and raises NoReferencedTableError — provider.send() has already gone
out, the status write fails, Celery retries, and the customer receives DUPLICATE
WhatsApp messages. This guards the import block in celery_app.py.
"""

from sqlalchemy.orm import configure_mappers

import apps.workers.celery_app  # noqa: F401  (must import all models as a side effect)
from app.outbox.models import OutboxMessage


def test_worker_registers_restaurants_table_for_outbox_fk() -> None:
    # Would raise NoReferencedTableError if the worker hadn't imported Restaurant.
    configure_mappers()

    metadata = OutboxMessage.__table__.metadata
    assert "restaurants" in metadata.tables, (
        "restaurants table not registered — importing apps.workers.celery_app must "
        "import the Restaurant model so OutboxMessage.restaurant_id FK resolves"
    )

    fk_targets = {
        fk.target_fullname
        for col in OutboxMessage.__table__.columns
        for fk in col.foreign_keys
    }
    assert "restaurants.id" in fk_targets
