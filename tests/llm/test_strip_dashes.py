"""strip_dashes: AI replies must not carry em/en-dash separators, but legitimate
compound-word hyphens (long-grain) stay intact."""
from app.llm.port import strip_dashes


def test_em_dash_separator_becomes_comma():
    assert (
        strip_dashes("The regular one is still good — it's our classic.")
        == "The regular one is still good, it's our classic."
    )


def test_en_dash_separator_becomes_comma():
    assert strip_dashes("Open 10 – 11 daily") == "Open 10, 11 daily"


def test_spaced_hyphen_separator_becomes_comma():
    assert strip_dashes("Both are great - your pick") == "Both are great, your pick"


def test_compound_word_hyphen_is_preserved():
    # No surrounding spaces → a real compound word, left untouched.
    assert strip_dashes("premium long-grain basmati rice") == "premium long-grain basmati rice"
    assert strip_dashes("extra-tender chicken") == "extra-tender chicken"


def test_no_dash_unchanged():
    assert strip_dashes("A step up with extra richness and saffron.") == (
        "A step up with extra richness and saffron."
    )


def test_empty_and_none_safe():
    assert strip_dashes("") == ""
    assert strip_dashes("plain") == "plain"
