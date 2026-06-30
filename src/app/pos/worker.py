"""Background POS menu sync — runs the heavy full pull off the HTTP request thread.

A full HNC pull is ~586 dishes: 586 name-based image generations + DB writes + one
Meta items_batch push. That can take minutes, far past an HTTP/Render request timeout,
so it must run in the background.

Two execution paths, mirroring the outbox pattern:
  * Celery worker present  -> ``sync_pos_menu_task.apply_async`` (this module's shared_task).
  * No worker (Render free tier, APP_OUTBOX_SYNC_DELIVERY=true) -> FastAPI BackgroundTasks
    awaits ``run_pos_sync`` in-process after the response is sent.

Either way the work funnels through :func:`run_pos_sync`, which opens its OWN session and
records a progress/result breadcrumb in ``restaurant.settings['pos_last_sync']`` so the
manager UI can poll for "running -> done/error" without holding the request open.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from celery import shared_task

logger = logging.getLogger(__name__)

_DUBAI = ZoneInfo("Asia/Dubai")


def _now_iso() -> str:
    return datetime.now(_DUBAI).isoformat(timespec="seconds")


def _default_factory():
    from app.db import async_session_factory

    return async_session_factory


async def _set_status(restaurant_id: int, status: dict, *, session_factory=None) -> None:
    """Persist a small sync breadcrumb on the restaurant in its own transaction."""
    from app.identity.models import Restaurant

    factory = session_factory or _default_factory()
    async with factory() as session:
        rest = await session.get(Restaurant, restaurant_id)
        if rest is None:
            return
        settings = dict(rest.settings or {})
        settings["pos_last_sync"] = status
        rest.settings = settings
        await session.commit()


async def run_pos_sync(
    restaurant_id: int, *, publish: bool = True, session_factory=None, provider=None
) -> dict:
    """Run a full POS sync in a fresh session and record status. Never raises — the
    failure is captured in the ``pos_last_sync`` breadcrumb so callers (Celery or a
    fire-and-forget BackgroundTask) don't crash the worker/request.

    ``session_factory``/``provider`` are injection points for tests; production (and the
    Celery path) leave them None so the real session factory + Cratis provider are used."""
    from app.pos.sync_service import PosConfigError, sync_menu_from_pos

    factory = session_factory or _default_factory()
    await _set_status(restaurant_id, {"state": "running", "started_at": _now_iso()},
                      session_factory=factory)
    try:
        async with factory() as session:
            result = await sync_menu_from_pos(
                session, restaurant_id=restaurant_id, publish=publish, provider=provider
            )
        status = {
            "state": "done",
            "finished_at": _now_iso(),
            "fetched": result.fetched,
            "created": result.created,
            "updated": result.updated,
            "deactivated": result.deactivated,
            "images": result.images,
            "skipped_empty": result.skipped_empty,
        }
        await _set_status(restaurant_id, status, session_factory=factory)
        logger.info("POS background sync done (restaurant %s): %s", restaurant_id, status)
        return status
    except PosConfigError as exc:
        status = {"state": "error", "finished_at": _now_iso(), "error": str(exc)}
        await _set_status(restaurant_id, status, session_factory=factory)
        return status
    except Exception as exc:  # noqa: BLE001 - keep the breadcrumb, never crash the runner
        logger.exception("POS background sync failed (restaurant %s)", restaurant_id)
        status = {"state": "error", "finished_at": _now_iso(), "error": str(exc)}
        await _set_status(restaurant_id, status, session_factory=factory)
        return status


@shared_task(name="pos.sync_menu", bind=True, max_retries=0)
def sync_pos_menu_task(self, restaurant_id: int, publish: bool = True) -> dict:  # type: ignore[override]
    """Celery entrypoint for the full POS sync (used when a worker is running)."""
    return asyncio.run(run_pos_sync(restaurant_id, publish=publish))
