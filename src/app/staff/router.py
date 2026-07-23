from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.db import get_session
from app.identity.auth import create_access_token, hash_password, verify_password
from app.identity.deps import current_restaurant
from app.staff.approvals import (
    InvalidManagerPinError,
    acknowledge_alert,
    approve_with_pin,
    list_approvals,
    list_suspicious_alerts,
    raise_suspicious,
)
from app.staff.deps import require_role
from app.staff.mistakes import list_mistakes, record_mistake
from app.staff.models import StaffMember
from app.staff.performance import attendance_for_date, performance_report
from app.staff.scheduling import (
    close_shift,
    create_shift,
    list_shifts_for_week,
    open_shift,
)
from app.staff.schemas import (
    ApprovalOut,
    AttributeTipIn,
    ClockIn,
    ManagerPinIn,
    MistakeIn,
    MistakeOut,
    ShiftIn,
    ShiftOut,
    StaffIn,
    StaffLoginIn,
    StaffOut,
    SuspiciousOut,
    TrainingModeIn,
)
from app.staff.service import (
    AlreadyClockedInError,
    AlreadyOnBreakError,
    NotClockedInError,
    NotOnBreakError,
    clock_in,
    clock_out,
    compute_hours,
    compute_overtime_hours,
    compute_sales,
    end_break,
    get_current_status,
    set_training_mode,
    start_break,
)
from app.staff.tips import attribute_tip_to_staff, distribute_tip_pool, tips_by_staff

router = APIRouter(prefix="/api/v1/staff", tags=["staff"])


def _approval_out(row) -> ApprovalOut:
    return ApprovalOut(
        id=row.id,
        action_type=row.action_type,
        status=row.status,
        requested_by_staff_id=row.requested_by_staff_id,
        approved_by_staff_id=row.approved_by_staff_id,
        order_id=row.order_id,
        amount_aed=str(row.amount_aed) if row.amount_aed is not None else None,
        reason=row.reason,
        created_at=row.created_at,
        resolved_at=row.resolved_at,
    )


@router.post("/login")
async def staff_login(body: StaffLoginIn, session: AsyncSession = Depends(get_session)):
    staff = await session.get(StaffMember, body.staff_id)
    if staff is None or not staff.is_active or not verify_password(body.pin, staff.pin_hash):
        raise HTTPException(status_code=401, detail="invalid staff_id or pin")
    token = create_access_token(
        staff_id=staff.id, audience="staff", extra_claims={"role": staff.role}
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": staff.role,
        "staff_id": staff.id,
        "name": staff.name,
        "training_mode": bool(staff.training_mode),
    }


async def _get_owned_staff(
    session: AsyncSession, *, staff_id: int, restaurant_id: int
) -> StaffMember:
    staff = await session.get(StaffMember, staff_id)
    if staff is None or staff.restaurant_id != restaurant_id:
        raise HTTPException(status_code=404, detail="staff member not found")
    return staff


