from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.auth import decode_token
from app.organizations.models import Organization

_bearer = HTTPBearer(auto_error=False)


async def current_organization(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> Organization:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing token")
    try:
        claims = decode_token(creds.credentials, audience="org")
        org_id = int(claims["sub"])
    except (ValueError, KeyError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
    org = await session.get(Organization, org_id)
    if org is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown organization")
    return org
