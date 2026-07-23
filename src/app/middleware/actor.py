"""Stamps the acting staff member onto the request context for the audit log.

Staff tokens carry ``sub`` = staff_members.id and ``aud`` = "staff". Decoding
that once per request is what lets every audit row say "Demo Cashier" instead
of just "cashier". Manager/owner tokens carry a restaurant id, not a staff id,
so they leave the context empty and keep recording the role.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.audit.context import current_actor_staff_id
from app.identity.auth import decode_token


class ActorContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        token_staff_id: int | None = None
        auth = request.headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            try:
                claims = decode_token(auth.split(" ", 1)[1].strip(), audience="staff")
                token_staff_id = int(claims["sub"])
            except (ValueError, KeyError, TypeError):
                # Manager/owner token, expired, or malformed — no staff identity.
                token_staff_id = None

        reset = current_actor_staff_id.set(token_staff_id)
        try:
            return await call_next(request)
        finally:
            current_actor_staff_id.reset(reset)
