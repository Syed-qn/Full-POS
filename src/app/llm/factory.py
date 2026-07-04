from functools import lru_cache

from app.config import get_settings
from app.llm.fake import FakeExtractor
from app.llm.port import MenuExtractor


def _deepseek_fallback_model(settings) -> str | None:
    """The previous/faster same-provider model to fall back to on the live path.

    Same provider (Claude is never used for conversation). Only active when a
    fallback model is configured and it differs from the primary model. Resolves
    Kimi's fallback model when APP_LLM_PROVIDER=kimi (the DeepSeek* classes serve
    both OpenAI-compatible providers).
    """
    if settings.llm_provider == "kimi":
        fb = (settings.kimi_fallback_model or "").strip()
        return fb if fb and fb != settings.kimi_model else None
    fb = (settings.deepseek_fallback_model or "").strip()
    if fb and fb != settings.deepseek_model:
        return fb
    return None


@lru_cache
def get_menu_extractor() -> MenuExtractor:
    settings = get_settings()
    provider = settings.menu_extractor_provider or "auto"
    if provider == "auto":
        # Menus arrive as PDFs/images. Only a multimodal model (Claude) can read
        # those natively — DeepSeek's chat API can't ingest binaries, so a PDF
        # gets decoded as garbage and dishes are lost. Prefer Claude whenever an
        # Anthropic key is configured; otherwise fall back to the chat provider.
        if settings.anthropic_api_key.get_secret_value():
            provider = "claude"
        else:
            provider = settings.llm_provider
    if provider == "claude":
        from app.llm.claude import ClaudeExtractor
        return ClaudeExtractor()
    if provider in ("deepseek", "kimi"):
        from app.llm.deepseek import DeepSeekExtractor
        return DeepSeekExtractor()
    if provider == "fake":
        return FakeExtractor()
    raise ValueError(f"Unknown menu extractor provider: {provider!r}")


@lru_cache
def _get_anthropic_client():
    """Cached synchronous Anthropic client for describe/classify/arbitrate ports."""
    from anthropic import Anthropic

    settings = get_settings()
    return Anthropic(api_key=settings.anthropic_api_key.get_secret_value())


def get_describer():
    settings = get_settings()
    if settings.llm_provider == "claude":
        from app.llm.claude import ClaudeDescriber
        return ClaudeDescriber()
    if settings.llm_provider in ("deepseek", "kimi"):
        from app.llm.deepseek import DeepSeekDescriber
        return DeepSeekDescriber()
    from app.llm.fake import FakeDescriber
    return FakeDescriber()


def get_intent_classifier():
    settings = get_settings()
    if settings.llm_provider == "claude":
        from app.llm.claude import ClaudeIntentClassifier
        return ClaudeIntentClassifier()
    if settings.llm_provider in ("deepseek", "kimi"):
        from app.llm.deepseek import DeepSeekIntentClassifier
        return DeepSeekIntentClassifier()
    from app.llm.fake import FakeIntentClassifier
    return FakeIntentClassifier()


def get_arbiter():
    settings = get_settings()
    if settings.llm_provider == "claude":
        from app.llm.claude import ClaudeArbiter
        return ClaudeArbiter()
    if settings.llm_provider in ("deepseek", "kimi"):
        from app.llm.deepseek import DeepSeekArbiter
        return DeepSeekArbiter()
    from app.llm.fake import FakeArbiter
    return FakeArbiter()


def get_forecast_adjuster():
    settings = get_settings()
    if settings.llm_provider == "claude":
        from app.llm.claude import ClaudeForecastAdjuster
        return ClaudeForecastAdjuster()
    if settings.llm_provider in ("deepseek", "kimi"):
        from app.llm.deepseek import DeepSeekForecastAdjuster
        return DeepSeekForecastAdjuster()
    from app.llm.fake import FakeForecastAdjuster
    return FakeForecastAdjuster()


def get_conversation_agent():
    settings = get_settings()
    if settings.llm_provider == "claude":
        if not getattr(settings, "claude_conversation_enabled", False):
            # Claude is parity-gated (W1). Until explicitly enabled, fall back to the
            # contract-tested DeepSeek agent rather than a divergent action surface.
            from app.llm.deepseek import DeepSeekConversationAgent
            return DeepSeekConversationAgent()
        from app.llm.claude import ClaudeConversationAgent
        return ClaudeConversationAgent()
    if settings.llm_provider in ("deepseek", "kimi"):
        from app.llm.deepseek import DeepSeekConversationAgent
        fb = _deepseek_fallback_model(settings)
        if fb:
            from app.llm.fallback import FallbackConversationAgent
            return FallbackConversationAgent(
                DeepSeekConversationAgent(),
                DeepSeekConversationAgent(model=fb),
                settings.llm_primary_timeout_s,
            )
        return DeepSeekConversationAgent()
    from app.llm.fake import FakeConversationAgent
    return FakeConversationAgent()


