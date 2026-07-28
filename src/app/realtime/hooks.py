"""Queue realtime events during a transaction, emit them after it commits.

The ordering FSM and table service mutate rows and leave the commit to their
caller. Publishing at the point of mutation would therefore tell terminals to
refetch while the write is still uncommitted — they would race the transaction
and often re-read the OLD row, which is worse than not pushing at all because
the screen then looks updated and is not.

So events are parked on the session and flushed from SQLAlchemy's ``after_commit``
hook. If the transaction rolls back the events die with it, which is exactly
right: nothing changed, so nothing should be announced.
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.realtime.bus import publish

logger = logging.getLogger(__name__)

_KEY = "realtime_events"


def queue_event(session, restaurant_id: int | None, topic: str, **fields) -> None:
    """Record a change to announce once the current transaction commits.

    Accepts an AsyncSession or a sync Session. Silently ignores a missing
    restaurant_id rather than guessing: an event on the wrong channel would
    reach another branch's terminals.
    """
    if restaurant_id is None:
        return
    info = getattr(session, "info", None)
    if info is None:  # pragma: no cover — every SQLAlchemy session has .info
        return
    pending = info.setdefault(_KEY, [])
    entry = (int(restaurant_id), topic, fields)
    # Collapse duplicates: one request can touch several rows of the same topic
    # (an order plus its table), and the terminal refetches the same list either
    # way, so N identical events would be N redundant round trips per terminal.
    if entry not in pending:
        pending.append(entry)


@event.listens_for(Session, "after_commit")
def _flush_after_commit(session: Session) -> None:
    pending = session.info.pop(_KEY, None)
    if not pending:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # A sync commit outside the event loop (scripts, some Celery paths).
        # Nothing to push to; terminals fall back to their poll.
        logger.debug("realtime: %d event(s) dropped, no running loop", len(pending))
        return
    for restaurant_id, topic, fields in pending:
        # Fire and forget on purpose: the write is already durable, and awaiting
        # a publish here would put Redis latency on the caller's response path.
        task = loop.create_task(publish(restaurant_id, topic, **fields))
        # Without a reference the loop may garbage-collect the task mid-flight.
        _in_flight.add(task)
        task.add_done_callback(_in_flight.discard)


#: Strong references to in-flight publishes; see the comment above.
_in_flight: set[asyncio.Task] = set()
