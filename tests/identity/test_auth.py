import pytest

from app.identity.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip():
    h = hash_password("hunter2!")
    assert h != "hunter2!"
    assert verify_password("hunter2!", h)
    assert not verify_password("wrong", h)


def test_jwt_roundtrip():
    token = create_access_token(restaurant_id=7)
    assert decode_access_token(token) == 7


def test_jwt_garbage_rejected():
    with pytest.raises(ValueError):
        decode_access_token("not.a.token")
