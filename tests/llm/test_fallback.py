"""Unit tests for the primary-then-fallback live-path wrappers."""
import asyncio

from app.llm.fallback import (
    FallbackCompletionDetector,
    FallbackConversationAgent,
    FallbackRouterClassifier,
)


class _StubAgent:
    """Records whether it was called; can be made to hang, raise, or return."""

    def __init__(self, *, result=None, raises=None, hang=False):
        self._result = result
        self._raises = raises
        self._hang = hang
        self.called = False

    async def respond(self, **kwargs):
        self.called = True
        if self._hang:
            await asyncio.sleep(10)
        if self._raises:
            raise self._raises
        return self._result

    async def classify_intent(self, text, cart_context, phase):
        self.called = True
        if self._hang:
            await asyncio.sleep(10)
        if self._raises:
            raise self._raises
        return self._result

    async def is_completion(self, text):
        self.called = True
        if self._hang:
            await asyncio.sleep(10)
        if self._raises:
            raise self._raises
        return self._result


async def test_conversation_uses_primary_when_it_succeeds():
    primary = _StubAgent(result="primary-reply")
    fallback = _StubAgent(result="fallback-reply")
    agent = FallbackConversationAgent(primary, fallback, timeout_s=5)

    out = await agent.respond(
        restaurant_name="r", dialogue_phase="p", history=[], context={}
    )

    assert out == "primary-reply"
    assert primary.called and not fallback.called


async def test_conversation_falls_back_on_error():
    primary = _StubAgent(raises=RuntimeError("deepseek down"))
    fallback = _StubAgent(result="fallback-reply")
    agent = FallbackConversationAgent(primary, fallback, timeout_s=5)

    out = await agent.respond(
        restaurant_name="r", dialogue_phase="p", history=[], context={}
    )

    assert out == "fallback-reply"
    assert primary.called and fallback.called


async def test_conversation_falls_back_on_timeout():
    primary = _StubAgent(hang=True)
    fallback = _StubAgent(result="fallback-reply")
    agent = FallbackConversationAgent(primary, fallback, timeout_s=0.05)

    out = await agent.respond(
        restaurant_name="r", dialogue_phase="p", history=[], context={}
    )

    assert out == "fallback-reply"
    assert fallback.called


async def test_router_falls_back_on_error():
    primary = _StubAgent(raises=ValueError("boom"))
    fallback = _StubAgent(result="ORDER_ITEM")
    clf = FallbackRouterClassifier(primary, fallback, timeout_s=5)

    out = await clf.classify_intent("2 pizzas", "(empty)", "greeting")

    assert out == "ORDER_ITEM"
    assert fallback.called


async def test_completion_uses_primary_when_it_succeeds():
    primary = _StubAgent(result=True)
    fallback = _StubAgent(result=False)
    det = FallbackCompletionDetector(primary, fallback, timeout_s=5)

    out = await det.is_completion("thanks, that's all")

    assert out is True
    assert primary.called and not fallback.called