@router.post("", response_model=StaffOut, status_code=status.HTTP_201_CREATED)
async def create_staff(
    body: StaffIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    staff = StaffMember(
        restaurant_id=restaurant.id,
        name=body.name,
        phone=body.phone,
        role=body.role,
        pin_hash=hash_password(body.pin),
        is_active=True,
        training_mode=False,
    )
    session.add(staff)
    await session.flush()
    await record_audit(
        session,
        actor=f"restaurant:{restaurant.id}",
        restaurant_id=restaurant.id,
        entity="staff_member",
        entity_id=str(staff.id),
        action="staff_created",
        after={"name": staff.name, "role": staff.role},
    )
    await session.commit()
    await session.refresh(staff)
    return staff


@router.get("", response_model=list[StaffOut])
async def list_staff(
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = await session.scalars(
        select(StaffMember).where(StaffMember.restaurant_id == restaurant.id)
    )
    return list(rows)


@router.post("/{staff_id}/clock")
async def clock(
    staff_id: int,
    body: ClockIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    await _get_owned_staff(session, staff_id=staff_id, restaurant_id=restaurant.id)
    now = datetime.now(timezone.utc)
    try:
        if body.type == "clock_in":
            event = await clock_in(
                session, staff_id=staff_id, restaurant_id=restaurant.id, at=now
            )
            # After-hours clock-in (before 6am or after 11pm UTC+4 ≈ rough UAE night)
            local_hour = (now.hour + 4) % 24
            if local_hour < 6 or local_hour >= 23:
                await raise_suspicious(
                    session,
                    restaurant_id=restaurant.id,
                    alert_type="after_hours_clock_in",
                    severity="low",
                    staff_id=staff_id,
                    detail={"at": now.isoformat(), "local_hour_approx": local_hour},
                )
        elif body.type == "clock_out":
            event = await clock_out(
                session, staff_id=staff_id, restaurant_id=restaurant.id, at=now
            )
        elif body.type == "break_start":
            event = await start_break(
                session, staff_id=staff_id, restaurant_id=restaurant.id, at=now
            )
        elif body.type == "break_end":
            event = await end_break(
                session, staff_id=staff_id, restaurant_id=restaurant.id, at=now
            )
        else:
            raise HTTPException(
                status_code=422,
                detail="type must be clock_in, clock_out, break_start, or break_end",
            )
    except AlreadyClockedInError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotClockedInError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AlreadyOnBreakError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotOnBreakError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await record_audit(
        session,
        actor=f"staff:{staff_id}",
        restaurant_id=restaurant.id,
        entity="clock_event",
        entity_id=str(staff_id),
        action=body.type,
        after={"at": now.isoformat()},
    )
    await session.commit()
    return {"id": event.id, "type": event.type, "at": event.at.isoformat()}


@router.get("/{staff_id}/status")
async def status_endpoint(
    staff_id: int,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    await _get_owned_staff(session, staff_id=staff_id, restaurant_id=restaurant.id)
    current_status = await get_current_status(
        session, staff_id=staff_id, restaurant_id=restaurant.id
    )
    return {"staff_id": staff_id, "status": current_status}


@router.get("/{staff_id}/hours")
async def hours(
    staff_id: int,
    target_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    await _get_owned_staff(session, staff_id=staff_id, restaurant_id=restaurant.id)
    total = await compute_hours(
        session,
        staff_id=staff_id,
        restaurant_id=restaurant.id,
        target_date=target_date,
    )
    return {
        "staff_id": staff_id,
        "date": target_date.isoformat(),
        "hours": round(total, 2),
        "overtime_hours": round(compute_overtime_hours(total), 2),
    }


@router.get("/{staff_id}/sales")
async def sales(
    staff_id: int,
    target_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    await _get_owned_staff(session, staff_id=staff_id, restaurant_id=restaurant.id)
    total = await compute_sales(
        session,
        staff_id=staff_id,
        restaurant_id=restaurant.id,
        target_date=target_date,
    )
    return {
        "staff_id": staff_id,
        "date": target_date.isoformat(),
        "sales_aed": str(total),
    }


@router.patch("/{staff_id}/training-mode", response_model=StaffOut)
async def patch_training_mode(
    staff_id: int,
    body: TrainingModeIn,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    try:
        staff = await set_training_mode(
            session,
            restaurant_id=restaurant.id,
            staff_id=staff_id,
            training_mode=body.training_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await record_audit(
        session,
        actor=f"restaurant:{restaurant.id}",
        restaurant_id=restaurant.id,
        entity="staff_member",
        entity_id=str(staff_id),
        action="training_mode_set",
        after={"training_mode": body.training_mode},
    )
    await session.commit()
    await session.refresh(staff)
    return staff


@router.post("/shifts", response_model=ShiftOut, status_code=status.HTTP_201_CREATED)
async def create_shift_endpoint(
    body: ShiftIn,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    await _get_owned_staff(session, staff_id=body.staff_id, restaurant_id=restaurant.id)
    shift = await create_shift(
        session,
        restaurant_id=restaurant.id,
        staff_id=body.staff_id,
        scheduled_start=body.scheduled_start,
        scheduled_end=body.scheduled_end,
    )
    await record_audit(
        session,
        actor=f"restaurant:{restaurant.id}",
        restaurant_id=restaurant.id,
        entity="shift",
        entity_id=str(shift.id),
        action="shift_created",
        after={
            "staff_id": body.staff_id,
            "scheduled_start": body.scheduled_start.isoformat(),
        },
    )
    await session.commit()
    await session.refresh(shift)
    return shift


@router.get("/shifts", response_model=list[ShiftOut])
async def list_shifts_endpoint(
    week_start: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await list_shifts_for_week(
        session, restaurant_id=restaurant.id, week_start=week_start
    )


@router.post("/shifts/{shift_id}/open", response_model=ShiftOut)
async def open_shift_endpoint(
    shift_id: int,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        shift = await open_shift(session, restaurant_id=restaurant.id, shift_id=shift_id)
        # Also clock in the staff if not already
        try:
            await clock_in(
                session,
                staff_id=shift.staff_id,
                restaurant_id=restaurant.id,
                at=datetime.now(timezone.utc),
            )
        except AlreadyClockedInError:
            pass
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(shift)
    return shift


@router.post("/shifts/{shift_id}/close", response_model=ShiftOut)
async def close_shift_endpoint(
    shift_id: int,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        shift = await close_shift(session, restaurant_id=restaurant.id, shift_id=shift_id)
        try:
            await clock_out(
                session,
                staff_id=shift.staff_id,
                restaurant_id=restaurant.id,
                at=datetime.now(timezone.utc),
            )
        except NotClockedInError:
            pass
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(shift)
    return shift


@router.get("/tip-pool")
async def tip_pool(
    start_date: date,
    end_date: date,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    pool = await distribute_tip_pool(
        session,
        restaurant_id=restaurant.id,
        start_date=start_date,
        end_date=end_date,
    )
    return {str(staff_id): str(amount) for staff_id, amount in pool.items()}


@router.get("/tips-by-staff")
async def tips_by_staff_endpoint(
    start_date: date,
    end_date: date,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    by_staff = await tips_by_staff(
        session,
        restaurant_id=restaurant.id,
        start_date=start_date,
        end_date=end_date,
    )
    return {str(sid): str(amt) for sid, amt in by_staff.items()}


@router.post("/attribute-tip")
async def attribute_tip_endpoint(
    body: AttributeTipIn,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    await _get_owned_staff(session, staff_id=body.staff_id, restaurant_id=restaurant.id)
    try:
        await attribute_tip_to_staff(
            session,
            restaurant_id=restaurant.id,
            order_id=body.order_id,
            staff_id=body.staff_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return {"order_id": body.order_id, "tip_staff_id": body.staff_id}


@router.post("/approvals", response_model=ApprovalOut, status_code=status.HTTP_201_CREATED)
async def create_approval_with_pin(
    body: ManagerPinIn,
    # A manager on a staff PIN session must be able to approve — gating this on
    # the OWNER token made every void/cancel 403 "manager access required" for
    # the very role the dialog asks for. The PIN is still verified inside
    # approve_with_pin, so the caller needs the role AND the secret.
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    try:
        row = await approve_with_pin(
            session,
            restaurant=restaurant,
            action_type=body.action_type,
            pin=body.pin,
            order_id=body.order_id,
            amount_aed=body.amount_aed,
            reason=body.reason,
            requested_by_staff_id=body.requested_by_staff_id,
            payload=body.payload,
        )
    except InvalidManagerPinError as exc:
        await raise_suspicious(
            session,
            restaurant_id=restaurant.id,
            alert_type="failed_manager_pin",
            severity="high",
            staff_id=body.requested_by_staff_id,
            detail={"action_type": body.action_type, "order_id": body.order_id},
        )
        await session.commit()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    await session.commit()
    return _approval_out(row)


@router.get("/approvals", response_model=list[ApprovalOut])
async def get_approvals(
    status_filter: str | None = Query(default=None, alias="status"),
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    rows = await list_approvals(
        session, restaurant_id=restaurant.id, status=status_filter
    )
    return [_approval_out(r) for r in rows]


@router.post("/mistakes", response_model=MistakeOut, status_code=status.HTTP_201_CREATED)
async def create_mistake(
    body: MistakeIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    await _get_owned_staff(session, staff_id=body.staff_id, restaurant_id=restaurant.id)
    try:
        row = await record_mistake(
            session,
            restaurant_id=restaurant.id,
            staff_id=body.staff_id,
            mistake_type=body.mistake_type,
            order_id=body.order_id,
            amount_aed=body.amount_aed,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # High void/mistake cost → suspicious
    if body.amount_aed >= Decimal("50.00") or body.mistake_type == "void":
        await raise_suspicious(
            session,
            restaurant_id=restaurant.id,
            alert_type="high_value_mistake",
            severity="medium" if body.amount_aed < Decimal("100") else "high",
            staff_id=body.staff_id,
            detail={
                "mistake_type": body.mistake_type,
                "amount_aed": str(body.amount_aed),
                "order_id": body.order_id,
            },
        )
    await session.commit()
    return MistakeOut(
        id=row.id,
        staff_id=row.staff_id,
        mistake_type=row.mistake_type,
        order_id=row.order_id,
        amount_aed=str(row.amount_aed),
        notes=row.notes,
        created_at=row.created_at,
    )


@router.get("/mistakes", response_model=list[MistakeOut])
async def get_mistakes(
    staff_id: int | None = None,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    rows = await list_mistakes(
        session, restaurant_id=restaurant.id, staff_id=staff_id
    )
    return [
        MistakeOut(
            id=r.id,
            staff_id=r.staff_id,
            mistake_type=r.mistake_type,
            order_id=r.order_id,
            amount_aed=str(r.amount_aed),
            notes=r.notes,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/attendance")
async def attendance(
    target_date: date,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    rows = await attendance_for_date(
        session, restaurant_id=restaurant.id, target_date=target_date
    )
    return {"date": target_date.isoformat(), "rows": rows}


@router.get("/reports/performance")
async def staff_performance(
    start_date: date,
    end_date: date,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    rows = await performance_report(
        session,
        restaurant_id=restaurant.id,
        start_date=start_date,
        end_date=end_date,
    )
    return {"start_date": start_date.isoformat(), "end_date": end_date.isoformat(), "rows": rows}


@router.get("/alerts", response_model=list[SuspiciousOut])
async def get_alerts(
    unacked_only: bool = False,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    rows = await list_suspicious_alerts(
        session, restaurant_id=restaurant.id, unacked_only=unacked_only
    )
    return [
        SuspiciousOut(
            id=r.id,
            alert_type=r.alert_type,
            severity=r.severity,
            staff_id=r.staff_id,
            detail=r.detail or {},
            acknowledged=r.acknowledged,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.post("/alerts/{alert_id}/acknowledge", response_model=SuspiciousOut)
async def ack_alert(
    alert_id: int,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    try:
        row = await acknowledge_alert(
            session, restaurant_id=restaurant.id, alert_id=alert_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return SuspiciousOut(
        id=row.id,
        alert_type=row.alert_type,
        severity=row.severity,
        staff_id=row.staff_id,
        detail=row.detail or {},
        acknowledged=row.acknowledged,
        created_at=row.created_at,
    )
