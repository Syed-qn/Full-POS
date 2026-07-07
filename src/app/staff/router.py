from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.auth import hash_password
from app.identity.deps import current_restaurant
from app.staff.models import StaffMember
from app.staff.schemas import ClockIn, StaffIn, StaffOut
from app.staff.service import (
    AlreadyClockedInError,
    NotClockedInError,
    clock_in,
    clock_out,
    compute_hours,
    compute_sales,
)

router = APIRouter(prefix="/api/v1/staff", tags=["staff"])


async def _get_owned_staff(session: AsyncSession, *, staff_id: int, restaurant_id: int) -> StaffMember:
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
        restaurant_id=restaurant.id, name=body.name, phone=body.phone, role=body.role,
        pin_hash=hash_password(body.pin),
    )
    session.add(staff)
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
            event = await clock_in(session, staff_id=staff_id, restaurant_id=restaurant.id, at=now)
        elif body.type == "clock_out":
            event = await clock_out(session, staff_id=staff_id, restaurant_id=restaurant.id, at=now)
        else:
            raise HTTPException(status_code=422, detail="type must be clock_in or clock_out")
    except AlreadyClockedInError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotClockedInError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return {"id": event.id, "type": event.type, "at": event.at.isoformat()}


@router.get("/{staff_id}/hours")
async def hours(
    staff_id: int,
    target_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    await _get_owned_staff(session, staff_id=staff_id, restaurant_id=restaurant.id)
    total = await compute_hours(session, staff_id=staff_id, restaurant_id=restaurant.id, target_date=target_date)
    return {"staff_id": staff_id, "date": target_date.isoformat(), "hours": round(total, 2)}


@router.get("/{staff_id}/sales")
async def sales(
    staff_id: int,
    target_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    await _get_owned_staff(session, staff_id=staff_id, restaurant_id=restaurant.id)
    total = await compute_sales(session, staff_id=staff_id, restaurant_id=restaurant.id, target_date=target_date)
    return {"staff_id": staff_id, "date": target_date.isoformat(), "sales_aed": str(total)}
