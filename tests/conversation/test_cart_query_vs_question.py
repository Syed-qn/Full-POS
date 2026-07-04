"""'_is_cart_query' must only match cart-LISTING requests, not any sentence that
happens to contain the word "cart".

Prod regression: "Is my cart good for lunch" hit the deterministic cart-dump
path (substring check `"cart" in t`) and got the generic "Reply with more
items, or send 'done'" — never answering the actual question. Genuine
opinion/suitability questions about the cart's contents must fall through to
the AI (which has the real cart grounded) instead of a canned listing.
"""
from app.conversation.engine import _is_cart_query


def test_matches_plain_listing_requests():
    for text in (
        "cart", "my cart", "show cart", "show my cart", "view cart",
        "what's in my cart", "whats in my cart", "what is in my cart",
        "check my cart", "what's my order", "show my order", "current order",
    ):
        assert _is_cart_query(text), text


def test_does_not_match_opinion_or_suitability_questions():
    for text in (
        "is my cart good for lunch",
        "is my cart healthy",
        "does my cart have enough food for 4 people",
        "is my cart too spicy",
        "what do you think of my cart",
    ):
        assert not _is_cart_query(text), text


def test_still_excludes_edit_and_cancel_actions():
    for text in ("cancel my order", "clear cart", "add to cart", "remove from cart", "empty my cart"):
        assert not _is_cart_query(text), text
