"""Branch-scoped event bus for pushing changes to open terminals.

Why this exists: a cashier terminal used to poll every 15 seconds, so a table a
waiter seated on another till took up to 15s to appear. Pushing instead of
polling makes it immediate AND cheaper, because an idle terminal now costs one
parked connection rather than a database query every few seconds per terminal.

Two backends, chosen at runtime:

* **Redis pub/sub** when a client is installed. Required whenever more than one
  worker process serves the app, since a terminal streaming from worker A must
  see a change written by worker B.
* **In-process fan-out** otherwise, so dev, tests and single-worker deploys work
  with no Redis at all. It is correct for one process and silently wrong for
  several, which is exactly why the Redis path exists.

Events carry no order or table CONTENT — only "something in this area changed".
Terminals re-fetch through their normal authenticated endpoints, so the stream
can never become a way to read data the caller could not already read, and a
missed event is repaired by the next fetch rather than leaving a stale screen.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

logger = logging.getLogger(__name__)

#: Channel per restaurant. A branch only ever hears its own traffic — the
#: subscriber is built from the caller's token, never from a client-supplied id.
_CHANNEL_PREFIX = "rt:"

#: What a terminal may be told changed. Deliberately coarse: a handful of
#: topics a screen can map to "refetch this list", not a per-field diff.
TOPICS = ("orders", "tables", "kds")

_redis_client: Any = None

#: In-process subscribers: restaurant_id -> set of queues.
_local: dict[int, set[asyncio.Queue]] = {}

#: Bounded so one wedged terminal cannot grow a queue without limit. Dropping
#: the oldest event is safe here precisely because events carry no content: the
#: terminal still refetches on the next one, or on its fallback poll.
_QUEUE_MAX = 64


def set_realtime_redis(client: Any) -> None:
    """Install the shared Redis client. Called once from the app lifespan."""
    global _redis_client
    _redis_client = client


def realtime_backend() -> str:
    """"redis" or "memory" — surfaced on the stream so a multi-worker deploy
    running without Redis is visible rather than mysteriously partial."""
    return "redis" if _redis_client is not None else "memory"


def channel_for(restaurant_id: int) -> str:
    return f"{_CHANNEL_PREFIX}{int(restaurant_id)}"


async def publish(restaurant_id: int, topic: str, **fields: Any) -> None:
    """Announce a change to every terminal of ``restaurant_id``.

    Never raises. This is called from inside request handlers that have already
    done the real work — a dead Redis must not turn a successful order into a
    500. A dropped event costs one screen a few seconds of staleness until its
    fallback poll; a raised one costs the customer their order.
    """
    if topic not in TOPICS:  # programming error, not a runtime condition
        raise ValueError(f"unknown realtime topic {topic!r}; expected one of {TOPICS}")
    event = {"topic": topic, "restaurant_id": int(restaurant_id), **fields}
    try:
        if _redis_client is not None:
            await _redis_client.publish(channel_for(restaurant_id), json.dumps(event))
            return
        for q in tuple(_local.get(int(restaurant_id), ())):
            if q.full():
                # Make room rather than block the request that triggered this.
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(event)
    except Exception:  # noqa: BLE001 — a broken bus must never break the write
        logger.warning("realtime publish failed (topic=%s)", topic, exc_info=True)


async def subscribe(restaurant_id: int) -> AsyncIterator[dict]:
    """Yield events for one restaurant until the caller stops iterating."""
    rid = int(restaurant_id)
    if _redis_client is not None:
        pubsub = _redis_client.pubsub()
        await pubsub.subscribe(channel_for(rid))
        try:
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                try:
                    yield json.loads(msg["data"])
                except (TypeError, ValueError):
                    logger.warning("realtime: undecodable event dropped")
        finally:
            # Always release the channel — a leaked subscription holds a Redis
            # connection open for the life of the process.
            try:
                await pubsub.unsubscribe(channel_for(rid))
                await pubsub.aclose()
            except Exception:  # noqa: BLE001
                logger.debug("realtime: pubsub cleanup failed", exc_info=True)
        return

    q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAX)
    _local.setdefault(rid, set()).add(q)
    try:
        while True:
            yield await q.get()
    finally:
        subs = _local.get(rid)
        if subs is not None:
            subs.discard(q)
            if not subs:
                _local.pop(rid, None)


def local_subscriber_count(restaurant_id: int) -> int:
    """Test seam: how many in-process subscribers a restaurant has."""
    return len(_local.get(int(restaurant_id), ()))
