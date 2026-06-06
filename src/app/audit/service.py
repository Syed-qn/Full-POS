# src/app/audit/service.py
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog


async def record_audit(
    session: AsyncSession,
    *,
    actor: str,
    entity: str,
    entity_id: str,
    action: str,
    restaurant_id: int | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> AuditLog:
    row = AuditLog(
        actor=actor,
        restaurant_id=restaurant_id,
        entity=entity,
        entity_id=entity_id,
        action=action,
        before=before,
        after=after,
    )
    session.add(row)
    return row
