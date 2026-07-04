"""DeepSeek LLM provider — OpenAI-compatible API via httpx.

All ports mirror the Claude implementations. Sync methods use httpx sync client;
async methods (MenuExtractor) use httpx async client.
"""
import json
import logging
import re as _re
from functools import lru_cache

import httpx

from app.config import get_settings
from app.llm.action_schema import build_openai_tool, to_engine_result
from app.llm.conversation_prompts import build_identity, build_phase_block
from app.llm.port import ConversationAgentResult, DishDraft, UploadedFile, strip_dashes
from app.llm.prompts_menu import (
    ARBITRATE_TEMPLATE,
    DESCRIBE_DISH_TEMPLATE,
    EXTRACT_SYSTEM,
    FORECAST_OVERRIDE_TEMPLATE,
    INTENT_CLASSIFY_TEMPLATE,
    SEGMENT_COMPILE_TEMPLATE,
)
from app.llm.prompts_router import COMPLETION_DETECT_TEMPLATE, ROUTER_CLASSIFY_TEMPLATE

_logger = logging.getLogger(__name__)

_BASE = "https://api.deepseek.com"
_CHAT = f"{_BASE}/chat/completions"

# Models that CANNOT do forced function-calling (tool_choice). The conversation agent
# REQUIRES a structured take_action tool call every turn, so if one of these is
# configured (e.g. someone sets APP_DEEPSEEK_MODEL=deepseek-reasoner) every inbound
# message would error with "something went wrong". Guard: fall back to deepseek-chat and
# log loudly instead of failing on the live customer path.
_NON_TOOL_CALLING_MODELS = frozenset({
    "deepseek-reasoner", "deepseek-r1", "deepseek-reasoner-r1", "deepseek-reasoning",
})
_TOOL_CALLING_FALLBACK = "deepseek-chat"


def _safe_tool_model(model: str) -> str:
    """Return a model that supports function-calling; downgrade reasoning models to
    deepseek-chat (with a loud log) so the conversation path never silently breaks."""
    if (model or "").strip().lower() in _NON_TOOL_CALLING_MODELS:
        _logger.error(
            "deepseek_model=%r cannot do the function-calling the conversation agent "
            "requires; falling back to %r. Set APP_DEEPSEEK_MODEL=deepseek-chat.",
            model, _TOOL_CALLING_FALLBACK,
        )
        return _TOOL_CALLING_FALLBACK
    return model


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _sync_chat(api_key: str, model: str, messages: list, max_tokens: int = 512, temperature: float = 0.0) -> str:
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    r = httpx.post(_CHAT, headers=_headers(api_key), json=payload, timeout=30)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


async def _async_chat(api_key: str, model: str, messages: list, max_tokens: int = 4096, temperature: float = 0.0) -> str:
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(_CHAT, headers=_headers(api_key), json=payload)
        r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


@lru_cache
def _get_deepseek_settings():
    s = get_settings()
    return s.deepseek_api_key.get_secret_value(), s.deepseek_model


_EXTRACT_SYSTEM = EXTRACT_SYSTEM


class DeepSeekExtractor:
    async def extract_menu(self, files: list[UploadedFile]) -> list[DishDraft]:
        if not files:
            raise ValueError("extract_menu requires at least one file")

        api_key, model = _get_deepseek_settings()
        parts = []
        for f in files:
            try:
                text = f.content.decode("utf-8", errors="replace")
            except Exception:
                text = f.content.decode("latin-1", errors="replace")
            parts.append(f"--- {f.filename} ---\n{text}")

        user_content = "\n\n".join(parts)
        messages = [
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": f"Extract all dishes from this menu:\n\n{user_content}"},
        ]
        raw = await _async_chat(api_key, model, messages, max_tokens=4096)
        # Strip markdown fences
        raw = _re.sub(r"^```(?:json)?|```$", "", raw, flags=_re.MULTILINE).strip()
        try:
            dishes = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"DeepSeek returned non-JSON: {exc}") from exc
        if not isinstance(dishes, list):
            raise RuntimeError("DeepSeek extraction: expected a JSON array")
        return [DishDraft(**d) for d in dishes]


