from app.identity.auth import hash_password, verify_password

# A hash produced by the old passlib CryptContext(schemes=["argon2"]) for
# "passlib-era-secret". argon2-cffi must verify it natively (same PHC format)
# so existing stored password hashes keep working after the swap.
_PASSLIB_ERA_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4"
    "$2juHUKpVivEeg5CS8h7DGA$buk0GQCaRAYV3fUCT9SgQOrfK866cw3yLpCaEvFuR3k"
)


def test_hash_roundtrip():
    h = hash_password("s3cret-pass")
    assert h.startswith("$argon2id$")
    assert verify_password("s3cret-pass", h) is True
    assert verify_password("wrong", h) is False


def test_hashes_are_salted_unique():
    assert hash_password("same") != hash_password("same")


def test_verifies_legacy_passlib_hash():
    assert verify_password("passlib-era-secret", _PASSLIB_ERA_HASH) is True
    assert verify_password("wrong", _PASSLIB_ERA_HASH) is False


def test_no_passlib_import():
    import app.identity.auth as auth

    assert "passlib" not in repr(auth.__dict__)
