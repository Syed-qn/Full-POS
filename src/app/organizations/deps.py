from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.auth import decode_token
from app.identity.models import Restaurant
from app.organizations.models import Organization
from app.staff.models import StaffMember

_bearer = HTTPBearer(auto_error=False)


async def current_organization(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> Organization:
    """Resolve the multi-branch HQ context.

    Accepts:
    1. Organization JWT (``aud=org``) — classic HQ login.
    2. Restaurant **owner** token (``aud=manager`` restaurant account, or staff
       with ``role=owner``) when that restaurant is already linked via
       ``organization_id``. Branch managers (staff ``role=manager``) are denied —
       they run one store, not franchise HQ.
    """
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing token")

    # 1) Dedicated org token.
    try:
        claims = decode_token(creds.credentials, audience="org")
        org_id = int(claims["sub"])
        org = await session.get(Organization, org_id)
        if org is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown organization")
        return org
    except ValueError:
        pass
    except (KeyError, TypeError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")

    restaurant: Restaurant | None = None

    # 2) Restaurant account (owner login).
    try:
        claims = decode_token(creds.credentials, audience="manager")
        restaurant = await session.get(Restaurant, int(claims["sub"]))
    except (ValueError, KeyError, TypeError):
        restaurant = None

    # 3) Staff PIN — only role=owner may act as multi-branch HQ.
    if restaurant is None:
        try:
            claims = decode_token(creds.credentials, audience="staff")
        except ValueError:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
        role = claims.get("role")
        if role != "owner":
            # Managers operate a single branch; they must not open HQ surfaces.
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "owner access required for multi-branch HQ",
            )
        staff = await session.get(StaffMember, int(claims["sub"]))
        if staff is None or not staff.is_active:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown staff member")
        restaurant = await session.get(Restaurant, staff.restaurant_id)

    if restaurant is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown restaurant")
    if restaurant.organization_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "restaurant is not linked to an organization — call POST /api/v1/organizations/bootstrap",
        )
    org = await session.get(Organization, restaurant.organization_id)
    if org is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown organization")
    return org
