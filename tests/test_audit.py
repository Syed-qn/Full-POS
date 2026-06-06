# tests/test_audit.py
from sqlalchemy import select

from app.audit.models import AuditLog
from app.audit.service import record_audit


async def test_record_audit_persists_row(db_session):
    await record_audit(
        db_session,
        actor="system",
        entity="order",
        entity_id="42",
        action="status_change",
        before={"status": "ready"},
        after={"status": "assigned"},
    )
    await db_session.commit()
    row = (await db_session.execute(select(AuditLog))).scalar_one()
    assert row.entity == "order"
    assert row.before == {"status": "ready"}
    assert row.after == {"status": "assigned"}
