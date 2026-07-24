from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.auth import decode_token
from app.identity.models import Restaurant
from app.staff.models import StaffMember

_bearer = HTTPBearer(auto_error=False)


async def current_actor(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """Who is performing this action, for FSM/audit attribution.

    Returns the staff role ("cashier" / "kitchen" / "manager") for a staff token,
    and "manager" for the owner token (which predates RBAC). Falls back to
    "manager" when there is no/invalid token so attribution never blocks a call.
    """
    if creds is None:
        return "manager"
    try:
        decode_token(creds.credentials, audience="manager")
        return "manager"  # owner token
    except ValueError:
        pass
    try:
        claims = decode_token(creds.credentials, audience="staff")
        return str(claims.get("role") or "manager")
    except ValueError:
        return "manager"


async def current_restaurant_any(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> Restaurant:
    """Restaurant context for ANY authenticated actor of the restaurant.

    Accepts the owner/manager token (aud=manager) OR any staff PIN token
    (aud=staff), resolving the tenant via the staff member's restaurant_id.
    Use for read-only shell/context + POS read endpoints (``/me``, active menu,
    order list) so staff sessions can load the app — unlike ``current_restaurant``
    (owner-only), a staff-audience token here does not 401 and log the user out.
    """
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing token")

    # Owner / manager token.
    try:
        claims = decode_token(creds.credentials, audience="manager")
        restaurant = await session.get(Restaurant, int(claims["sub"]))
        if restaurant is not None:
            return restaurant
    except ValueError:
        pass

    # Staff PIN token → resolve restaurant via staff_id.
    try:
        claims = decode_token(creds.credentials, audience="staff")
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")

    staff = await session.get(StaffMember, int(claims["sub"]))
    if staff is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown staff member")
    restaurant = await session.get(Restaurant, staff.restaurant_id)
    if restaurant is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown restaurant")
    return restaurant


def require_role(*roles: str):
    """Manager-only-style guard: the restaurant OWNER token always passes
    (it predates RBAC and must keep working unchanged); a STAFF token must
    carry one of the given roles. Returns the Restaurant either way, so it
    drops in wherever `Depends(current_restaurant)` is used today."""

    async def dependency(
        creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
        session: AsyncSession = Depends(get_session),
    ) -> Restaurant:
        if creds is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing token")

        try:
            claims = decode_token(creds.credentials, audience="manager")
            restaurant = await session.get(Restaurant, int(claims["sub"]))
            if restaurant is None:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown restaurant")
            return restaurant
        except ValueError:
            pass

        try:
            claims = decode_token(creds.credentials, audience="staff")
        except ValueError:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")

        if claims.get("role") not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient role")

        staff = await session.get(StaffMember, int(claims["sub"]))
        if staff is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown staff member")
        restaurant = await session.get(Restaurant, staff.restaurant_id)
        if restaurant is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown restaurant")
        return restaurant

    return dependency