class DeepSeekDescriber:
    def describe(self, name: str, raw_description: str, price_hint: str | None = None) -> str:
        api_key, model = _get_deepseek_settings()
        prompt = DESCRIBE_DISH_TEMPLATE.format(name=name, raw_description=raw_description)
        raw = _sync_chat(api_key, model, [{"role": "user", "content": prompt}], max_tokens=128)
        safe = _re.sub(r"\b(?:AED|aed|\d+\.\d{2})\b", "", raw).strip()
        return "\n".join(safe.splitlines()[:3])


class DeepSeekIntentClassifier:
    _VALID = frozenset({"order_item", "dish_question", "cancel", "modify", "status", "other"})

    def classify(self, text: str) -> str:
        api_key, model = _get_deepseek_settings()
        prompt = INTENT_CLASSIFY_TEMPLATE.format(text=text)
        result = _sync_chat(api_key, model, [{"role": "user", "content": prompt}], max_tokens=16).lower()
        return result if result in self._VALID else "other"


class DeepSeekArbiter:
    async def arbitrate(self, query: str, candidates: list) -> object | None:
        if not candidates:
            return None
        api_key, model = _get_deepseek_settings()
        options = "\n".join(f"{i + 1}. {c.dish_number}. {c.name}" for i, c in enumerate(candidates))
        prompt = ARBITRATE_TEMPLATE.format(
            query=query,
            options=options,
            candidate_count=len(candidates),
        )
        raw = await _async_chat(api_key, model, [{"role": "user", "content": prompt}], max_tokens=8)
        try:
            idx = int(raw.strip()) - 1
            if 0 <= idx < len(candidates):
                return candidates[idx]
        except ValueError:
            pass
        return None


_ALLOWED_HORIZONS = frozenset({"breakfast", "lunch", "dinner", "midnight", "morning", "evening"})


class DeepSeekForecastAdjuster:
    def parse_override(self, text: str) -> dict:
        api_key, model = _get_deepseek_settings()
        prompt = FORECAST_OVERRIDE_TEMPLATE.format(text=text)
        try:
            raw = _sync_chat(api_key, model, [{"role": "user", "content": prompt}], max_tokens=256)
            raw = _re.sub(r"^```(?:json)?|```$", "", raw, flags=_re.MULTILINE).strip()
            parsed = json.loads(raw)
        except Exception:
            return {}
        if not isinstance(parsed, dict):
            return {}
        return _sanitise_effect(parsed)


def _salvage_truncated_tool_args(raw: str) -> dict:
    """Recover a usable dict from a tool-call arguments string that was cut off
    by the token cap (finish_reason="length"). DeepSeek streams JSON key-order-
    stable; the ``reply`` string is what runs long, so a truncated payload still
    carries the leading ``action`` field. We parse as much as we can and default
    the rest — a partial reply beats crashing into a canned error.
    """
    # Fast path: maybe it's actually complete.
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    # Pull the action verb (first string field) so the engine can still act.
    action = None
    m = _re.search(r'"action"\s*:\s*"([^"]*)"', raw)
    if m:
        action = m.group(1)
    # Pull whatever of the reply text survived (may be an unterminated string).
    reply = ""
    m = _re.search(r'"reply"\s*:\s*"(.*)', raw, flags=_re.DOTALL)
    if m:
        # Cut at the last complete char; drop a dangling backslash escape.
        reply = m.group(1).rstrip("\\")
        # If the reply string was closed, stop at its closing quote.
        end = _re.search(r'(?<!\\)"', reply)
        if end:
            reply = reply[: end.start()]
        reply = reply.encode().decode("unicode_escape", errors="ignore")
    out: dict = {}
    if action:
        out["action"] = action
    if reply.strip():
        out["reply"] = reply.strip()
    if out:
        return out
    raise RuntimeError("DeepSeek tool call truncated beyond recovery")


