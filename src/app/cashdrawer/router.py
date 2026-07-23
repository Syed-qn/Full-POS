from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.cashdrawer.schemas import CloseSessionIn, EventIn, OpenSessionIn, SessionOut
from app.cashdrawer.service import (
    DrawerAlreadyOpenError,
    DrawerNotFoundError,
    add_event,
    close_session,
    get_current_session,
    open_session,
)
from app.db import get_session
from app.staff.deps import require_role

router = APIRouter(prefix="/api/v1/cash-drawer", tags=["cash-drawer"])


@router.post("/sessions", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def open_drawer_session(
    body: OpenSessionIn,
    restaurant=Depends(require_role("manager", "cashier")),
    session: AsyncSession = Depends(get_session),
):
    opened_by = "manager"
    if body.staff_id is not None:
        from app.staff.models import StaffMember

        staff = await session.get(StaffMember, body.staff_id)
        if staff is None or staff.restaurant_id != restaurant.id:
            raise HTTPException(status_code=404, detail="staff member not found")
        opened_by = f"staff:{staff.id}:{staff.name}"
    try:
        drawer = await open_session(
            session,
            restaurant_id=restaurant.id,
            opened_by=opened_by,
            opening_float_aed=body.opening_float_aed,
            staff_id=body.staff_id,
        )
    except DrawerAlreadyOpenError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(drawer)
    return drawer


@router.get("/sessions/current", response_model=SessionOut)
async def current_drawer_session(
    restaurant=Depends(require_role("manager", "cashier")),
    session: AsyncSession = Depends(get_session),
):
    drawer = await get_current_session(session, restaurant_id=restaurant.id)
    if drawer is None:
        raise HTTPException(status_code=404, detail="no open drawer session")
    return drawer


@router.post("/sessions/{session_id}/events", status_code=status.HTTP_201_CREATED)
async def add_drawer_event(
    session_id: int,
    body: EventIn,
    restaurant=Depends(require_role("manager", "cashier")),
    session: AsyncSession = Depends(get_session),
):
    try:
        event = await add_event(
            session, session_id=session_id, restaurant_id=restaurant.id, type=body.type,
            amount_aed=body.amount_aed, reason=body.reason, created_by="manager",
        )
    except DrawerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return {"id": event.id, "type": event.type, "amount_aed": str(event.amount_aed)}


@router.post("/sessions/{session_id}/close", response_model=SessionOut)
async def close_drawer_session(
    session_id: int,
    body: CloseSessionIn,
    restaurant=Depends(require_role("manager", "cashier")),
    session: AsyncSession = Depends(get_session),
):
    try:
        drawer = await close_session(
            session, session_id=session_id, restaurant_id=restaurant.id,
            closed_by="manager", closing_count_aed=body.closing_count_aed,
        )
    except DrawerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(drawer)
    return drawer
