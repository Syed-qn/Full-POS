"""AI reservation handling (bookings, not just tables)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import ReservationRequest
from app.ai.text_gen import generate_narrative
from app.audit.service import record_audit


async def create_reservation(
    session: AsyncSession,
    *,
    restaurant_id: int,
    party_size: int,
    requested_for: datetime,
    guest_name: str | None = None,
    phone: str | None = None,
    notes: str | None = None,
    customer_id: int | None = None,
    source: str = "dashboard",
) -> ReservationRequest:
    party_size = max(1, min(int(party_size), 50))
    if requested_for.tzinfo is None:
        requested_for = requested_for.replace(tzinfo=timezone.utc)
    facts = {
        "party_size": party_size,
        "when": requested_for.isoformat(),
        "guest": guest_name,
        "notes": notes,
    }
    summary = await generate_narrative("reservation", facts)
    # Soft-assign a free table if tables module has capacity
    table_id = None
    try:
        from app.tables.models import DiningTable

        tables = list(
            (
                await session.scalars(
                    select(DiningTable).where(
                        DiningTable.restaurant_id == restaurant_id,
                    )
                )
            ).all()
        )
        for t in tables:
            cap = int(t.seats or 0)
            if cap >= party_size and t.status in ("free", "available", None, ""):
                table_id = t.id
                break
    except Exception:  # noqa: BLE001
        table_id = None

    row = ReservationRequest(
        restaurant_id=restaurant_id,
        customer_id=customer_id,
        phone=phone,
        guest_name=guest_name,
        party_size=party_size,
        requested_for=requested_for,
        notes=notes,
        status="confirmed" if table_id else "pending",
        table_id=table_id,
        ai_summary=summary,
        source=source,
    )
    session.add(row)
    await session.flush()
    await record_audit(
        session,
        restaurant_id=restaurant_id,
        actor="manager",
        entity="reservation",
        entity_id=str(row.id),
        action="create",
        after={"party_size": party_size, "table_id": table_id},
    )
    return row


async def list_reservations(
    session: AsyncSession, *, restaurant_id: int, limit: int = 50
) -> list[ReservationRequest]:
    return list(
        (
            await session.scalars(
                select(ReservationRequest)
                .where(ReservationRequest.restaurant_id == restaurant_id)
                .order_by(ReservationRequest.requested_for.desc())
                .limit(min(max(limit, 1), 100))
            )
        ).all()
    )


async def update_reservation_status(
    session: AsyncSession,
    *,
    restaurant_id: int,
    reservation_id: int,
    status: str,
) -> ReservationRequest:
    row = await session.get(ReservationRequest, reservation_id)
    if row is None or row.restaurant_id != restaurant_id:
        raise ValueError("reservation not found")
    allowed = {"pending", "confirmed", "seated", "cancelled", "no_show", "completed"}
    if status not in allowed:
        raise ValueError(f"invalid status {status}")
    row.status = status
    await session.flush()
    return row
