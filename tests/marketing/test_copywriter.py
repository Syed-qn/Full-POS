"""Template copywriter post-processing — no dashes, no back-to-back emojis.

The AI body is cleaned before it reaches the manager: em/en/standalone dashes
become commas (compound hyphens kept) and runs of adjacent emojis collapse to a
single emoji. Pure string logic — no LLM, no DB.
"""
from app.marketing.copywriter import _dedupe_adjacent_emoji
from app.llm.port import strip_dashes


def _clean(s: str) -> str:
    return _dedupe_adjacent_emoji(strip_dashes(s))


def test_adjacent_emojis_collapse_to_first():
    # "🍽️🔥" -> "🍽️" (fork-and-knife kept, fire dropped)
    assert _dedupe_adjacent_emoji("meat \U0001F37D️\U0001F525 here") == "meat \U0001F37D️ here"


def test_triple_run_collapses_to_first():
    out = _dedupe_adjacent_emoji("\U0001F389\U0001F38A\U0001F37D done")
    assert "\U0001F389" in out and "\U0001F38A" not in out and "\U0001F37D" not in out


def test_lone_emoji_preserved():
    assert _dedupe_adjacent_emoji("just \U0001F525 one").count("\U0001F525") == 1


def test_separated_emojis_preserved():
    # Emojis with words between them are fine, only back-to-back collapses.
    s = "tasty \U0001F60B order now \U0001F389"
    assert _dedupe_adjacent_emoji(s) == s


def test_dashes_stripped_but_compound_hyphens_kept():
    assert _clean("meat – a taste") == "meat, a taste"
    assert _clean("long-grain rice, extra-tender") == "long-grain rice, extra-tender"
