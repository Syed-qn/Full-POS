from decimal import Decimal
from tests.harness.result import OutboundCapture, TranscriptTurnResult
from tests.harness.graders import (
    grade_no_duplicate_dish_line, grade_last_outbound_matches_cart,
    grade_no_mutation,
)


def _turn(cart, body="", inbound="x"):
    return TranscriptTurnResult(
        inbound_text=inbound,
        outbounds=[OutboundCapture("p", body, "text")] if body else [],
        cart_rows=cart, subtotal=Decimal("0"), total=Decimal("0"),
        phase="ordering", state={},
    )


def test_duplicate_line_detected():
    cart = [
        {"dish_id": 1, "variant_name": None, "dish_name": "Biryani", "notes": None, "qty": 1, "price_aed": Decimal("20")},
        {"dish_id": 1, "variant_name": None, "dish_name": "Biryani", "notes": "x", "qty": 1, "price_aed": Decimal("20")},
    ]
    assert grade_no_duplicate_dish_line(_turn(cart)).passed is False


def test_last_outbound_must_name_cart_dishes():
    cart = [{"dish_id": 1, "variant_name": None, "dish_name": "Lemon mint", "notes": None, "qty": 1, "price_aed": Decimal("12")}]
    assert grade_last_outbound_matches_cart(_turn(cart, body="Added 1x Lemon mint")).passed is True
    assert grade_last_outbound_matches_cart(_turn(cart, body="Added 1x Biryani")).passed is False


def test_no_mutation_on_question():
    cart = [{"dish_id": 1, "variant_name": None, "dish_name": "Biryani", "notes": None, "qty": 2, "price_aed": Decimal("20")}]
    assert grade_no_mutation(cart, _turn(cart)).passed is True
    grew = cart + [{"dish_id": 1, "variant_name": None, "dish_name": "Biryani", "notes": None, "qty": 1, "price_aed": Decimal("20")}]
    assert grade_no_mutation(cart, _turn(grew)).passed is False
