"""W4 Task 1 — top-level multilingual intent router: port + Fake impl.

The Fake is a deterministic test double.  These tests pin the router CONTRACT:
questions/complaints/reactions never classify as a mutation, closings are
checkout, explicit clear is only ever from an explicit phrase, and dish orders
(in ordering phase) are mutations — across a few languages/scripts.
"""
import pytest

from app.llm.factory import get_router_classifier
from app.llm.port import (
    MUTATING_INTENTS,
    NON_MUTATING_INTENTS,
    IntentLabel,
    RouterClassifierPort,
)
from app.llm.router_fake import FakeRouterClassifier


@pytest.fixture
def clf() -> RouterClassifierPort:
    return FakeRouterClassifier()


def test_factory_returns_fake_for_fake_provider(monkeypatch):
    # Default test settings use the fake provider.
    assert isinstance(get_router_classifier(), FakeRouterClassifier)


def test_intent_label_enum_members():
    values = {label.value for label in IntentLabel}
    assert values == {
        "mutation", "question", "complaint", "menu", "catalogue", "checkout",
        "address", "cancel", "clear", "show_cart", "greeting",
        "non_actionable", "unknown",
    }


def test_mutating_and_non_mutating_are_disjoint():
    assert MUTATING_INTENTS.isdisjoint(NON_MUTATING_INTENTS)
    # A question/complaint/reaction can NEVER be treated as a mutation.
    assert IntentLabel.QUESTION not in MUTATING_INTENTS
    assert IntentLabel.COMPLAINT not in MUTATING_INTENTS
    assert IntentLabel.NON_ACTIONABLE not in MUTATING_INTENTS


@pytest.mark.asyncio
async def test_dish_order_in_ordering_is_mutation(clf):
    assert await clf.classify_intent("one chicken biryani", "", "ordering") == (
        IntentLabel.MUTATION
    )
    assert await clf.classify_intent("2 lemon mint", "", "ordering") == (
        IntentLabel.MUTATION
    )


@pytest.mark.asyncio
async def test_why_did_you_add_is_complaint_never_mutation(clf):
    label = await clf.classify_intent(
        "Why did you add 2 biriyani", "1x Chicken Biryani", "ordering"
    )
    assert label == IntentLabel.COMPLAINT
    assert label not in MUTATING_INTENTS


@pytest.mark.asyncio
async def test_trailing_question_mark_is_question(clf):
    label = await clf.classify_intent("do you have mutton biryani?", "", "ordering")
    assert label == IntentLabel.QUESTION
    assert label not in MUTATING_INTENTS


@pytest.mark.asyncio
async def test_closings_are_checkout_multilingual(clf):
    for msg in ("done", "That's all", "bas", "khalas", "proceed"):
        assert await clf.classify_intent(msg, "1x Biryani", "ordering") == (
            IntentLabel.CHECKOUT
        ), msg


@pytest.mark.asyncio
async def test_only_x_is_not_clear(clf):
    # "only 1 biryani" is a correction/mutation, NEVER a clear-cart (F82/TX-36).
    label = await clf.classify_intent("only 1 biriyani", "2x Biryani", "ordering")
    assert label != IntentLabel.CLEAR
    assert label in MUTATING_INTENTS


@pytest.mark.asyncio
async def test_explicit_clear_is_clear(clf):
    assert await clf.classify_intent("clear my cart", "2x Biryani", "ordering") == (
        IntentLabel.CLEAR
    )
    assert await clf.classify_intent("start over", "2x Biryani", "ordering") == (
        IntentLabel.CLEAR
    )


@pytest.mark.asyncio
async def test_cancel_and_show_cart_and_menu(clf):
    assert await clf.classify_intent("cancel order", "", "ordering") == IntentLabel.CANCEL
    assert await clf.classify_intent("my cart", "", "ordering") == IntentLabel.SHOW_CART
    assert await clf.classify_intent("menu", "", "ordering") == IntentLabel.MENU


@pytest.mark.asyncio
async def test_greeting_bare_vs_greeting_with_order(clf):
    assert await clf.classify_intent("hi", "", "ordering") == IntentLabel.GREETING
    assert await clf.classify_intent("salam", "", "ordering") == IntentLabel.GREETING
    # Greeting mixed with an order is a mutation so the dish still lands.
    assert await clf.classify_intent("hi, one biryani", "", "ordering") == (
        IntentLabel.MUTATION
    )


@pytest.mark.asyncio
async def test_reaction_and_emoji_are_non_actionable(clf):
    for msg in ("👍", "❤️", "", "   "):
        assert await clf.classify_intent(msg, "1x Biryani", "ordering") == (
            IntentLabel.NON_ACTIONABLE
        ), repr(msg)


@pytest.mark.asyncio
async def test_non_english_question_is_question(clf):
    # Arabic "what is the best dish?" must be a question, not a mutation.
    label = await clf.classify_intent("ما هو أفضل طبق؟", "", "ordering")
    assert label == IntentLabel.QUESTION
    assert label not in MUTATING_INTENTS


@pytest.mark.asyncio
async def test_correction_before_completion_is_mutation_not_checkout(clf):
    # A correction naming an in-cart dish/qty during the confirm phase is a
    # mutation the flow must apply — NEVER a checkout, NEVER a silent add-on-top
    # (R-071/RA-5/R-075).  It must be in MUTATING_INTENTS so it reaches the edit path.
    for phase in ("ordering", "awaiting_confirmation"):
        label = await clf.classify_intent("only 1 biriyani", "2x Biryani", phase)
        assert label != IntentLabel.CHECKOUT
        assert label != IntentLabel.CLEAR
        assert label in MUTATING_INTENTS, (phase, label)


@pytest.mark.asyncio
async def test_complaint_naming_qty_is_never_checkout_or_mutation(clf):
    # "why did you add 2" names a quantity but is a complaint — must not be read
    # as a checkout or an add.
    label = await clf.classify_intent("why did you add 2", "2x Biryani", "ordering")
    assert label == IntentLabel.COMPLAINT
    assert label not in MUTATING_INTENTS
    assert label != IntentLabel.CHECKOUT


@pytest.mark.asyncio
async def test_unknown_outside_ordering_defaults_safe(clf):
    # An unrecognised phrase outside ordering falls through as UNKNOWN (which is
    # a MUTATING_INTENT → existing engine flow is preserved, nothing diverted).
    label = await clf.classify_intent("hmm let me think", "", "post_order")
    assert label == IntentLabel.UNKNOWN
    assert label in MUTATING_INTENTS
