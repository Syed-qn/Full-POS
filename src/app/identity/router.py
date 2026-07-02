import logging

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
    MetaConfigIn,
    MetaConfigOut,
    MetaConnectIn,
    MetaEmbedConfigOut,
    ProfilePatch,
    RestaurantOut,
    RiderIn,
    RiderLocationOut,
    RiderOut,
    RiderPatch,
    OnboardingStatusOut,
    SettingsPatch,
    SignupIn,
    TokenOut,
)
from app.identity.service import (
    DuplicateEmailError,
    DuplicatePhoneError,
    RiderHasHistoryError,
)
from app.ratelimit.deps import rate_limit_auth

router = APIRouter(prefix="/api/v1", tags=["identity"])

_logger = logging.getLogger(__name__)

_DUMMY_HASH = hash_password("dummy-timing-equalizer-not-a-real-password")


@router.post("/auth/signup", response_model=RestaurantOut, status_code=201)
async def signup(body: SignupIn, session: AsyncSession = Depends(get_session)):
    try:
        return await service.create_restaurant(
            session,
            name=body.name,
            email=body.email,
            password=body.password,
            phone=body.phone,
            lat=body.lat,
            lng=body.lng,
        )
    except (DuplicateEmailError, DuplicatePhoneError) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))


@router.post(
    "/auth/login",
    response_model=TokenOut,
    dependencies=[Depends(rate_limit_auth)],
)
async def login(body: LoginIn, session: AsyncSession = Depends(get_session)):
    restaurant = await session.scalar(
        select(Restaurant).where(Restaurant.email == body.email)
    )
    if restaurant is None:
        verify_password(body.password, _DUMMY_HASH)  # equalize timing
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad credentials")
    if not verify_password(body.password, restaurant.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad credentials")
    restaurant_id = restaurant.id
    # First sign-in only: submit the transactional utility templates for approval.
    # Best-effort — a template-provider hiccup must never block login.
    try:
        from app.whatsapp.templates import ensure_utility_templates

        if await ensure_utility_templates(session, restaurant_id=restaurant_id):
            await session.commit()
    except Exception:  # noqa: BLE001 — login must succeed regardless
        await session.rollback()
    return TokenOut(access_token=create_access_token(restaurant_id=restaurant_id))


@router.get("/me", response_model=RestaurantOut)
async def me(restaurant: Restaurant = Depends(current_restaurant)):
    return restaurant


@router.get("/onboarding/status", response_model=OnboardingStatusOut)
async def onboarding_status(
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await service.get_onboarding_status(session, restaurant=restaurant)


@router.post("/onboarding/complete", response_model=RestaurantOut)
async def onboarding_complete(
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await service.complete_onboarding(session, restaurant=restaurant)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


async def _set_connected_phone(
    session: AsyncSession, restaurant: Restaurant, display_number: str
) -> None:
    """Set the restaurant's WhatsApp routing phone to the number it just connected.

    This guarantees Restaurant.phone == the real WhatsApp display number regardless
    of anything typed at signup, so inbound webhooks always route correctly. Raises
    409 if that number is already connected to a different restaurant."""
    from app.identity.phones import normalize_phone

    norm = normalize_phone(display_number)
    if not norm or norm == restaurant.phone:
        return
    clash = await session.scalar(
        select(Restaurant).where(Restaurant.phone == norm, Restaurant.id != restaurant.id)
    )
    if clash is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This WhatsApp number is already connected to another restaurant.",
        )
    restaurant.phone = norm


def _meta_config_out(restaurant: Restaurant) -> MetaConfigOut:
    from app.identity.meta_config import meta_connected, meta_settings

    cfg = meta_settings(restaurant)
    return MetaConfigOut(
        wa_phone_number_id=cfg["wa_phone_number_id"],
        wa_business_account_id=cfg["wa_business_account_id"],
        wa_access_token_set=bool(cfg["wa_access_token"]),
        catalog_id=cfg["catalog_id"],
        connected=meta_connected(restaurant),
    )


@router.get("/onboarding/meta-config", response_model=MetaConfigOut)
async def get_meta_config(restaurant: Restaurant = Depends(current_restaurant)):
    """Read this restaurant's Meta/WhatsApp connection (token never returned)."""
    return _meta_config_out(restaurant)


@router.patch("/onboarding/meta-config", response_model=MetaConfigOut)
async def patch_meta_config(
    body: MetaConfigIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """Onboarding page saves the Meta connection for this restaurant."""
    from app.identity.meta_config import apply_meta_settings

    apply_meta_settings(restaurant, body.model_dump(exclude_unset=True))
    # Manual connect: sync the routing phone from the pasted number too (once both
    # the number id and token are present), matching the popup's behaviour.
    from app.identity.meta_config import meta_settings
    from app.identity.meta_embed import fetch_display_phone_number

    cfg = meta_settings(restaurant)
    if cfg["wa_phone_number_id"] and cfg["wa_access_token"]:
        display = await fetch_display_phone_number(
            cfg["wa_phone_number_id"], cfg["wa_access_token"]
        )
        await _set_connected_phone(session, restaurant, display)
    await session.commit()
    await session.refresh(restaurant)
    return _meta_config_out(restaurant)


@router.post("/onboarding/meta-disconnect", response_model=MetaConfigOut)
async def meta_disconnect(
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """Disconnect this restaurant's WhatsApp (Meta) account: clears its stored
    creds and re-opens onboarding. The manager must reconnect to operate again.
    Menu/catalogue/orders are untouched."""
    from app.identity.meta_config import disconnect_meta

    disconnect_meta(restaurant)
    await session.commit()
    await session.refresh(restaurant)
    return _meta_config_out(restaurant)


@router.get("/onboarding/meta-embed-config", response_model=MetaEmbedConfigOut)
async def get_meta_embed_config(_: Restaurant = Depends(current_restaurant)):
    """Config the frontend needs to launch the Embedded Signup ("Connect with
    Facebook") popup. `enabled` is False when the tech-provider app isn't set up —
    the UI then falls back to the manual paste form. No secrets returned."""
    from app.config import get_settings

    settings = get_settings()
    return MetaEmbedConfigOut(
        enabled=bool(settings.wa_app_id and settings.wa_es_config_id),
        app_id=settings.wa_app_id,
        config_id=settings.wa_es_config_id,
        graph_version=settings.graph_api_version,
    )


@router.post("/onboarding/meta-connect", response_model=MetaConfigOut)
async def meta_connect(
    body: MetaConnectIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """Embedded Signup popup result → exchange the code for this restaurant's own
    long-lived token, subscribe our app to its WABA, and store the creds. The token
    is never returned; the manager just sees Connected."""
    from app.identity.meta_config import apply_meta_settings
    from app.identity.meta_embed import MetaEmbedError, connect_embedded_signup
    from app.partner.integration import provision_partner_integration

    try:
        creds = await connect_embedded_signup(
            code=body.code,
            phone_number_id=body.phone_number_id,
            waba_id=body.waba_id,
            business_name=restaurant.name or "",
            existing_pin=(restaurant.settings or {}).get("wa_2fa_pin", "") or "",
        )
    except MetaEmbedError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    display_number = creds.pop("display_phone_number", "")
    apply_meta_settings(restaurant, creds)
    await _set_connected_phone(session, restaurant, display_number)
    # Auto-provision the POS partner integration: wire the global webhook + mint this
    # store's API key (returned once) so Cratis can talk to it with no manual setup.
    api_key = await provision_partner_integration(session, restaurant)
    await session.commit()
    await session.refresh(restaurant)
    out = _meta_config_out(restaurant)
    out.api_key = api_key
    return out


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
        rider = await service.create_rider(
            session,
            restaurant_id=restaurant.id,
            name=body.name,
            phone=body.phone,
        )
    except DuplicatePhoneError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))

    # Auto-invite: as soon as a rider is added, WhatsApp them the app download
    # link + a one-time pairing code so they can install and pair the rider app.
    # Best-effort — a send hiccup must not fail the (already-committed) creation.
    try:
        from app.dispatch.rider_app import send_rider_app_pairing
        from app.outbox.service import deliver_pending

        await send_rider_app_pairing(session, rider=rider)
        await session.commit()
        await deliver_pending(session, restaurant.id)
    except Exception:  # noqa: BLE001 - invite is best-effort
        _logger.exception("auto app-invite failed for rider %s", rider.id)
    return rider


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
    elif body.on_duty is not None:
        rider = await service.set_rider_on_duty(
            session,
            restaurant_id=restaurant.id,
            rider_id=rider_id,
            on_duty=body.on_duty,
        )
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
