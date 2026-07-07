from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.config import get_settings

# argon2id with argon2-cffi's OWASP-acceptable defaults. Produces and verifies
# the same "$argon2id$" PHC strings the previous passlib backend emitted, so
# existing stored password hashes keep verifying unchanged.
_ph = PasswordHasher()
_ALGO = "HS256"


def hash_password(plain: str) -> str:
    return _ph.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_access_token(
    *,
    restaurant_id: int | None = None,
    rider_id: int | None = None,
    org_id: int | None = None,
    audience: str = "manager",
) -> str:
    s = get_settings()
    sub = str(next(v for v in (restaurant_id, rider_id, org_id) if v is not None))
    payload = {
        "sub": sub,
        "aud": audience,
        "iss": s.jwt_issuer,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=s.jwt_ttl_minutes),
    }
    return jwt.encode(payload, s.jwt_secret.get_secret_value(), algorithm=_ALGO)


def decode_token(token: str, *, audience: str) -> dict:
    """Decode and verify a JWT, enforcing aud and iss. Returns full claims dict."""
    s = get_settings()
    try:
        return jwt.decode(
            token,
            s.jwt_secret.get_secret_value(),
            algorithms=[_ALGO],
            audience=audience,
            issuer=s.jwt_issuer,
        )
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise ValueError("invalid token") from exc


def decode_access_token(token: str) -> int:
    """Backward-compat wrapper: decode a manager token, return restaurant_id as int."""
    claims = decode_token(token, audience="manager")
    try:
        return int(claims["sub"])
    except (KeyError, ValueError) as exc:
        raise ValueError("invalid token") from exc
