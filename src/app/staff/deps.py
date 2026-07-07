from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.auth import decode_token
from app.identity.models import Restaurant
from app.staff.models import StaffMember

_bearer = HTTPBearer(auto_error=False)


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
