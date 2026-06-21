"""AI copywriter for WhatsApp marketing templates.

Turns a manager's plain-English offer ("20% off biryani this weekend") into a
Meta-compliant template body — first line personalised with ``{{1}}`` (the
customer's name), a clear CTA, no shortened URLs. Mirrors the DSC "describe your
offer → drafted template" flow. Falls back to a sensible default body when no LLM
is configured (or the call fails), so template creation never hard-depends on AI.
"""
from __future__ import annotations

import json
import logging
import re

from app.config import get_settings

_logger = logging.getLogger(__name__)

_PROMPT = (
    "You write WhatsApp marketing message templates for a restaurant called "
    "{restaurant}. Turn the offer below into ONE short, friendly template body.\n\n"
    "OFFER: {describe}\n\n"
    "RULES (Meta-compliant):\n"
    "- Start by greeting the customer with the placeholder {{{{1}}}} (their name), "
    "e.g. 'Hi {{{{1}}}},'.\n"
    "- Use {{{{1}}}} EXACTLY once and no other placeholders.\n"
    "- Max ~400 characters, no emoji spam, no shortened links, no ALL CAPS words.\n"
    "- End with a clear call to action (e.g. 'Reply to order').\n"
    'Reply with ONLY JSON: {{"body": "...", "footer": "Reply STOP to opt out"}}'
)


def _slug(describe: str) -> str:
    words = re.findall(r"[a-z0-9]+", describe.lower())[:4]
    return ("promo_" + "_".join(words))[:60] or "promo_offer"


def _fallback(describe: str) -> dict:
    body = (
        f"Hi {{{{1}}}}, we've got something for you at our restaurant: "
        f"{describe.strip()}. Reply to this message to order. See you soon!"
    )
    return {"body": body, "footer": "Reply STOP to opt out"}


async def draft_template(*, restaurant_name: str, describe: str) -> dict:
    """Return ``{suggested_name, body, footer, examples}`` for the offer."""
    settings = get_settings()
    prompt = _PROMPT.format(restaurant=restaurant_name or "our restaurant", describe=describe.strip())
    drafted: dict | None = None
    try:
        if settings.llm_provider == "deepseek" and settings.deepseek_api_key.get_secret_value():
            from app.llm.deepseek import _async_chat, _get_deepseek_settings

            api_key, model = _get_deepseek_settings()
            raw = await _async_chat(
                api_key, model, [{"role": "user", "content": prompt}], max_tokens=400
            )
            raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
            drafted = json.loads(raw)
        elif settings.llm_provider == "claude" and settings.anthropic_api_key.get_secret_value():
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())
            resp = await client.messages.create(
                model=settings.claude_model,
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text if resp.content else ""
            text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
            drafted = json.loads(text)
    except Exception as exc:  # noqa: BLE001 - AI is best-effort; fall back to a default body
        _logger.warning("template draft via %s failed: %s", settings.llm_provider, exc)
        drafted = None

    if not isinstance(drafted, dict) or not drafted.get("body"):
        drafted = _fallback(describe)

    body = str(drafted["body"]).strip()
    # Guarantee exactly one {{1}} placeholder (Meta rejects mismatched samples).
    if "{{1}}" not in body:
        body = "Hi {{1}}, " + body
    return {
        "suggested_name": _slug(describe),
        "body": body,
        "footer": drafted.get("footer") or "Reply STOP to opt out",
        "examples": ["Ahmed"],
    }
