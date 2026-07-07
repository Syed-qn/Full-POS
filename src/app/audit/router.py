# src/app/audit/router.py
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.backup_status import backup_readiness
from app.audit.service import list_audit_log
from app.db import get_session
from app.staff.deps import require_role

router = APIRouter(prefix="/api/v1/audit-log", tags=["audit"])


@router.get("")
async def audit_log(
    start_date: date | None = None,
    end_date: date | None = None,
    entity: str | None = None,
    action: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    rows = await list_audit_log(
        session,
        restaurant_id=restaurant.id,
        start_date=start_date,
        end_date=end_date,
        entity=entity,
        action=action,
        limit=limit,
    )
    return {
        "rows": [
            {
                "id": r.id,
                "actor": r.actor,
                "restaurant_id": r.restaurant_id,
                "entity": r.entity,
                "entity_id": r.entity_id,
                "action": r.action,
                "before": r.before,
                "after": r.after,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


@router.get("/backup-readiness")
async def audit_log_backup_readiness(
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    return await backup_readiness(session, restaurant_id=restaurant.id)
