"""Serve marketing media (template header images) from Postgres at ``/media/<path>``.

Images are stored in the ``marketing_media`` table (see models.MarketingMedia) so
they survive redeploys on ephemeral-disk hosts. For backward compatibility this
route also falls back to a file on local disk if a DB row is not found (covers
any legacy uploads written before the DB migration, and local-dev files).
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.marketing.models import MarketingMedia

router = APIRouter(tags=["media"])

_CACHE_HEADERS = {"Cache-Control": "public, max-age=31536000, immutable"}


@router.get("/media/{path:path}")
async def serve_media(
    path: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    row = (
        await session.scalars(
            select(MarketingMedia).where(MarketingMedia.path == path)
        )
    ).first()
    if row is not None:
        return Response(
            content=row.data,
            media_type=row.content_type,
            headers=_CACHE_HEADERS,
        )
    # Legacy / local-dev fallback: a file written to the upload dir before the
    # DB-backed store existed. Guard against path traversal.
    upload_dir = os.path.abspath(get_settings().upload_dir)
    candidate = os.path.abspath(os.path.join(upload_dir, path))
    if candidate.startswith(upload_dir + os.sep) and os.path.isfile(candidate):
        return FileResponse(candidate, headers=_CACHE_HEADERS)
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
