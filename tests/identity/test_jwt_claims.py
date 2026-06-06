# tests/identity/test_jwt_claims.py
import pytest

from app.identity.auth import create_access_token, decode_access_token, decode_token


def test_manager_token_carries_iss_and_aud():
    tok = create_access_token(restaurant_id=7, audience="manager")
    claims = decode_token(tok, audience="manager")
    assert claims["sub"] == "7"
    assert claims["aud"] == "manager"
    assert claims["iss"]  # issuer present


def test_wrong_audience_rejected():
    tok = create_access_token(restaurant_id=7, audience="manager")
    with pytest.raises(Exception):  # jwt.InvalidAudienceError or ValueError
        decode_token(tok, audience="rider")


def test_rider_token_audience():
    tok = create_access_token(rider_id=3, audience="rider")
    claims = decode_token(tok, audience="rider")
    assert claims["aud"] == "rider"
    assert claims["sub"] == "3"


def test_backward_compat_no_audience_param():
    """Existing code creates tokens with just restaurant_id — must still work."""
    tok = create_access_token(restaurant_id=42)
    restaurant_id = decode_access_token(tok)
    assert restaurant_id == 42
