# src/app/audit/service.py
from datetime import date, datetime, time

from sqlalchemy import select
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
    """Add an audit row to the caller's transaction. The caller MUST commit (or flush) — record_audit never commits."""
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


async def list_audit_log(
    session: AsyncSession,
    *,
    restaurant_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    entity: str | None = None,
    action: str | None = None,
    limit: int = 50,
) -> list[AuditLog]:
    """Query the append-only audit log for a tenant, newest first.

    Read-only admin surface over `record_audit` writes — used by the
    admin activity-log endpoint, never by production business logic.
    """
    stmt = select(AuditLog).where(AuditLog.restaurant_id == restaurant_id)
    if start_date is not None:
        stmt = stmt.where(AuditLog.created_at >= datetime.combine(start_date, time.min))
    if end_date is not None:
        stmt = stmt.where(AuditLog.created_at <= datetime.combine(end_date, time.max))
    if entity is not None:
        stmt = stmt.where(AuditLog.entity == entity)
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit)

    result = await session.execute(stmt)
    return list(result.scalars().all())
