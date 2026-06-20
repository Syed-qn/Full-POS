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
    set_push_token,
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


class PushTokenIn(BaseModel):
    push_token: str = Field(min_length=1, max_length=255)


class LocationIn(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy: float | None = Field(default=None, ge=0)
    speed: float | None = None
    heading: float | None = None


class AckOut(BaseModel):
    success: bool = True


class StopOut(BaseModel):
    orderId: int
    orderNumber: str
    sequence: int
    customerName: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    codAmount: float = 0.0
    delivered: bool = False


class RunOut(BaseModel):
    batchId: int | None = None
    status: str | None = None  # planned | picked_up | None (no active run)
    stops: list[StopOut] = []


class DeliveredOut(BaseModel):
    success: bool = True
    batchComplete: bool = False
    nextOrderId: int | None = None


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


@router.post("/api/v1/rider-app/push-token", response_model=AckOut)
async def rider_app_push_token(
    body: PushTokenIn,
    rider: Rider = Depends(_current_rider),
    session: AsyncSession = Depends(get_session),
):
    """Register/refresh the rider's Expo push token (called by the app on launch)."""
    await set_push_token(session, rider=rider, push_token=body.push_token)
    await session.commit()
    return AckOut()


@router.get("/api/v1/rider-app/orders", response_model=RunOut)
async def rider_app_orders(
    rider: Rider = Depends(_current_rider),
    session: AsyncSession = Depends(get_session),
):
    """The rider's current run (active batch + stops) for the app to render."""
    return await get_active_run_response(session, rider)


@router.post("/api/v1/rider-app/orders/pickup", response_model=RunOut)
async def rider_app_pickup(
    rider: Rider = Depends(_current_rider),
    session: AsyncSession = Depends(get_session),
):
    """Mark the rider's batch picked up (same FSM as the WhatsApp 'Orders Picked').

    No live-location prompt here — the app IS the GPS source; it streams location
    via /rider-app/location, and the first ping reveals the customer's stop. The
    app then re-reads /rider-app/orders to show the run."""
    from app.dispatch.rider_actions import mark_batch_picked_up

    await mark_batch_picked_up(
        session, restaurant_id=rider.restaurant_id, rider=rider, batch_id=None
    )
    await session.commit()
    run = await get_active_run_response(session, rider)
    return run


@router.post("/api/v1/rider-app/orders/{order_id}/delivered", response_model=DeliveredOut)
async def rider_app_delivered(
    order_id: int,
    rider: Rider = Depends(_current_rider),
    session: AsyncSession = Depends(get_session),
):
    """Mark one stop delivered + record COD (same FSM as the WhatsApp 'Delivered').

    Gated on live GPS (a recent ping) — the app should be streaming location. On
    success the customer is notified and the next stop, if any, is reported."""
    from app.dispatch.rider_actions import DeliverOutcome, mark_order_delivered

    result = await mark_order_delivered(
        session, restaurant_id=rider.restaurant_id, rider=rider, order_id=order_id
    )
    if result.outcome is DeliverOutcome.IGNORED:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "order not found")
    if result.outcome is DeliverOutcome.NOT_LIVE:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "location sharing is off — keep the app open with GPS on",
        )
    await session.commit()
    # Flush the customer 'delivered' notification now (no Celery on Render).
    from app.outbox.service import deliver_pending

    await deliver_pending(session, rider.restaurant_id)
    return DeliveredOut(
        batchComplete=result.batch_complete,
        nextOrderId=result.next_order.id if result.next_order else None,
    )


async def get_active_run_response(session: AsyncSession, rider: Rider) -> RunOut:
    """Build the RunOut payload for ``rider`` (shared by GET /orders and pickup)."""
    from app.dispatch.rider_actions import get_active_run

    run = await get_active_run(session, rider=rider)
    if run is None:
        return RunOut()
    return RunOut(
        batchId=run.batch_id,
        status=run.status,
        stops=[
            StopOut(
                orderId=s.order_id,
                orderNumber=s.order_number,
                sequence=s.sequence,
                customerName=s.customer_name or None,
                address=s.address or None,
                latitude=s.latitude,
                longitude=s.longitude,
                codAmount=s.cod_amount,
                delivered=s.delivered,
            )
            for s in run.stops
        ],
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
        # An order's live tracking just went on → notify the customer their order
        # is on the way + Track link (deferred from pickup until GPS is actually
        # on). The rider sees their stop in the app (GET /rider-app/orders), so no
        # rider-facing WhatsApp is sent here — riders never receive WhatsApp.
        from app.dispatch.rider_flow import _notify_customer_status
        from app.ordering.models import Order

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
