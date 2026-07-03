"""Primary-then-fallback wrappers for the latency-sensitive live LLM ports.

The primary is tried first with a hard time cap. If it times out (a reasoning
model's think phase can run long) or raises, the same call is re-issued against
the fallback. This gives a latency ceiling on the inbound reply path plus
resilience when the primary is degraded.

Both primary and fallback are DeepSeek instances pointed at DIFFERENT models
(e.g. a slow reasoning model as primary, the previous faster model as fallback).
Claude is NEVER used on the conversation path — only for menu/image extraction.

Wrapping is opt-in via ``APP_DEEPSEEK_FALLBACK_MODEL`` — see ``app.llm.factory``.
Each wrapper is a true drop-in: it mirrors the exact port method signature, so the
engine is unaware a fallback exists.
"""
import asyncio
import logging

log = logging.getLogger(__name__)


async def _primary_then_fallback(label, primary_call, fallback_call, timeout_s):
    """Await ``primary_call()`` under ``timeout_s``; on timeout/error await
    ``fallback_call()``. Both args are zero-arg coroutine factories so the
    fallback coroutine is only created when actually needed."""
    try:
        return await asyncio.wait_for(primary_call(), timeout=timeout_s)
    except asyncio.TimeoutError:
        log.warning(
            "llm-fallback: primary %s exceeded %.1fs — using fallback", label, timeout_s
        )
    except Exception as exc:  # noqa: BLE001 — any primary failure must fall back
        log.warning("llm-fallback: primary %s failed (%s) — using fallback", label, exc)
    return await fallback_call()


class FallbackConversationAgent:
    """ConversationAgentPort: primary DeepSeek model, fallback DeepSeek model."""

    def __init__(self, primary, fallback, timeout_s: float) -> None:
        self._primary = primary
        self._fallback = fallback
        self._timeout = timeout_s

    async def respond(self, **kwargs):
        return await _primary_then_fallback(
            "conversation_agent",
            lambda: self._primary.respond(**kwargs),
            lambda: self._fallback.respond(**kwargs),
            self._timeout,
        )


class FallbackRouterClassifier:
    """RouterClassifierPort: primary DeepSeek model, fallback DeepSeek model."""

    def __init__(self, primary, fallback, timeout_s: float) -> None:
        self._primary = primary
        self._fallback = fallback
        self._timeout = timeout_s

    async def classify_intent(self, text: str, cart_context: str, phase: str):
        return await _primary_then_fallback(
            "router_classifier",
            lambda: self._primary.classify_intent(text, cart_context, phase),
            lambda: self._fallback.classify_intent(text, cart_context, phase),
            self._timeout,
        )


class FallbackCompletionDetector:
    """CompletionDetectorPort: primary DeepSeek model, fallback DeepSeek model."""

    def __init__(self, primary, fallback, timeout_s: float) -> None:
        self._primary = primary
        self._fallback = fallback
        self._timeout = timeout_s

    async def is_completion(self, text: str) -> bool:
        return await _primary_then_fallback(
            "completion_detector",
            lambda: self._primary.is_completion(text),
            lambda: self._fallback.is_completion(text),
            self._timeout,
        )
