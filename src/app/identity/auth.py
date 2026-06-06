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


def create_access_token(restaurant_id: int) -> str:
    s = get_settings()
    payload = {
        "sub": str(restaurant_id),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=s.jwt_ttl_minutes),
    }
    return jwt.encode(payload, s.jwt_secret.get_secret_value(), algorithm=_ALGO)


def decode_access_token(token: str) -> int:
    s = get_settings()
    try:
        payload = jwt.decode(token, s.jwt_secret.get_secret_value(), algorithms=[_ALGO])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise ValueError("invalid token") from exc