def get_router_classifier():
    """W4 top-level multilingual intent router (LLM-driven; Fake for tests)."""
    settings = get_settings()
    if settings.llm_provider == "claude":
        from app.llm.claude import ClaudeRouterClassifier
        return ClaudeRouterClassifier()
    if settings.llm_provider in ("deepseek", "kimi"):
        from app.llm.deepseek import DeepSeekRouterClassifier
        fb = _deepseek_fallback_model(settings)
        if fb:
            from app.llm.fallback import FallbackRouterClassifier
            return FallbackRouterClassifier(
                DeepSeekRouterClassifier(),
                DeepSeekRouterClassifier(model=fb),
                settings.llm_primary_timeout_s,
            )
        return DeepSeekRouterClassifier()
    from app.llm.router_fake import FakeRouterClassifier
    return FakeRouterClassifier()


def get_completion_detector():
    settings = get_settings()
    if settings.llm_provider == "claude":
        from app.llm.claude import ClaudeCompletionDetector
        return ClaudeCompletionDetector()
    if settings.llm_provider in ("deepseek", "kimi"):
        from app.llm.deepseek import DeepSeekCompletionDetector
        fb = _deepseek_fallback_model(settings)
        if fb:
            from app.llm.fallback import FallbackCompletionDetector
            return FallbackCompletionDetector(
                DeepSeekCompletionDetector(),
                DeepSeekCompletionDetector(model=fb),
                settings.llm_primary_timeout_s,
            )
        return DeepSeekCompletionDetector()
    from app.llm.fake import FakeCompletionDetector
    return FakeCompletionDetector()


def get_segment_compiler():
    settings = get_settings()
    if settings.llm_provider == "claude":
        from app.llm.claude import ClaudeSegmentCompiler
        return ClaudeSegmentCompiler()
    if settings.llm_provider in ("deepseek", "kimi"):
        from app.llm.deepseek import DeepSeekSegmentCompiler
        return DeepSeekSegmentCompiler()
    from app.llm.fake import FakeSegmentCompiler
    return FakeSegmentCompiler()


def get_kitchen_summarizer():
    """Tier-2 kitchen chat compressor (LLM-driven; Fake returns [] in tests)."""
    settings = get_settings()
    if settings.llm_provider == "claude":
        from app.llm.claude import ClaudeKitchenSummarizer
        return ClaudeKitchenSummarizer()
    if settings.llm_provider in ("deepseek", "kimi"):
        from app.llm.deepseek import DeepSeekKitchenSummarizer
        return DeepSeekKitchenSummarizer()
    from app.llm.fake import FakeKitchenSummarizer
    return FakeKitchenSummarizer()


def get_complaint_summarizer():
    """E-10 complaint sub-agent (LLM-driven; Fake for tests)."""
    settings = get_settings()
    if settings.llm_provider == "claude":
        from app.llm.complaint_agent import ClaudeComplaintSummarizer
        return ClaudeComplaintSummarizer()
    if settings.llm_provider in ("deepseek", "kimi"):
        from app.llm.complaint_agent import DeepSeekComplaintSummarizer
        return DeepSeekComplaintSummarizer()
    from app.llm.fake import FakeComplaintSummarizer
    return FakeComplaintSummarizer()


def get_modify_summarizer():
    """E-10 modify sub-agent (LLM-driven; Fake for tests)."""
    settings = get_settings()
    if settings.llm_provider == "claude":
        from app.llm.modify_agent import ClaudeModifySummarizer
        return ClaudeModifySummarizer()
    if settings.llm_provider in ("deepseek", "kimi"):
        from app.llm.modify_agent import DeepSeekModifySummarizer
        return DeepSeekModifySummarizer()
    from app.llm.fake import FakeModifySummarizer
    return FakeModifySummarizer()


def get_suggestion_agent():
    """Dish suggestion sub-agent (LLM-driven; Fake returns first 2 candidates in tests)."""
    settings = get_settings()
    if settings.llm_provider == "claude":
        from app.llm.suggestion_agent import ClaudeSuggestionAgent
        return ClaudeSuggestionAgent()
    if settings.llm_provider in ("deepseek", "kimi"):
        from app.llm.suggestion_agent import DeepSeekSuggestionAgent
        return DeepSeekSuggestionAgent()
    from app.llm.fake import FakeSuggestionAgent
    return FakeSuggestionAgent()


def get_thought_evaluator():
    """E-17 ToT-lite evaluator (deterministic-first; Fake for tests)."""
    settings = get_settings()
    if settings.llm_provider == "claude":
        from app.llm.thought_evaluator import ClaudeThoughtEvaluator
        return ClaudeThoughtEvaluator()
    if settings.llm_provider in ("deepseek", "kimi"):
        from app.llm.thought_evaluator import DeepSeekThoughtEvaluator
        return DeepSeekThoughtEvaluator()
    from app.llm.fake import FakeThoughtEvaluator
    return FakeThoughtEvaluator()
