"""Manager PIN approval queue for void / discount / refund overrides."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.identity.auth import verify_password
from app.identity.models import Restaurant
from app.staff.models import ApprovalRequest, StaffMember, SuspiciousActivityAlert


class InvalidManagerPinError(Exception):
    pass


DISCOUNT_PIN_THRESHOLD_AED = Decimal("20.00")


async def find_manager_by_pin(
    session: AsyncSession, *, restaurant_id: int, pin: str
) -> StaffMember | None:
    managers = (
        await session.scalars(
            select(StaffMember).where(
                StaffMember.restaurant_id == restaurant_id,
                StaffMember.role == "manager",
                StaffMember.is_active.is_(True),
            )
        )
    ).all()
    for m in managers:
        if verify_password(pin, m.pin_hash):
            return m
    return None


async def verify_manager_pin(
    session: AsyncSession,
    *,
    restaurant: Restaurant,
    pin: str,
) -> tuple[str, int | None]:
    """Return (actor_label, approving_staff_id).

    Accepts either a manager staff PIN or the restaurant owner password.
    """
    if not pin:
        raise InvalidManagerPinError("manager PIN required")

    manager = await find_manager_by_pin(
        session, restaurant_id=restaurant.id, pin=pin
    )
    if manager is not None:
        return f"staff:{manager.id}", manager.id

    if verify_password(pin, restaurant.password_hash):
        return f"restaurant:{restaurant.id}", None

    raise InvalidManagerPinError("invalid manager PIN")


async def create_approval_request(
    session: AsyncSession,
    *,
    restaurant_id: int,
    action_type: str,
    order_id: int | None = None,
    amount_aed: Decimal | None = None,
    reason: str | None = None,
    requested_by_staff_id: int | None = None,
    payload: dict[str, Any] | None = None,
    status: str = "pending",
    approved_by_staff_id: int | None = None,
) -> ApprovalRequest:
    now = datetime.now(timezone.utc)
    row = ApprovalRequest(
        restaurant_id=restaurant_id,
        action_type=action_type,
        status=status,
        requested_by_staff_id=requested_by_staff_id,
        approved_by_staff_id=approved_by_staff_id,
        order_id=order_id,
        amount_aed=amount_aed,
        payload=payload or {},
        reason=reason,
        resolved_at=now if status != "pending" else None,
    )
    session.add(row)
    await session.flush()
    return row


async def approve_with_pin(
    session: AsyncSession,
    *,
    restaurant: Restaurant,
    action_type: str,
    pin: str,
    order_id: int | None = None,
    amount_aed: Decimal | None = None,
    reason: str | None = None,
    requested_by_staff_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> ApprovalRequest:
    actor, staff_id = await verify_manager_pin(
        session, restaurant=restaurant, pin=pin
    )
    row = await create_approval_request(
        session,
        restaurant_id=restaurant.id,
        action_type=action_type,
        order_id=order_id,
        amount_aed=amount_aed,
        reason=reason,
        requested_by_staff_id=requested_by_staff_id,
        approved_by_staff_id=staff_id,
        payload=payload,
        status="approved",
    )
    await record_audit(
        session,
        restaurant_id=restaurant.id,
        actor=actor,
        entity="approval_request",
        entity_id=str(row.id),
        action=f"{action_type}_approved",
        after={
            "order_id": order_id,
            "amount_aed": str(amount_aed) if amount_aed is not None else None,
            "reason": reason,
        },
    )
    return row


async def list_approvals(
    session: AsyncSession,
    *,
    restaurant_id: int,
    status: str | None = None,
    limit: int = 50,
) -> list[ApprovalRequest]:
    stmt = (
        select(ApprovalRequest)
        .where(ApprovalRequest.restaurant_id == restaurant_id)
        .order_by(ApprovalRequest.created_at.desc())
        .limit(min(max(limit, 1), 100))
    )
    if status:
        stmt = stmt.where(ApprovalRequest.status == status)
    return list((await session.scalars(stmt)).all())


async def raise_suspicious(
    session: AsyncSession,
    *,
    restaurant_id: int,
    alert_type: str,
    severity: str = "medium",
    staff_id: int | None = None,
    detail: dict | None = None,
) -> SuspiciousActivityAlert:
    row = SuspiciousActivityAlert(
        restaurant_id=restaurant_id,
        alert_type=alert_type,
        severity=severity,
        staff_id=staff_id,
        detail=detail or {},
        acknowledged=False,
    )
    session.add(row)
    await session.flush()
    await record_audit(
        session,
        restaurant_id=restaurant_id,
        actor="system",
        entity="suspicious_activity",
        entity_id=str(row.id),
        action=alert_type,
        after=detail or {},
    )
    return row


async def list_suspicious_alerts(
    session: AsyncSession,
    *,
    restaurant_id: int,
    unacked_only: bool = False,
    limit: int = 50,
) -> list[SuspiciousActivityAlert]:
    stmt = (
        select(SuspiciousActivityAlert)
        .where(SuspiciousActivityAlert.restaurant_id == restaurant_id)
        .order_by(SuspiciousActivityAlert.created_at.desc())
        .limit(min(max(limit, 1), 100))
    )
    if unacked_only:
        stmt = stmt.where(SuspiciousActivityAlert.acknowledged.is_(False))
    return list((await session.scalars(stmt)).all())


async def acknowledge_alert(
    session: AsyncSession, *, restaurant_id: int, alert_id: int
) -> SuspiciousActivityAlert:
    row = await session.get(SuspiciousActivityAlert, alert_id)
    if row is None or row.restaurant_id != restaurant_id:
        raise ValueError("alert not found")
    row.acknowledged = True
    await session.flush()
    return row


def discount_requires_pin(amount_aed: Decimal) -> bool:
    return amount_aed >= DISCOUNT_PIN_THRESHOLD_AED
