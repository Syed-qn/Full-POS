"""POS integration HTTP API (config + manual sync). Thin layer over the sync service."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

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


@router.post("/sync", response_model=PosSyncOut)
async def sync_pos(
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        result = await sync_menu_from_pos(session, restaurant_id=restaurant.id)
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
