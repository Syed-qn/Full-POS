"""POS integration HTTP API (config + manual sync). Thin layer over the sync service."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.pos.cratis import PosFetchError
from app.pos.sync_service import PosConfigError, sync_menu_from_pos

router = APIRouter(prefix="/api/v1/pos", tags=["pos"])


class PosConfigOut(BaseModel):
    pos_enabled: bool
    pos_account: str
    pos_location: str
    pos_base_url: str | None = None


class PosConfigIn(BaseModel):
    pos_enabled: bool | None = None
    pos_account: str | None = None
    pos_location: str | None = None
    pos_base_url: str | None = None


class PosSyncOut(BaseModel):
    fetched: int
    created: int
    updated: int
    deactivated: int
    images: int
    skipped_empty: bool
    errors: list[str] = []


class PosSyncAccepted(BaseModel):
    """Returned when a full sync is kicked off in the background (202)."""
    started: bool = True
    mode: str  # "celery" | "inprocess"
    detail: str


class PosSyncStatusOut(BaseModel):
    """Last background-sync breadcrumb (state machine: idle/running/done/error)."""
    state: str = "idle"
    started_at: str | None = None
    finished_at: str | None = None
    fetched: int | None = None
    created: int | None = None
    updated: int | None = None
    deactivated: int | None = None
    images: int | None = None
    skipped_empty: bool | None = None
    error: str | None = None


def _config_out(rest: Restaurant) -> PosConfigOut:
    s = rest.settings or {}
    return PosConfigOut(
        pos_enabled=bool(s.get("pos_enabled")),
        pos_account=(s.get("pos_account") or ""),
        pos_location=(s.get("pos_location") or ""),
        pos_base_url=(s.get("pos_base_url") or None),
    )


@router.get("/config", response_model=PosConfigOut)
async def get_pos_config(restaurant: Restaurant = Depends(current_restaurant)):
    return _config_out(restaurant)


@router.patch("/config", response_model=PosConfigOut)
async def patch_pos_config(
    body: PosConfigIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    settings = dict(restaurant.settings or {})
    for key in ("pos_enabled", "pos_account", "pos_location", "pos_base_url"):
        val = getattr(body, key)
        if val is not None:
            settings[key] = val.strip() if isinstance(val, str) else val
    restaurant.settings = settings
    await session.commit()
    await session.refresh(restaurant)
    return _config_out(restaurant)


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED, response_model=PosSyncAccepted)
async def sync_pos(
    background_tasks: BackgroundTasks,
    restaurant: Restaurant = Depends(current_restaurant),
):
    """Kick off the FULL POS sync in the background (586 dishes, image generation, Meta
    push) so it never blocks/times out the request. Hands off to the Celery worker when
    one is running, else runs in-process after the response. Poll GET /sync/status."""
    # Fail fast on a misconfigured restaurant so the manager gets an immediate 422
    # instead of a silently-failing background job.
    s = restaurant.settings or {}
    if not (s.get("pos_account") and s.get("pos_location")):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Set the POS account and location before syncing.",
        )

    restaurant_id = restaurant.id
    # APP_OUTBOX_SYNC_DELIVERY is our "no Celery worker is running" signal (e.g. Render
    # free tier). When a worker exists, hand off to the queue; otherwise run in-process.
    if get_settings().outbox_sync_delivery:
        from app.pos.worker import run_pos_sync

        background_tasks.add_task(run_pos_sync, restaurant_id, publish=True)
        return PosSyncAccepted(mode="inprocess", detail="Sync started. Refresh in a minute.")

    from app.pos.worker import sync_pos_menu_task

    sync_pos_menu_task.apply_async(args=[restaurant_id], kwargs={"publish": True},
                                   queue="maintenance")
    return PosSyncAccepted(mode="celery", detail="Sync queued. Refresh in a minute.")


@router.post("/sync/inline", response_model=PosSyncOut)
async def sync_pos_inline(
    limit: int | None = None,
    publish: bool = True,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """Synchronous sync, blocking until done. Use only for SMALL/validation runs
    (pass ?limit=N) — a full pull will time out. The full pull goes through POST /sync."""
    try:
        result = await sync_menu_from_pos(
            session, restaurant_id=restaurant.id, limit=limit, publish=publish
        )
    except PosConfigError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    except PosFetchError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"POS sync failed: {exc}")
    await session.commit()
    return PosSyncOut(
        fetched=result.fetched, created=result.created, updated=result.updated,
        deactivated=result.deactivated, images=result.images,
        skipped_empty=result.skipped_empty, errors=result.errors,
    )


@router.get("/sync/status", response_model=PosSyncStatusOut)
async def sync_pos_status(restaurant: Restaurant = Depends(current_restaurant)):
    """Poll the last background-sync breadcrumb (set by the POS worker)."""
    last = (restaurant.settings or {}).get("pos_last_sync") or {}
    return PosSyncStatusOut(**{**{"state": "idle"}, **last})
