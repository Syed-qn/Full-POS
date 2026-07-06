"""Pure-function coverage for category-availability parsing.

Prod regressions (Lims transcript):
- "Drink" on its own → "Sorry, we don't have Drink on our menu" (bare category word
  was not recognised, fell to the dish-not-found path).
- "Any other drink" → "we don't have other drink on the menu" (the follow-up word
  "other" polluted the category keyword).
- "Any other" → "we don't have other on the menu" ("other" treated as a dish).

Food words like "biryani"/"pizza" must STAY a normal dish order (return None), never a
category dump — otherwise typing a dish name to order it would list instead of add.
"""
from app.conversation.engine import _parse_category_availability_query as cat


def test_bare_drink_family_is_a_browse_query():
    for text in ("Drink", "drink", "drinks", "beverage", "beverages",
                 "cold drink", "soft drinks", "something to drink"):
        assert cat(text) == "drink", text


def test_follow_up_words_resolve_to_the_category():
    # "any other drink" / "another drink" / "more drinks" all mean the drink category.
    for text in ("any other drink", "another drink", "more drinks", "any other soup"):
        assert cat(text) in ("drink", "soup"), text
    assert cat("any other drink") == "drink"
    assert cat("any other soup") == "soup"


def test_bare_follow_up_word_carries_no_category():
    # "any other" / "anything else" name no dish — must fall through to the AI, never
    # render "we don't have other on the menu".
    for text in ("any other", "anything else", "some more", "another"):
        assert cat(text) is None, text


def test_food_words_stay_dish_orders_not_category_dumps():
    # A bare food word is an ORDER intent, not a "show me the category" browse.
    for text in ("biryani", "pizza", "burger", "add biryani", "i want biryani",
                 "1 chicken biryani"):
        assert cat(text) is None, text


def test_still_recognises_explicit_category_questions():
    assert cat("do you have any drinks") == "drink"
    assert cat("u have soup") == "soup"
    assert cat("any soup") == "soup"
