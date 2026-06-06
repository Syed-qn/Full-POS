from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from app.config import get_settings

_pwd = CryptContext(schemes=["argon2"], deprecated="auto")
_ALGO = "HS256"


def hash_password(plain: str) -> str:
    return _pwd.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd.verify(plain, hashed)


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
    except jwt.PyJWTError as exc:
        raise ValueError("invalid token") from exc
    return int(payload["sub"])
