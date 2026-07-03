"""Dish suggestion sub-agent — grounded picks from menu candidates only."""
from __future__ import annotations

import json
import re

_SUGGESTION_SYSTEM = """\
[ROLE]
You are a restaurant WhatsApp dish recommender.

[TASK]
Pick 1–3 dishes from MENU CANDIDATES that best match the customer's request.

[INPUT]
You receive MENU CANDIDATES (authoritative list with name, category, description),
CUSTOMER TEXT (what they asked for, any language), and an optional BROWSE FILTER
(ingredient/category they were browsing).

[INSTRUCTIONS]
- Choose only dishes whose exact names appear in MENU CANDIDATES.
- Write a short, friendly intro (one line) and a one-line reason per pick (no prices).
- If nothing fits well, return empty picks and an intro asking a clarifying question.

[CONSTRAINTS]
- NEVER invent dish names not in MENU CANDIDATES.
- NEVER include prices or AED amounts in intro or reasons.
- Pick at most 3 items.
- Keep total customer-facing output to 3 lines or fewer (intro + picks).

[TONE]
Warm, concise, customer-facing WhatsApp chat. Light emoji OK in intro only.

[OUTPUT]
JSON ONLY with exactly two keys:
- "intro": short friendly line (or clarifying question when picks is empty).
- "picks": array of 0–3 objects, each with "dish_name" (exact menu name) and
  "reason" (max one line, no price).
"""

SUGGESTION_SYSTEM = _SUGGESTION_SYSTEM


def build_suggestion_prompt(
    menu_candidates: list[dict],
    customer_text: str,
    browse_filter: str | None = None,
) -> str:
    """User turn for the suggestion sub-agent."""
    lines = []
    for c in menu_candidates:
        name = c.get("name") or "?"
        cat = c.get("category") or ""
        desc = (c.get("description") or "").strip()
        part = f"- {name}"
        if cat:
            part += f" ({cat})"
        if desc:
            part += f": {desc[:120]}"
        lines.append(part)
    menu_block = "\n".join(lines) if lines else "(none)"
    return (
        f"MENU CANDIDATES:\n{menu_block}\n\n"
        f"CUSTOMER TEXT:\n{customer_text or '(none)'}\n\n"
        f"BROWSE FILTER:\n{browse_filter or '(none)'}\n\n"
        'Reply with JSON only: {"intro": "...", "picks": '
        '[{"dish_name": "...", "reason": "..."}]}'
    )


def parse_suggestion_response(raw: str) -> dict:
    """Parse suggestion sub-agent JSON into ``{intro, picks: [{dish_name, reason}]}``."""
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"SuggestionAgent returned non-JSON: {exc}") from exc

    intro = (parsed.get("intro") or "").strip()
    if not intro:
        intro = "Here are a few ideas for you!"

    picks: list[dict] = []
    for item in parsed.get("picks") or []:
        if not isinstance(item, dict):
            continue
        dish_name = (item.get("dish_name") or "").strip()
        reason = (item.get("reason") or "").strip()
        if dish_name:
            picks.append({"dish_name": dish_name, "reason": reason})
        if len(picks) >= 3:
            break

    return {"intro": intro, "picks": picks}


class DeepSeekSuggestionAgent:
    """Production dish recommender — DeepSeek chat API."""

    async def suggest(
        self,
        menu_candidates: list[dict],
        customer_text: str,
        browse_filter: str | None = None,
    ) -> dict:
        from app.llm.deepseek import _async_chat, _get_deepseek_settings

        api_key, model = _get_deepseek_settings()
        prompt = build_suggestion_prompt(menu_candidates, customer_text, browse_filter)
        raw = await _async_chat(
            api_key,
            model,
            [
                {"role": "system", "content": _SUGGESTION_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=384,
            temperature=0.3,
        )
        return parse_suggestion_response(raw)


class ClaudeSuggestionAgent:
    """Production dish recommender — Claude haiku."""

    def __init__(self) -> None:
        from app.llm.factory import _get_anthropic_client

        self._client = _get_anthropic_client()

    async def suggest(
        self,
        menu_candidates: list[dict],
        customer_text: str,
        browse_filter: str | None = None,
    ) -> dict:
        from app.llm.claude import _first_text

        prompt = build_suggestion_prompt(menu_candidates, customer_text, browse_filter)
        msg = self._client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=384,
            temperature=0.3,
            system=_SUGGESTION_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return parse_suggestion_response(_first_text(msg))