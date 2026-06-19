from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.dispatch.tracking_live import (
    TRACKING_STOPPED,
    build_rider_tracking_url,
    build_tracking_url,
    ensure_tracking_session,
    get_tracking_session_by_public_token,
    get_tracking_session_by_rider_token,
    get_tracking_session_for_order,
    is_tracking_accessible,
    record_tracking_location,
    stop_tracking_session,
)
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant

router = APIRouter(tags=["tracking"])
_bearer = HTTPBearer(auto_error=False)


class TrackingStartOut(BaseModel):
    success: bool = True
    tracking_token: str
    rider_token: str
    tracking_url: str
    rider_tracking_url: str


class TrackingAckOut(BaseModel):
    success: bool = True


class LocationUpdateIn(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy: float | None = Field(default=None, ge=0)
    speed: float | None = None
    heading: float | None = None


class LatestLocationOut(BaseModel):
    latitude: float
    longitude: float
    updatedAt: datetime
    accuracy: float | None = None
    speed: float | None = None
    heading: float | None = None
    status: str


class TrackingPointOut(BaseModel):
    latitude: float
    longitude: float
    label: str | None = None


class TrackingPublicOut(BaseModel):
    orderId: int
    orderNumber: str
    status: str
    trackingUrl: str
    lastUpdatedAt: datetime | None = None
    location: LatestLocationOut | None = None
    # Journey endpoints so the customer map can show restaurant → rider →
    # destination (Swiggy/Zomato style), not just the rider dot.
    restaurant: TrackingPointOut | None = None
    destination: TrackingPointOut | None = None


class RiderTrackingOut(BaseModel):
    orderId: int
    orderNumber: str
    status: str
    riderName: str | None = None
    customerName: str | None = None


async def _current_rider_tracking(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
):
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing token")
    access = await get_tracking_session_by_rider_token(
        session, rider_token=creds.credentials
    )
    if access is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid rider token")
    return access


def _to_location_out(access) -> LatestLocationOut | None:
    tracking = access.session
    if (
        tracking.latest_latitude is None
        or tracking.latest_longitude is None
        or tracking.last_location_at is None
    ):
        return None
    return LatestLocationOut(
        latitude=tracking.latest_latitude,
        longitude=tracking.latest_longitude,
        updatedAt=tracking.last_location_at,
        accuracy=tracking.latest_accuracy,
        speed=tracking.latest_speed,
        heading=tracking.latest_heading,
        status=str(access.order.status),
    )


@router.post("/api/v1/orders/{order_id}/tracking/start", response_model=TrackingStartOut)
async def start_order_tracking(
    order_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    access = await get_tracking_session_for_order(
        session, order_id=order_id, restaurant_id=restaurant.id
    )
    if access is None:
        from app.ordering.models import Order

        order = await session.get(Order, order_id)
        if order is None or order.restaurant_id != restaurant.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "order not found")
        if order.rider_id is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "order has no assigned rider")
        tracking = await ensure_tracking_session(session, order=order)
        await session.commit()
        return TrackingStartOut(
            tracking_token=tracking.tracking_token,
            rider_token=tracking.rider_token,
            tracking_url=build_tracking_url(tracking.tracking_token),
            rider_tracking_url=build_rider_tracking_url(tracking.rider_token),
        )

    tracking = await ensure_tracking_session(session, order=access.order)
    await session.commit()
    return TrackingStartOut(
        tracking_token=tracking.tracking_token,
        rider_token=tracking.rider_token,
        tracking_url=build_tracking_url(tracking.tracking_token),
        rider_tracking_url=build_rider_tracking_url(tracking.rider_token),
    )


@router.post("/api/v1/orders/{order_id}/location", response_model=TrackingAckOut)
async def update_order_location(
    order_id: int,
    body: LocationUpdateIn,
    access=Depends(_current_rider_tracking),
    session: AsyncSession = Depends(get_session),
):
    if access.order.id != order_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "token does not match order")
    if not is_tracking_accessible(access.session):
        raise HTTPException(status.HTTP_410_GONE, "tracking session expired")
    # First ping = the rider's live location just went ON. We defer the customer's
    # "on the way" + Track link to this moment (not pickup) so the link always
    # works when tapped, instead of opening an empty "waiting for rider" map.
    was_first_ping = access.session.last_location_at is None
    await record_tracking_location(
        session,
        tracking=access.session,
        latitude=body.latitude,
        longitude=body.longitude,
        accuracy=body.accuracy,
        speed=body.speed,
        heading=body.heading,
    )
    if was_first_ping:
        await _notify_customers_tracking_live(session, rider_id=access.session.rider_id)
    await session.commit()
    if was_first_ping:
        # Location POSTs aren't webhook calls, so nothing flushes the outbox for
        # us — deliver the just-enqueued customer notifications now.
        from app.outbox.service import deliver_pending

        await deliver_pending(session, access.order.restaurant_id)
    return TrackingAckOut()