async def _async_chat_tools(
    api_key: str, model: str, system: str, messages: list,
    tools: list, tool_name: str, max_tokens: int = 1024,
) -> dict:
    """OpenAI-compatible tool-calling: returns parsed arguments dict of the forced tool call.

    Resilient by design — this sits on the live customer path and a raw exception
    surfaces as a canned "having a moment" error. Transient HTTP failures get one
    retry; a token-truncated JSON payload is salvaged rather than crashing.
    """
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}] + messages,
        "tools": tools,
        "tool_choice": {"type": "function", "function": {"name": tool_name}},
        "max_tokens": max_tokens,
        "temperature": 0.0,
    }
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(_CHAT, headers=_headers(api_key), json=payload)
                r.raise_for_status()
            break
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            # Retry once on transient network / 5xx / 429; give up on other 4xx.
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if attempt == 0 and (status is None or status == 429 or status >= 500):
                continue
            raise
    else:  # pragma: no cover - loop always breaks or raises
        raise last_exc  # type: ignore[misc]

    data = r.json()
    choice = data["choices"][0]
    tool_calls = choice["message"].get("tool_calls") or []
    for tc in tool_calls:
        if tc.get("function", {}).get("name") == tool_name:
            raw_args = tc["function"]["arguments"]
            try:
                return json.loads(raw_args)
            except json.JSONDecodeError:
                # Truncated at the token cap — salvage the action + partial reply.
                return _salvage_truncated_tool_args(raw_args)
    raise RuntimeError(f"DeepSeek returned no {tool_name!r} tool call")


# Tool definition is derived from the single-source-of-truth schema so providers
# can never drift from the canonical action vocabulary (W1 Task 2).
_DS_TOOL = build_openai_tool("take_action")

# Conversation prompts: src/app/llm/conversation_prompts.py (E-02, E-12, E-23)

class DeepSeekConversationAgent:
    """Phase-aware AI ordering assistant using DeepSeek function calling."""

    def __init__(self, model: str | None = None) -> None:
        api_key, default_model = _get_deepseek_settings()
        self._api_key = api_key
        self._model = _safe_tool_model(model or default_model)

    def _build_system(self, restaurant_name: str, dialogue_phase: str, context: dict) -> str:
        ctx = dict(context)
        ctx.setdefault("max_radius_km", 10)
        identity = build_identity(restaurant_name, ctx)
        phase_block = build_phase_block(dialogue_phase, ctx)
        from app.llm.context_management import format_memory_context

        notes_block = format_memory_context(context.get("session_notes"))
        if notes_block:
            notes_block = f"\n{notes_block}\n"
        extra_blocks: list[str] = []
        prompt_kb = (context.get("prompt_kb") or "").strip()
        if prompt_kb:
            extra_blocks.append(prompt_kb)
        grounding = (context.get("grounding") or "").strip()
        if grounding:
            extra_blocks.append(grounding)
        suffix = ("\n\n" + "\n\n".join(extra_blocks)) if extra_blocks else ""
        return identity + notes_block + phase_block + suffix

    async def respond(
        self,
        *,
        restaurant_name: str,
        dialogue_phase: str,
        history: list[dict],
        context: dict,
    ) -> ConversationAgentResult:
        system = self._build_system(restaurant_name, dialogue_phase, context)
        messages = history if history else [{"role": "user", "content": "hi"}]

        inp = await _async_chat_tools(
            self._api_key,
            self._model,
            system,
            messages,
            tools=[_DS_TOOL],
            tool_name="take_action",
            max_tokens=1024,
        )

        # Translate canonical action + payload to engine-legacy (action, action_data).
        # Required-field validation happens inside to_engine_result: missing fields
        # yield ("no_action", {needs_clarification: True, ...}) so the engine never
        # mutates state from an under-specified tool call.
        legacy_action, action_data = to_engine_result(
            inp.get("action", "no_action"), inp,
        )
        return ConversationAgentResult(
            message=strip_dashes(inp.get("reply", "")),
            action=legacy_action,
            action_data=action_data,
        )


