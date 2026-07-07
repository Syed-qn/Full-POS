# src/app/idempotency/middleware.py
"""Dedupe replayed mutating requests carrying an ``Idempotency-Key`` header.

Scoped by (restaurant_id, key, method, path) — a retried desktop-shell sync op
after a dropped connection replays the exact same call and must get back the
original response, never re-apply the mutation.

Deviation from the illustrative brief: the tenant (``restaurant_id``) is
resolved here by decoding the bearer JWT directly via
``identity.auth.decode_access_token``, not by reading ``request.state`` set by
the ``current_restaurant`` FastAPI dependency. ``BaseHTTPMiddleware.dispatch``
runs the "check for an existing key" branch *before* ``call_next`` — at that
point route dependencies (including ``current_restaurant``) have not run yet,
so ``request.state`` would never be populated in time for the pre-check. The
JWT is already the single source of truth for the tenant id (see
``identity/deps.py:current_restaurant``), so decoding it directly here avoids
that ordering problem entirely and needs no change to ``identity/deps.py``.

Similarly, the DB session is obtained via ``request.app.dependency_overrides``
(falling back to the real ``get_session``) rather than a fixed module-level
session factory. Tests override ``get_session`` to hand back a single
per-test, savepoint-scoped session (see ``tests/conftest.py``); a middleware
bound to ``app.db.async_session_factory`` would open a second, unrelated
connection that can't see uncommitted rows from that savepoint and would trip
the ``restaurant_id`` foreign key. Going through the same override keeps the
middleware inside the test's transaction like every route handler.
"""
import logging
from contextlib import asynccontextmanager

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.db import get_session
from app.identity.auth import decode_access_token
from app.idempotency.models import IdempotencyKey

logger = logging.getLogger(__name__)

_MUTATING_METHODS = {"POST", "PATCH", "PUT", "DELETE"}


def _restaurant_id_from_request(request: Request) -> int | None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    try:
        return decode_access_token(auth.removeprefix("Bearer ").strip())
    except ValueError:
        return None


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        key = request.headers.get("Idempotency-Key")
        if key is None or request.method not in _MUTATING_METHODS:
            return await call_next(request)

        restaurant_id = _restaurant_id_from_request(request)
        if restaurant_id is None:
            # No resolvable tenant (missing/invalid token) — let the route's own
            # auth dependency reject it as usual; nothing to dedup against.
            return await call_next(request)

        method = request.method
        path = request.url.path
        session_dep = request.app.dependency_overrides.get(get_session, get_session)

        async with asynccontextmanager(session_dep)() as session:
            existing = await session.scalar(
                select(IdempotencyKey).where(
                    IdempotencyKey.restaurant_id == restaurant_id,
                    IdempotencyKey.key == key,
                    IdempotencyKey.method == method,
                    IdempotencyKey.path == path,
                )
            )
            if existing is not None:
                return Response(
                    content=existing.response_body,
                    status_code=existing.response_status,
                    media_type="application/json",
                )

        response = await call_next(request)

        if 200 <= response.status_code < 300:
            body_chunks = [chunk async for chunk in response.body_iterator]
            body = b"".join(body_chunks)
            response.body_iterator = _aiter([body])

            try:
                async with asynccontextmanager(session_dep)() as session:
                    session.add(
                        IdempotencyKey(
                            restaurant_id=restaurant_id,
                            key=key,
                            method=method,
                            path=path,
                            response_status=response.status_code,
                            response_body=body.decode(),
                        )
                    )
                    try:
                        await session.commit()
                    except IntegrityError:
                        # Concurrent duplicate: another in-flight request for the same
                        # (restaurant_id, key, method, path) won the race and already
                        # inserted a row. Our own response is still a valid first
                        # application of the mutation (we didn't replay anything) —
                        # just let it through unmodified rather than erroring the caller.
                        await session.rollback()
            except Exception:
                # The mutation itself already succeeded (call_next returned 2xx) —
                # a transient failure recording the dedup bookkeeping (e.g. a dropped
                # DB connection) must never turn a completed mutation into a
                # client-visible 500. Worst case: this one write isn't deduped against
                # on a future retry, which is strictly better than either erroring a
                # succeeded request or silently double-applying it.
                logger.exception(
                    "idempotency bookkeeping write failed after a successful mutation "
                    "(restaurant_id=%s, method=%s, path=%s) — returning the original "
                    "response anyway",
                    restaurant_id,
                    method,
                    path,
                )

        return response


async def _aiter(chunks):
    for chunk in chunks:
        yield chunk