async def _notify_customers_tracking_live(session: AsyncSession, *, rider_id: int) -> None:
    """Notify the customer(s) of this rider's en-route orders that the order is on
    the way, now that live GPS is on — idempotent per (order, picked_up). Covers a
    batched run (every undelivered stop), not just the order that posted."""
    from sqlalchemy import select as _select

    from app.dispatch.rider_flow import _notify_customer_status
    from app.ordering.fsm import OrderStatus
    from app.ordering.models import Order

    en_route = (
        await session.scalars(
            _select(Order).where(
                Order.rider_id == rider_id,
                Order.status.in_(
                    [
                        str(OrderStatus.ASSIGNED),
                        str(OrderStatus.PICKED_UP),
                        str(OrderStatus.ARRIVING),
                    ]
                ),
            )
        )
    ).all()
    for order in en_route:
        await _notify_customer_status(
            session, restaurant_id=order.restaurant_id, order=order, status_key="picked_up"
        )


@router.get("/api/v1/orders/{order_id}/location", response_model=LatestLocationOut)
async def get_order_location(
    order_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    access = await get_tracking_session_for_order(
        session, order_id=order_id, restaurant_id=restaurant.id
    )
    if access is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tracking not found")
    location = _to_location_out(access)
    if location is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "location not available")
    return location


@router.post("/api/v1/orders/{order_id}/tracking/stop", response_model=TrackingAckOut)
async def stop_order_tracking(
    order_id: int,
    access=Depends(_current_rider_tracking),
    session: AsyncSession = Depends(get_session),
):
    if access.order.id != order_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "token does not match order")
    await stop_tracking_session(session, order_id=order_id, reason=TRACKING_STOPPED)
    await session.commit()
    return TrackingAckOut()


@router.get("/api/v1/track/{tracking_token}", response_model=TrackingPublicOut)
async def get_public_tracking(
    tracking_token: str,
    session: AsyncSession = Depends(get_session),
):
    access = await get_tracking_session_by_public_token(
        session, tracking_token=tracking_token
    )
    if access is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tracking link not found")
    if not is_tracking_accessible(access.session):
        raise HTTPException(status.HTTP_410_GONE, "tracking link expired")

    # Resolve the journey endpoints so the customer map can draw
    # restaurant (from) → rider → delivery address (to).
    from app.identity.models import Restaurant
    from app.ordering.models import CustomerAddress

    restaurant_pt: TrackingPointOut | None = None
    rest = await session.get(Restaurant, access.order.restaurant_id)
    if rest is not None and rest.lat is not None and rest.lng is not None:
        restaurant_pt = TrackingPointOut(
            latitude=rest.lat, longitude=rest.lng, label=rest.name
        )

    destination_pt: TrackingPointOut | None = None
    if access.order.address_id is not None:
        addr = await session.get(CustomerAddress, access.order.address_id)
        if addr is not None and addr.latitude is not None and addr.longitude is not None:
            destination_pt = TrackingPointOut(
                latitude=addr.latitude,
                longitude=addr.longitude,
                label="Delivery address",
            )

    return TrackingPublicOut(
        orderId=access.order.id,
        orderNumber=access.order.order_number,
        status=str(access.order.status),
        trackingUrl=build_tracking_url(access.session.tracking_token),
        lastUpdatedAt=access.session.last_location_at,
        location=_to_location_out(access),
        restaurant=restaurant_pt,
        destination=destination_pt,
    )


@router.get("/api/v1/track/{tracking_token}/location", response_model=LatestLocationOut)
async def get_public_tracking_location(
    tracking_token: str,
    session: AsyncSession = Depends(get_session),
):
    access = await get_tracking_session_by_public_token(
        session, tracking_token=tracking_token
    )
    if access is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tracking link not found")
    if not is_tracking_accessible(access.session):
        raise HTTPException(status.HTTP_410_GONE, "tracking link expired")
    location = _to_location_out(access)
    if location is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "location not available")
    return location


@router.get("/api/v1/rider-track/{rider_token}", response_model=RiderTrackingOut)
async def get_rider_tracking(
    rider_token: str,
    session: AsyncSession = Depends(get_session),
):
    access = await get_tracking_session_by_rider_token(session, rider_token=rider_token)
    if access is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "rider tracking not found")
    if access.session.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_410_GONE, "rider tracking expired")
    from app.identity.models import Rider
    from app.ordering.models import Customer

    rider = await session.get(Rider, access.session.rider_id)
    customer = await session.get(Customer, access.order.customer_id)
    return RiderTrackingOut(
        orderId=access.order.id,
        orderNumber=access.order.order_number,
        status=str(access.order.status),
        riderName=rider.name if rider else None,
        customerName=customer.name if customer else None,
    )
