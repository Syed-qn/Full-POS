from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.db import get_session
from app.identity.auth import create_access_token, hash_password, verify_password
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.identity.schemas import LoginIn, RestaurantOut, SignupIn, TokenOut

router = APIRouter(prefix="/api/v1", tags=["identity"])

_DUMMY_HASH = hash_password("dummy-timing-equalizer-not-a-real-password")


@router.post("/auth/signup", response_model=RestaurantOut, status_code=201)
async def signup(body: SignupIn, session: AsyncSession = Depends(get_session)):
    existing = await session.scalar(
        select(Restaurant).where(Restaurant.phone == body.phone)
    )
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "phone already registered")
    restaurant = Restaurant(
        name=body.name,
        phone=body.phone,
        password_hash=hash_password(body.password),
        lat=body.lat,
        lng=body.lng,
    )
    session.add(restaurant)
    await session.flush()
    await record_audit(
        session,
        actor="manager",
        restaurant_id=restaurant.id,
        entity="restaurant",
        entity_id=str(restaurant.id),
        action="signup",
        after={"name": body.name, "phone": body.phone, "lat": body.lat, "lng": body.lng},
    )
    await session.commit()
    return restaurant


@router.post("/auth/login", response_model=TokenOut)
async def login(body: LoginIn, session: AsyncSession = Depends(get_session)):
    restaurant = await session.scalar(
        select(Restaurant).where(Restaurant.phone == body.phone)
    )
    if restaurant is None:
        verify_password(body.password, _DUMMY_HASH)  # equalize timing
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad credentials")
    if not verify_password(body.password, restaurant.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad credentials")
    return TokenOut(access_token=create_access_token(restaurant.id))


@router.get("/me", response_model=RestaurantOut)
async def me(restaurant: Restaurant = Depends(current_restaurant)):
    return restaurant
