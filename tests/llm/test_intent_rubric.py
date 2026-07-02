"""E-17 intent rubric for ambiguous router UNKNOWN turns."""

import pytest

from app.conversation.intent_rubric import (
    is_checkout_intent,
    is_completion_intent,
    is_done_intent,
    resolve_ambiguous_intent,
)


@pytest.mark.parametrize(
    "text",
    ["done", "checkout", "that's all", "thats all"],
)
def test_is_checkout_intent_recognizes_completion_phrases(text: str) -> None:
    assert is_checkout_intent(text)


@pytest.mark.parametrize(
    "text",
    ["nothing else", "im done", "that is all", "no thats all"],
)
def test_is_done_intent_recognizes_variants(text: str) -> None:
    assert is_done_intent(text)


def test_resolve_ambiguous_intent_checkout_when_cart_nonempty() -> None:
    assert resolve_ambiguous_intent("that's all", "ordering", cart_nonempty=True) == "checkout"


def test_resolve_ambiguous_intent_checkout_suppressed_when_cart_empty() -> None:
    assert resolve_ambiguous_intent("that's all", "ordering", cart_nonempty=False) is None


def test_resolve_ambiguous_intent_question_tie_abstains() -> None:
    """Interrogatives often tie with add because parse_qty_and_text yields a qty."""
    assert resolve_ambiguous_intent("how spicy is it?", "ordering", cart_nonempty=False) is None


def test_resolve_ambiguous_intent_add_from_qty_phrase() -> None:
    assert resolve_ambiguous_intent("2 chicken biryani", "ordering", cart_nonempty=False) == "add"


def test_resolve_ambiguous_intent_add_from_want_phrase() -> None:
    assert resolve_ambiguous_intent("want karahi", "ordering", cart_nonempty=False) == "add"


def test_resolve_ambiguous_intent_returns_none_outside_ordering_phases() -> None:
    assert resolve_ambiguous_intent("2 biryani", "post_order", cart_nonempty=True) is None


def test_resolve_ambiguous_intent_returns_none_for_empty_text() -> None:
    assert resolve_ambiguous_intent("", "ordering", cart_nonempty=True) is None


def test_resolve_ambiguous_intent_bare_no_scores_add_from_qty_parser() -> None:
    # parse_qty_and_text treats bare "no" as qty=1, so add wins over checkout.
    assert resolve_ambiguous_intent("no", "ordering", cart_nonempty=True) == "add"


@pytest.mark.parametrize("text", ["khalas", "bas", "done", "that's all"])
def test_is_completion_intent_multilingual_and_english(text: str) -> None:
    assert is_completion_intent(text)


def test_is_completion_intent_rejects_dish_name() -> None:
    assert not is_completion_intent("chicken biryani")


def test_is_completion_intent_rejects_no_onion() -> None:
    assert not is_completion_intent("no onion")