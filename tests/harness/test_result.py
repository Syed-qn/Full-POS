from decimal import Decimal
from tests.harness.result import OutboundCapture, TranscriptTurnResult, TranscriptResult


def test_result_helpers():
    t1 = TranscriptTurnResult(
        inbound_text="one biryani",
        outbounds=[OutboundCapture(prefix="ai-add", body="Added 1x", msg_type="text")],
        cart_rows=[{"dish_id": 1, "dish_name": "Chicken Biryani", "variant_name": None,
                    "notes": None, "qty": 1, "price_aed": Decimal("20.00")}],
        subtotal=Decimal("20.00"), total=Decimal("20.00"),
        phase="ordering", state={"draft_order_id": 5},
    )
    res = TranscriptResult(turns=[t1])
    assert res.last_outbound().body == "Added 1x"
    assert res.final_cart()[0]["dish_name"] == "Chicken Biryani"
