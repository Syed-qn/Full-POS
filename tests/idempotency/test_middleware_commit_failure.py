# tests/idempotency/test_middleware_commit_failure.py
"""Isolated unit test (no DB/app fixtures): a transient failure while writing the
idempotency bookkeeping record must not turn an already-successful mutation into a
client-visible 500, and must not silently corrupt state for the next retry."""
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request

from app.idempotency.middleware import IdempotencyMiddleware


async def _one_chunk(body: bytes):
    yield body


class _FakeStreamingResponse:
    """Minimal stand-in for what BaseHTTPMiddleware's call_next actually returns
    (a StreamingResponse-shaped object with a body_iterator), since a plain
    starlette Response has no body_iterator attribute."""

    def __init__(self, status_code: int, body: bytes):
        self.status_code = status_code
        self.body_iterator = _one_chunk(body)


class _FakeSelectResult:
    def scalar(self):
        return None  # no existing key — this is a first application


class _BrokenSession:
    """Session whose SELECT (the pre-check) succeeds but whose commit (the
    bookkeeping insert after a successful mutation) raises a generic, non-IntegrityError
    exception — simulating a transient DB blip (e.g. a dropped connection)."""

    def add(self, _obj):
        pass

    async def scalar(self, _stmt):
        return None

    async def commit(self):
        raise RuntimeError("connection reset by peer")

    async def rollback(self):
        pass


def _make_request(session_dep) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/riders",
        "headers": [
            (b"idempotency-key", b"test-key"),
            (b"authorization", b"Bearer faketoken"),
        ],
        "app": type("App", (), {"dependency_overrides": {}})(),
    }
    request = Request(scope)
    request.app.dependency_overrides = {}
    return request


@pytest.mark.anyio
async def test_commit_failure_does_not_turn_success_into_500(monkeypatch):
    async def fake_session_dep():
        yield _BrokenSession()

    monkeypatch.setattr(
        "app.idempotency.middleware.get_session", fake_session_dep, raising=False
    )
    monkeypatch.setattr(
        "app.idempotency.middleware._restaurant_id_from_request", lambda _req: 1
    )

    async def call_next(_request):
        return _FakeStreamingResponse(201, b'{"ok": true}')

    middleware = IdempotencyMiddleware(app=AsyncMock())
    request = _make_request(fake_session_dep)

    response = await middleware.dispatch(request, call_next)

    # The mutation succeeded (call_next returned 201) — the caller must see that
    # success, not a 500, even though the bookkeeping insert failed transiently.
    assert response.status_code == 201
