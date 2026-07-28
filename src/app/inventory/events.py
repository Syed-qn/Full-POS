"""Announce inventory writes to this branch's open terminals.

The Inventory screen used to carry a Refresh button, which is a way of telling
the person at the till to notice that the page is out of date. It now listens on
the realtime stream instead, so a stock move made on one terminal lands on the
others without anybody pressing anything.

The announcement has to happen AFTER the commit, or a terminal would refetch
while the write is still in flight and re-read the old row — a screen that looks
refreshed and is wrong. ``queue_event`` parks the event on the session and the
``after_commit`` hook in app.realtime.hooks flushes it, so a rollback discards
it, which is right: nothing changed, so nothing is announced.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.realtime.hooks import queue_event


async def _commit_and_announce(session: AsyncSession, restaurant_id: int) -> None:
    """Commit the current transaction and tell the branch its stock moved.

    Deliberately NOT used on read paths that happen to commit (``GET
    /locations`` commits after seeding the default stock areas). Announcing
    there would make every terminal's refetch trigger another announcement.
    """
    queue_event(session, restaurant_id, "inventory")
    await session.commit()
