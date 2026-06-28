from app.coupons.service import generate_code

_AMBIGUOUS = set("01OIL")


def test_code_has_prefix_and_entropy():
    code = generate_code(prefix="SAVE", length=10)
    assert code.startswith("SAVE-")
    body = code.split("-", 1)[1]
    assert len(body) == 10


def test_code_avoids_ambiguous_chars():
    for _ in range(50):
        body = generate_code().split("-", 1)[1]
        assert not (_AMBIGUOUS & set(body)), f"ambiguous char in {body}"


def test_codes_are_unique_across_calls():
    codes = {generate_code() for _ in range(200)}
    assert len(codes) == 200  # no collisions at ~50 bits
