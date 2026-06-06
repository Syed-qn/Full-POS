from app.llm.fake import FakeDescriber, FakeIntentClassifier, FakeArbiter
from app.llm.port import DescriberPort, IntentClassifierPort, ArbiterPort


def test_fake_describer_returns_max_3_lines():
    describer = FakeDescriber()
    result = describer.describe("Chicken Biryani", "Fragrant basmati rice cooked with tender chicken.")
    lines = [ln for ln in result.strip().split("\n") if ln.strip()]
    assert 1 <= len(lines) <= 3


def test_fake_describer_never_includes_price():
    describer = FakeDescriber()
    result = describer.describe("Chicken Biryani", "Fragrant basmati rice with chicken.", price_hint="22.00")
    assert "22" not in result
    assert "AED" not in result


def test_fake_intent_classifier_returns_known_intent():
    classifier = FakeIntentClassifier()
    # known intents: "order_item", "dish_question", "cancel", "modify", "status", "other"
    intent = classifier.classify("I want to cancel my order")
    assert intent in {"order_item", "dish_question", "cancel", "modify", "status", "other"}


async def test_fake_arbiter_returns_one_of_candidates():
    arbiter = FakeArbiter()
    from decimal import Decimal
    # Create minimal Dish-like objects
    class MockDish:
        dish_number = 110
        name = "Chicken Biryani"
        price_aed = Decimal("22.00")

    candidates = [MockDish()]
    result = await arbiter.arbitrate("chkn biry", candidates)
    assert result is candidates[0]


def test_describer_protocol_satisfied_by_fake():
    """FakeDescriber satisfies DescriberPort Protocol (structural check)."""
    d: DescriberPort = FakeDescriber()
    assert callable(d.describe)


def test_intent_classifier_protocol_satisfied_by_fake():
    c: IntentClassifierPort = FakeIntentClassifier()
    assert callable(c.classify)


def test_arbiter_protocol_satisfied_by_fake():
    a: ArbiterPort = FakeArbiter()
    assert callable(a.arbitrate)
