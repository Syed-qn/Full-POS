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
    """Tenant context for the manager/admin surface.

    Accepts EITHER the owner login token (aud=manager) OR a staff PIN token whose
    role is ``manager``. It used to accept the owner token only, which made every
    one of its ~270 call sites 403 for a manager signed in with a PIN — the whole
    manager nav (riders, menu, settings, reports, inventory…) was unusable for the
    role it was built for, and the failures were silent in the UI: a rejected
    request just left a button disabled or a list empty.

    Non-manager staff (cashier, waiter, kitchen) still get 403 here — their
    surfaces use ``current_restaurant_any`` or an explicit ``require_role``.
    """
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing token")
    try:
        restaurant_id = decode_access_token(creds.credentials)
    except ValueError:
        # Not an owner token. A VALID staff PIN token means the caller is
        # authenticated, so the answer is 403 (forbidden), never 401 — a 401 here
        # would trip the frontend's auth interceptor and log a legitimate staff
        # session straight out to /login. Only a bad/expired token yields 401.
        try:
            claims = decode_token(creds.credentials, audience="staff")
        except ValueError:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
        if claims.get("role") != "manager":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "manager access required")
        # Manager on a PIN session — resolve the tenant through their staff row.
        from app.staff.models import StaffMember

        staff = await session.get(StaffMember, int(claims["sub"]))
        if staff is None or not staff.is_active:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown staff member")
        restaurant_id = staff.restaurant_id
    restaurant = await session.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown restaurant")
    return restaurant
