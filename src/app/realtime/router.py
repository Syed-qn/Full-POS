"""Server-sent event stream: one parked connection per terminal.

Deliberately SSE over WebSocket. The traffic is entirely server-to-terminal, so
the duplex half of a socket would go unused while costing a dependency, its own
reconnect and auth handling, and worse behaviour through proxies. SSE is plain
HTTP: it survives the same infrastructure every other endpoint already crosses.

The browser's native ``EventSource`` cannot set an Authorization header, and the
one workaround is putting the token in the query string — where it lands in
access logs and browser history. The frontend therefore reads this with ``fetch``
and a stream reader instead, which carries the normal bearer header.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.identity.models import Restaurant
from app.realtime.bus import realtime_backend, subscribe
from app.staff.deps import current_restaurant_any

router = APIRouter(prefix="/api/v1/events", tags=["realtime"])

logger = logging.getLogger(__name__)

#: Idle ping. Proxies and load balancers close a silent connection (commonly at
#: 60s), and the client cannot tell "quiet restaurant" from "dead socket"
#: without traffic. A comment line is the cheapest legal SSE keepalive.
_HEARTBEAT_SECONDS = 20.0


def _frame(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.get("/stream")
async def stream(
    request: Request,
    restaurant: Restaurant = Depends(current_restaurant_any),
) -> StreamingResponse:
    """Live changes for the caller's branch.

    Open to ANY authenticated actor of the restaurant — cashier, waiter and
    kitchen all need it, and it is the reason they stop polling. That grants no
    new reach: an event says only which topic changed, and the terminal still
    refetches through the endpoints its own role already allows.

    The branch comes from the token, never from a parameter, so a terminal
    cannot listen to another restaurant by asking.
    """
    restaurant_id = restaurant.id

    async def gen() -> AsyncIterator[str]:
        # Announce the backend up front: "memory" across multiple workers means
        # events only reach terminals attached to the same process, and that is
        # far better seen than silently half-working.
        yield _frame("ready", {"restaurant_id": restaurant_id, "backend": realtime_backend()})
        events = subscribe(restaurant_id)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(
                        events.__anext__(), timeout=_HEARTBEAT_SECONDS
                    )
                except asyncio.TimeoutError:
                    # Quiet branch: prove the connection is alive.
                    yield ": keepalive\n\n"
                    continue
                except StopAsyncIteration:
                    break
                yield _frame("change", event)
        except asyncio.CancelledError:
            # Terminal navigated away or the server is shutting down. Expected.
            raise
        finally:
            # Close the generator so the Redis subscription is released even
            # when the client vanishes mid-stream.
            await events.aclose()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            # nginx buffers proxied responses by default, which holds events
            # until the buffer fills — the exact opposite of the point.
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
