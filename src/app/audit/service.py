# src/app/audit/service.py
from datetime import date, datetime, time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.context import get_actor_staff_id
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
    actor_staff_id: int | None = None,
) -> AuditLog:
    """Add an audit row to the caller's transaction. The caller MUST commit (or flush) — record_audit never commits.

    ``actor_staff_id`` defaults to whoever's staff token made this request (see
    app.audit.context) so callers do not have to thread it through.
    """
    if actor_staff_id is None:
        actor_staff_id = get_actor_staff_id()
    row = AuditLog(
        actor=actor,
        actor_staff_id=actor_staff_id,
        restaurant_id=restaurant_id,
        entity=entity,
        entity_id=entity_id,
        action=action,
        before=before,
        after=after,
    )
    session.add(row)
    return row


#: Never surfaced in a diff. Either noise (timestamps that move on every write)
#: or secrets that have no business being re-displayed on an admin screen.
_DIFF_SKIP = frozenset(
    {
        "updated_at",
        "created_at",
        "password",
        "password_hash",
        "pin",
        "pin_hash",
        "token",
        "access_token",
        "api_key",
        "asp_api_key",
        "secret",
    }
)


def _short(value) -> str:
    """One-line rendering of a JSON value for a table cell."""
    if value is None:
        return "empty"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, dict)):
        n = len(value)
        kind = "items" if isinstance(value, list) else "fields"
        return f"{n} {kind}"
    text = str(value)
    return text if len(text) <= 40 else f"{text[:39]}…"


def diff_fields(before: dict | None, after: dict | None) -> list[dict]:
    """The fields that actually changed, as {field, from, to}.

    `before` and `after` were recorded on every audit row from the start and
    never sent to any screen, so the log could say "manager changed dish 12" but
    not "from 26.00 to 18.00" — the half of the row worth reading stayed in the
    database. Computed server-side so every client renders the same answer.

    A create has no `before` and a delete no `after`; both return an empty list
    rather than every field marked changed, since "all of them" is not a diff.
    """
    if not isinstance(before, dict) or not isinstance(after, dict):
        return []
    out: list[dict] = []
    for key in sorted(set(before) | set(after)):
        if key in _DIFF_SKIP:
            continue
        old, new = before.get(key), after.get(key)
        if old == new:
            continue
        out.append({"field": key, "from": _short(old), "to": _short(new)})
    return out


async def staff_names(
    session: AsyncSession, *, restaurant_id: int, staff_ids: set[int]
) -> dict[int, str]:
    """id -> name for the given staff, scoped to the tenant.

    Deliberately tolerant of missing rows: the audit log is append-only and
    outlives the staff records it references, so a departed employee's id simply
    has no name rather than breaking the page.
    """
    if not staff_ids:
        return {}
    from app.staff.models import StaffMember

    rows = (
        await session.execute(
            select(StaffMember.id, StaffMember.name).where(
                StaffMember.restaurant_id == restaurant_id,
                StaffMember.id.in_(staff_ids),
            )
        )
    ).all()
    return {sid: name for sid, name in rows}


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
