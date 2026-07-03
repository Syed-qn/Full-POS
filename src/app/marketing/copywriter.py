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
from app.llm.port import strip_dashes
from app.llm.prompts_marketing import COPYWRITER_PROMPT, TEMPLATE_FIX_PROMPT

_logger = logging.getLogger(__name__)

# One emoji "unit": a base emoji glyph + optional skin-tone + optional VS16,
# plus any ZWJ-joined continuation so family/profession sequences stay intact.
_EMOJI_CORE = (
    r"[\U0001F300-\U0001FAFF"  # symbols & pictographs (+ supplemental/extended-A)
    r"\U00002600-\U000027BF"  # misc symbols + dingbats
    r"\U00002B00-\U00002BFF"  # stars, arrows
    r"\U00002300-\U000023FF"  # ⌚⏰ etc.
    r"\U0001F1E6-\U0001F1FF]"  # regional indicators (flags)
)
_EMOJI_UNIT = (
    rf"{_EMOJI_CORE}[\U0001F3FB-\U0001F3FF]?️?"
    rf"(?:‍{_EMOJI_CORE}[\U0001F3FB-\U0001F3FF]?️?)*"
)
_ADJACENT_EMOJI_RE = re.compile(rf"({_EMOJI_UNIT})(?:{_EMOJI_UNIT})+")


def _dedupe_adjacent_emoji(text: str) -> str:
    """Collapse runs of back-to-back emojis to a single emoji (no '🍽️🔥')."""
    if not text:
        return text
    return _ADJACENT_EMOJI_RE.sub(lambda m: m.group(1), text)

def _slug(describe: str) -> str:
    words = re.findall(r"[a-z0-9]+", describe.lower())[:4]
    return ("promo_" + "_".join(words))[:60] or "promo_offer"


def _fallback(describe: str) -> dict:
    body = (
        f"Hi {{{{1}}}}, we've got something tasty for you 😋 "
        f"{describe.strip()}. Reply to this message to order. See you soon! 🍽️"
    )
    return {"body": body, "footer": "Reply STOP to opt out"}


async def draft_template(*, restaurant_name: str, describe: str) -> dict:
    """Return ``{suggested_name, body, footer, examples}`` for the offer."""
    settings = get_settings()
    prompt = COPYWRITER_PROMPT.format(restaurant=restaurant_name or "our restaurant", describe=describe.strip())
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
    # No hyphens/em/en-dashes, and never two emojis back-to-back (manager pref).
    body = _dedupe_adjacent_emoji(strip_dashes(body))
    # Guarantee exactly one {{1}} placeholder (Meta rejects mismatched samples).
    if "{{1}}" not in body:
        body = "Hi {{1}}, " + body
    return {
        "suggested_name": _slug(describe),
        "body": body,
        "footer": drafted.get("footer") or "Reply STOP to opt out",
        "examples": ["Ahmed"],
    }


def _fallback_fix(*, body: str, rejection_reason: str | None) -> dict:
    """Rule-based revision when LLM is unavailable."""
    revised = body
    reason = (rejection_reason or "").lower()
    if "url" in reason or "link" in reason:
        revised = re.sub(r"https?://\S+", "", revised)
    revised = _dedupe_adjacent_emoji(strip_dashes(revised.strip()))
    if "{{1}}" not in revised:
        revised = "Hi {{1}}, " + revised
    return {"body": revised, "footer": "Reply STOP to opt out"}


async def fix_template_body(
    *,
    restaurant_name: str,
    body: str,
    rejection_reason: str | None,
    hint: str | None = None,
) -> dict:
    """Return ``{body, footer}`` revising a rejected template for Meta resubmit."""
    settings = get_settings()
    prompt = TEMPLATE_FIX_PROMPT.format(
        restaurant=restaurant_name or "our restaurant",
        rejection_reason=rejection_reason or "unspecified",
        body=body.strip(),
        hint=hint or "",
    )
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
    except Exception as exc:  # noqa: BLE001
        _logger.warning("template fix via %s failed: %s", settings.llm_provider, exc)
        drafted = None

    if not isinstance(drafted, dict) or not drafted.get("body"):
        drafted = _fallback_fix(body=body, rejection_reason=rejection_reason)

    fixed_body = _dedupe_adjacent_emoji(strip_dashes(str(drafted["body"]).strip()))
    if "{{1}}" not in fixed_body:
        fixed_body = "Hi {{1}}, " + fixed_body
    return {
        "body": fixed_body,
        "footer": drafted.get("footer") or "Reply STOP to opt out",
    }
