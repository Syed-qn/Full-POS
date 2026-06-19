"""HTTP API for the native Android rider app (pairing + background GPS).

Auth: after pairing, the app sends ``Authorization: Bearer <device_token>``.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.dispatch.rider_app import (
    get_rider_by_device_token,
    record_rider_app_location,
    redeem_pairing_code,
)
from app.identity.models import Rider

router = APIRouter(tags=["rider-app"])
_bearer = HTTPBearer(auto_error=False)


class RiderAppInfoOut(BaseModel):
    apkUrl: str | None = None


class PairIn(BaseModel):
    code: str = Field(min_length=4, max_length=12)


class PairOut(BaseModel):
    success: bool = True
    device_token: str
    rider_name: str


class RiderAppMeOut(BaseModel):
    riderName: str
    activeOrderNumber: str | None = None
    customerName: str | None = None
    tracking: bool = False


class LocationIn(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy: float | None = Field(default=None, ge=0)
    speed: float | None = None
    heading: float | None = None


class AckOut(BaseModel):
    success: bool = True


async def _current_rider(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> Rider:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing device token")
    rider = await get_rider_by_device_token(session, token=creds.credentials)
    if rider is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid device token")
    return rider


async def _active_order(session: AsyncSession, rider_id: int):
    from app.ordering.fsm import OrderStatus
    from app.ordering.models import Order

    return await session.scalar(
        select(Order)
        .where(
            Order.rider_id == rider_id,
            Order.status.in_(
                [
                    str(OrderStatus.ASSIGNED),
                    str(OrderStatus.PICKED_UP),
                    str(OrderStatus.ARRIVING),
                ]
            ),
        )
        .order_by(Order.id)
        .limit(1)
    )


@router.get("/api/v1/rider-app/info", response_model=RiderAppInfoOut)
async def rider_app_info():
    """Public: the configured APK download link (for the dashboard banner)."""
    from app.config import get_settings

    return RiderAppInfoOut(apkUrl=get_settings().rider_app_apk_url or None)


@router.post("/api/v1/rider-app/pair", response_model=PairOut)
async def pair_rider_app(body: PairIn, session: AsyncSession = Depends(get_session)):
    rider = await redeem_pairing_code(session, code=body.code)
    if rider is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "invalid or expired pairing code"
        )
    await session.commit()
    return PairOut(device_token=rider.device_token, rider_name=rider.name)


@router.get("/api/v1/rider-app/me", response_model=RiderAppMeOut)
async def rider_app_me(
    rider: Rider = Depends(_current_rider),
    session: AsyncSession = Depends(get_session),
):
    from app.ordering.models import Customer

    order = await _active_order(session, rider.id)
    customer = await session.get(Customer, order.customer_id) if order else None
    return RiderAppMeOut(
        riderName=rider.name,
        activeOrderNumber=order.order_number if order else None,
        customerName=customer.name if customer else None,
        tracking=order is not None,
    )


@router.post("/api/v1/rider-app/location", response_model=AckOut)
async def rider_app_location(
    body: LocationIn,
    rider: Rider = Depends(_current_rider),
    session: AsyncSession = Depends(get_session),
):
    first_ping_orders = await record_rider_app_location(
        session,
        rider=rider,
        latitude=body.latitude,
        longitude=body.longitude,
        accuracy=body.accuracy,
        speed=body.speed,
        heading=body.heading,
    )
    if first_ping_orders:
        # An order's live tracking just went on → reveal the rider's stop and
        # notify the customer (deferred from pickup until GPS is actually on).
        from app.dispatch.rider_flow import (
            _notify_customer_status,
            reveal_first_stop_on_tracking_live,
        )
        from app.ordering.models import Order

        await reveal_first_stop_on_tracking_live(
            session, restaurant_id=rider.restaurant_id, rider_id=rider.id
        )
        for oid in first_ping_orders:
            order = await session.get(Order, oid)
            if order is not None:
                await _notify_customer_status(
                    session,
                    restaurant_id=order.restaurant_id,
                    order=order,
                    status_key="picked_up",
                )
    await session.commit()
    if first_ping_orders:
        from app.outbox.service import deliver_pending

        await deliver_pending(session, rider.restaurant_id)
    return AckOut()
