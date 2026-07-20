from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.auth import decode_access_token, decode_token
from app.identity.models import Restaurant

_bearer = HTTPBearer(auto_error=False)


async def current_restaurant(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> Restaurant:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing token")
    try:
        restaurant_id = decode_access_token(creds.credentials)
    except ValueError:
        # Not a manager/owner token. If it's a VALID staff PIN token, the caller
        # is authenticated but simply lacks access to this manager-only endpoint —
        # that's a 403 (forbidden), NOT a 401. Returning 401 here would make the
        # frontend's auth interceptor log a valid staff session straight out to
        # /login the moment it hits any manager-only route. Only a genuinely
        # invalid/expired token yields 401.
        try:
            decode_token(creds.credentials, audience="staff")
        except ValueError:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "manager access required")
    restaurant = await session.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown restaurant")
    return restaurant
