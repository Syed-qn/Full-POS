import datetime as dt
import pytest
from sqlalchemy import select
from app.webhook.models import WebhookEvent


@pytest.mark.asyncio
async def test_processed_at_is_datetime(db_session):
    ev = WebhookEvent(
        provider_event_id="evt-proc-type-check",
        payload={"x": 1},
        processed_at=dt.datetime.now(dt.timezone.utc),
    )
    db_session.add(ev)
    await db_session.flush()
    row = (
        await db_session.execute(
            select(WebhookEvent).where(WebhookEvent.provider_event_id == "evt-proc-type-check")
        )
    ).scalar_one()
    assert isinstance(row.processed_at, dt.datetime)
    assert row.processed_at.tzinfo is not None
