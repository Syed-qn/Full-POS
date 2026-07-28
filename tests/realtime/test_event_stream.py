"""The live stream that replaced polling on the tills.

Two properties matter more than the plumbing: a terminal must only ever hear its
OWN branch, and a failure in the bus must never break the order that triggered
it — a dead Redis costs a few seconds of staleness, a raised exception costs the
customer their order.
"""
import asyncio
import contextlib

import pytest

from app.realtime import bus


async def _stop(sub, pending=None):
    """Cancel any in-flight read, then close the generator.

    aclose() on a generator that is still suspended inside __anext__ raises
    "already running", so the pending read has to be cancelled and awaited
    first.
    """
    if pending is not None:
        pending.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pending
    with contextlib.suppress(RuntimeError):
        await sub.aclose()


@pytest.fixture(autouse=True)
def _memory_backend():
    """Force the in-process backend; these tests are about behaviour, not Redis."""
    bus.set_realtime_redis(None)
    bus._local.clear()
    yield
    bus._local.clear()


@pytest.mark.anyio
async def test_event_reaches_only_its_own_branch():
    """The whole isolation story. Branch 1's till must not learn that branch 2
    seated a table — the channel is built from the caller's token, and this is
    what proves that separation is real rather than assumed."""
    mine = bus.subscribe(1)
    theirs = bus.subscribe(2)
    # Start both subscriptions before publishing.
    mine_next = asyncio.ensure_future(mine.__anext__())
    theirs_next = asyncio.ensure_future(theirs.__anext__())
    await asyncio.sleep(0)

    await bus.publish(1, "tables", table_id=7)

    got = await asyncio.wait_for(mine_next, timeout=2)
    assert got == {"topic": "tables", "restaurant_id": 1, "table_id": 7}
    assert not theirs_next.done(), "branch 2 heard branch 1's event"

    await _stop(theirs, theirs_next)
    await _stop(mine)


@pytest.mark.anyio
async def test_publish_never_raises_into_the_caller():
    """publish() runs inside request handlers that have already done the real
    work. A broken bus must degrade to staleness, not to a 500."""

    class Broken:
        def publish(self, *a, **k):
            raise RuntimeError("redis is down")

        def pubsub(self):  # pragma: no cover — not reached here
            raise RuntimeError("redis is down")

    bus.set_realtime_redis(Broken())
    try:
        await bus.publish(1, "orders", order_id=5)  # must not raise
    finally:
        bus.set_realtime_redis(None)


@pytest.mark.anyio
async def test_unknown_topic_is_a_programming_error():
    """Topics are a closed set. A typo should fail loudly in development, not
    publish an event no screen listens for."""
    with pytest.raises(ValueError, match="unknown realtime topic"):
        await bus.publish(1, "tabels")


@pytest.mark.anyio
async def test_slow_terminal_cannot_grow_a_queue_without_limit():
    """A wedged till must not become a memory leak. Events carry no content, so
    dropping the oldest is safe: the terminal refetches on the next one."""
    sub = bus.subscribe(1)
    # Drive one event through so the generator is suspended at its yield with
    # the queue registered. Cancelling the first read instead would unwind the
    # generator and deregister the subscriber, leaving nothing to measure.
    first = asyncio.ensure_future(sub.__anext__())
    await asyncio.sleep(0)
    await bus.publish(1, "orders", order_id=-1)
    await asyncio.wait_for(first, timeout=2)

    # Nobody reads from here on: the queue must stop growing, not grow forever.
    for i in range(bus._QUEUE_MAX * 3):
        await bus.publish(1, "orders", order_id=i)

    (q,) = tuple(bus._local[1])
    assert q.qsize() <= bus._QUEUE_MAX
    await _stop(sub)


@pytest.mark.anyio
async def test_subscriber_is_removed_when_it_stops_listening():
    """A leaked subscriber holds a queue (and, on Redis, a connection) for the
    life of the process."""
    sub = bus.subscribe(3)
    fut = asyncio.ensure_future(sub.__anext__())
    await asyncio.sleep(0)
    await bus.publish(3, "tables")
    await asyncio.wait_for(fut, timeout=2)
    assert bus.local_subscriber_count(3) == 1

    await _stop(sub)
    assert bus.local_subscriber_count(3) == 0


@pytest.mark.anyio
async def test_stream_endpoint_requires_authentication(client):
    resp = await client.get("/api/v1/events/stream")
    assert resp.status_code == 401