class DeepSeekCompletionDetector:
    """Production completion detector: one tiny async chat call, yes/no answer."""

    def __init__(self, model: str | None = None) -> None:
        self._model_override = model

    async def is_completion(self, text: str) -> bool:
        if not text or not text.strip():
            return False
        api_key, default_model = _get_deepseek_settings()
        model = _safe_tool_model(self._model_override or default_model)
        prompt = COMPLETION_DETECT_TEMPLATE.format(text=text)
        raw = await _async_chat(
            api_key, model,
            [{"role": "user", "content": prompt}],
            max_tokens=4,
        )
        return raw.strip().lower().startswith("y")


class DeepSeekRouterClassifier:
    """Production W4 top-level router: one async chat call, single enum answer.

    LLM-driven and multilingual — no English phrase tables on the live path.
    """

    def __init__(self, model: str | None = None) -> None:
        self._model_override = model

    async def classify_intent(self, text: str, cart_context: str, phase: str):
        from app.llm.port import IntentLabel

        if not text or not text.strip():
            return IntentLabel.NON_ACTIONABLE
        api_key, default_model = _get_deepseek_settings()
        model = _safe_tool_model(self._model_override or default_model)
        labels = ", ".join(label.value for label in IntentLabel)
        prompt = ROUTER_CLASSIFY_TEMPLATE.format(
            phase=phase,
            cart_context=cart_context or "(empty)",
            text=text,
            labels=labels,
        )
        raw = await _async_chat(
            api_key, model,
            [{"role": "user", "content": prompt}],
            max_tokens=8,
        )
        token = raw.strip().lower().split()[0] if raw.strip() else ""
        try:
            return IntentLabel(token)
        except ValueError:
            return IntentLabel.UNKNOWN


def _sanitise_effect(parsed: dict) -> dict:
    effect: dict = {}
    horizon = parsed.get("horizon")
    if isinstance(horizon, str) and horizon.lower() in _ALLOWED_HORIZONS:
        effect["horizon"] = horizon.lower()
    dow = parsed.get("dow")
    if isinstance(dow, int) and 0 <= dow <= 6:
        effect["dow"] = dow
    if isinstance(parsed.get("order_count_delta"), int):
        effect["order_count_delta"] = parsed["order_count_delta"]
    for key in ("order_count_mult", "revenue_mult"):
        val = parsed.get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            effect[key] = float(val)
    dish = parsed.get("dish_demand_delta")
    if isinstance(dish, dict):
        cleaned = {str(k): int(v) for k, v in dish.items() if isinstance(v, int) and not isinstance(v, bool)}
        if cleaned:
            effect["dish_demand_delta"] = cleaned
    return effect


class DeepSeekSegmentCompiler:
    def compile(self, text: str) -> dict:
        from app.marketing.segments import validate_dsl

        api_key, model = _get_deepseek_settings()
        prompt = SEGMENT_COMPILE_TEMPLATE.format(text=text)
        raw = _sync_chat(api_key, model, [{"role": "user", "content": prompt}], max_tokens=512)
        raw = _re.sub(r"^```(?:json)?|```$", "", raw, flags=_re.MULTILINE).strip()
        try:
            dsl = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"DeepSeekSegmentCompiler returned non-JSON: {exc}") from exc
        validate_dsl(dsl)
        return dsl


class DeepSeekKitchenSummarizer:
    """Tier-2 kitchen chat compressor — multilingual, no phrase tables."""

    async def supplement_from_chat(
        self, structured_block: str, inbound_messages: list[str]
    ) -> list[str]:
        from app.llm.kitchen_summary import (
            _TIER2_SYSTEM,
            build_tier2_prompt,
            parse_tier2_response,
        )

        if not inbound_messages:
            return []
        api_key, model = _get_deepseek_settings()
        prompt = build_tier2_prompt(structured_block, inbound_messages)
        raw = await _async_chat(
            api_key,
            model,
            [
                {"role": "system", "content": _TIER2_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=120,
            temperature=0.0,
        )
        return parse_tier2_response(raw)
