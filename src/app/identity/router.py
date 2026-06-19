from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity import service
from app.identity.auth import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.identity.schemas import (
    LoginIn,
    ProfilePatch,
    RestaurantOut,
    RiderIn,
    RiderLocationOut,
    RiderOut,
    RiderPatch,
    SettingsPatch,
    SignupIn,
    TokenOut,
)
from app.identity.service import DuplicatePhoneError, RiderHasHistoryError
from app.ratelimit.deps import rate_limit_auth

router = APIRouter(prefix="/api/v1", tags=["identity"])

_DUMMY_HASH = hash_password("dummy-timing-equalizer-not-a-real-password")


@router.post("/auth/signup", response_model=RestaurantOut, status_code=201)
async def signup(body: SignupIn, session: AsyncSession = Depends(get_session)):
    try:
        return await service.create_restaurant(
            session,
            name=body.name,
            phone=body.phone,
            password=body.password,
            lat=body.lat,
            lng=body.lng,
        )
    except DuplicatePhoneError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))


@router.post(
    "/auth/login",
    response_model=TokenOut,
    dependencies=[Depends(rate_limit_auth)],
)
async def login(body: LoginIn, session: AsyncSession = Depends(get_session)):
    restaurant = await session.scalar(
        select(Restaurant).where(Restaurant.phone == body.phone)
    )
    if restaurant is None:
        verify_password(body.password, _DUMMY_HASH)  # equalize timing
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad credentials")
    if not verify_password(body.password, restaurant.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad credentials")
    return TokenOut(access_token=create_access_token(restaurant_id=restaurant.id))


@router.get("/me", response_model=RestaurantOut)
async def me(restaurant: Restaurant = Depends(current_restaurant)):
    return restaurant


@router.get("/geo/health")
async def geo_health(
    lat: float | None = None,
    lng: float | None = None,
    restaurant: Restaurant = Depends(current_restaurant),
):
    """Diagnose delivery-distance accuracy in the live environment.

    Without params: reports the configured provider + whether a Google key is
    present + the restaurant's saved location. With ``lat``/``lng`` (a test
    customer pin): also returns the road distance vs straight-line distance and
    whether real road distance is actually in effect — so a silent fallback to
    straight-line (which mis-prices delivery) is visible without reading logs.
    """
    import asyncio

    from app.config import get_settings
    from app.geo.factory import get_geo_provider
    from app.geo.haversine import distance_km as _haversine

    settings = get_settings()
    out: dict = {
        "configured_provider": settings.geo_provider,
        "google_key_present": bool(settings.google_maps_api_key.get_secret_value()),
        "restaurant_location": {"lat": restaurant.lat, "lng": restaurant.lng},
    }
    if lat is not None and lng is not None:
        road = await asyncio.to_thread(
            get_geo_provider().distance_km, restaurant.lat, restaurant.lng, lat, lng
        )
        straight = _haversine(restaurant.lat, restaurant.lng, lat, lng)
        # If road distance equals straight-line to the metre, the provider fell
        # back to haversine (real road distance is essentially never identical).
        real = settings.geo_provider == "google_maps" and abs(road - straight) > 1e-4
        out["test"] = {
            "road_km": round(road, 3),
            "straight_line_km": round(straight, 3),
            "using_real_road_distance": real,
        }
    return out


@router.patch("/me", response_model=RestaurantOut)
async def patch_me(
    body: ProfilePatch,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await service.update_profile(
        session, restaurant=restaurant, name=body.name, lat=body.lat, lng=body.lng,
    )


@router.post("/riders", response_model=RiderOut, status_code=201)
async def create_rider(
    body: RiderIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await service.create_rider(
            session,
            restaurant_id=restaurant.id,
            name=body.name,
            phone=body.phone,
        )
    except DuplicatePhoneError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))


@router.get("/riders", response_model=list[RiderOut])
async def list_riders(
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await service.list_riders(session, restaurant.id)


@router.get("/riders/{rider_id}/location", response_model=RiderLocationOut | None)
async def rider_location(
    rider_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """Latest location ping for the live-tracking map. 200 with the pin, 200 with
    null when the rider hasn't shared a location yet, 404 when the rider is
    unknown to this tenant."""
    result = await service.latest_rider_location(
        session, restaurant_id=restaurant.id, rider_id=rider_id
    )
    if result is False:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "rider not found")
    return result


@router.patch("/riders/{rider_id}", response_model=RiderOut)
async def patch_rider(
    rider_id: int,
    body: RiderPatch,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    # Profile edit (name/phone) takes precedence; otherwise it's a status change.
    if body.name is not None or body.phone is not None:
        try:
            rider = await service.update_rider_profile(
                session,
                restaurant_id=restaurant.id,
                rider_id=rider_id,
                name=body.name,
                phone=body.phone,
            )
        except DuplicatePhoneError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    elif body.status is not None:
        rider = await service.set_rider_status(
            session,
            restaurant_id=restaurant.id,
            rider_id=rider_id,
            status=body.status,
        )
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "no fields to update")
    if rider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "rider not found")
    return rider


@router.post("/riders/{rider_id}/app-invite")
async def invite_rider_to_app(
    rider_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """Generate a one-time pairing code for the rider and send it (with the APK
    link) over WhatsApp, so they can pair the native tracking app."""
    from app.dispatch.rider_app import _PAIRING_TTL_MINUTES, send_rider_app_pairing
    from app.identity.models import Rider
    from app.outbox.service import deliver_pending

    rider = await session.scalar(
        select(Rider).where(Rider.id == rider_id, Rider.restaurant_id == restaurant.id)
    )
    if rider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "rider not found")
    code = await send_rider_app_pairing(session, rider=rider)
    await session.commit()
    await deliver_pending(session, restaurant.id)
    return {"success": True, "code": code, "expires_in_minutes": _PAIRING_TTL_MINUTES}


@router.delete("/riders/{rider_id}", status_code=204)
async def delete_rider(
    rider_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        deleted = await service.delete_rider(
            session, restaurant_id=restaurant.id, rider_id=rider_id
        )
    except RiderHasHistoryError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "rider not found")


@router.patch("/settings", response_model=RestaurantOut)
async def patch_settings(
    body: SettingsPatch,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    return await service.update_settings(session, restaurant=restaurant, changes=changes)
