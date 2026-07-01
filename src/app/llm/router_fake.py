"""Deterministic test double for the W4 top-level multilingual router.

The production classifier (Claude / DeepSeek) prompts the model for a single
``IntentLabel`` and is language-agnostic.  This fake mirrors that contract with
transparent, deterministic heuristics so tests never hit the network.

It is intentionally conservative: anything that is not clearly a question,
complaint, closing, greeting, or global navigation intent falls back to
``MUTATION`` / ``UNKNOWN`` so the existing engine flow is preserved unchanged.
The token sets deliberately include a few non-English closings/greetings so the
double exercises the multilingual contract, but the fake is a TEST path only —
the live path stays LLM-driven per the W4 spec.
"""

from app.llm.port import IntentLabel

# Multilingual closing / proceed tokens (mirrors FakeCompletionDetector).
_CHECKOUT_TOKENS = frozenset(
    {
        "done", "that's all", "thats all", "checkout", "proceed", "finish",
        "no more", "nothing else", "that is all", "go ahead", "pay",
        # Arabic / Gulf
        "bas", "khalas", "khalaas", "khallas",
    }
)

# Greeting tokens across a few scripts (Latin + Arabic).
_GREETING_TOKENS = frozenset(
    {
        "hi", "hello", "hey", "hiya", "yo",
        "salam", "salaam", "assalam", "as salam", "asalam",
        "السلام", "مرحبا", "اهلا", "أهلا", "namaste", "hola",
    }
)

_CANCEL_TOKENS = frozenset({"cancel", "cancel order", "cancel my order", "الغاء"})

_MENU_TOKENS = frozenset({"menu", "show menu", "full menu", "قائمة"})

_CATALOGUE_TOKENS = frozenset(
    {"catalog", "catalogue", "catlog", "cataloge", "catalog", "كتالوج"}
)

_SHOW_CART_TOKENS = frozenset(
    {"cart", "my cart", "show cart", "my order", "show my order", "what's in my cart",
     "whats in my cart"}
)

# Explicit fresh-start / empty-cart phrases only — never inferred from "only X".
_CLEAR_TOKENS = frozenset(
    {"clear cart", "clear my cart", "empty cart", "empty my cart", "start over",
     "remove everything", "delete all", "fresh start"}
)

# Question openers across scripts.  A trailing "?" is the strongest signal.
_QUESTION_OPENERS = (
    "what", "how", "where", "why", "who", "when", "which", "do you", "does",
    "can you", "could you", "is there", "are there", "tell me", "show me the",
    # Arabic interrogatives
    "ما", "هل", "كيف", "اين", "أين", "لماذا", "متى",
)

# Complaint / correction-explain — "why did you …", "you added wrong", etc.
_COMPLAINT_MARKERS = (
    "why did you", "why have you", "why is there", "why are there",
    "you added", "you put", "i didn't", "i did not", "wrong", "mistake",
    "لماذا اضفت", "ليش",
)

# Reactions / system noise (emoji-only, single punctuation, ack tokens).
_NON_ACTIONABLE_TOKENS = frozenset({"👍", "❤️", "😊", "🙏", "ok", "okay", "k"})


def _normalise(text: str) -> str:
    return (
        (text or "")
        .replace("’", "'")
        .replace("‘", "'")
        .replace("ʼ", "'")
        .strip()
    )


class FakeRouterClassifier:
    """Rule-based, deterministic ``RouterClassifierPort`` test double."""

    async def classify_intent(
        self, text: str, cart_context: str, phase: str
    ) -> IntentLabel:
        raw = _normalise(text)
        low = raw.lower()

        if not low:
            return IntentLabel.NON_ACTIONABLE

        # Pure emoji / ack noise → non-actionable (never mutates, never errors).
        if raw in _NON_ACTIONABLE_TOKENS or low in _NON_ACTIONABLE_TOKENS:
            return IntentLabel.NON_ACTIONABLE
        if raw and all(not ch.isalnum() for ch in raw):
            return IntentLabel.NON_ACTIONABLE

        # Complaint / correction-explain — highest priority: a message that
        # questions a prior action must never be read as an add/checkout.
        if any(m in low for m in _COMPLAINT_MARKERS):
            return IntentLabel.COMPLAINT

        # Explicit global navigation intents (exact-token or clear phrase).
        if low in _CANCEL_TOKENS or low.startswith("cancel"):
            return IntentLabel.CANCEL
        if any(t in low for t in _CLEAR_TOKENS):
            return IntentLabel.CLEAR
        if low in _CATALOGUE_TOKENS:
            return IntentLabel.CATALOGUE
        if low in _MENU_TOKENS or low == "show me the full menu":
            return IntentLabel.MENU
        if low in _SHOW_CART_TOKENS:
            return IntentLabel.SHOW_CART

        # Greeting (cart-awareness is the router caller's job, not the label's).
        if low in _GREETING_TOKENS or any(
            low == g or low.startswith(g + " ") for g in _GREETING_TOKENS
        ):
            # A greeting mixed with an order ("hi, one biryani") is a mutation.
            _rest = low
            for g in _GREETING_TOKENS:
                if _rest.startswith(g + " "):
                    _rest = _rest[len(g) + 1 :].strip(" ,.!")
                    break
            if _rest and _rest not in _GREETING_TOKENS:
                return IntentLabel.MUTATION
            return IntentLabel.GREETING

        # Questions — trailing "?" or an interrogative opener.
        if raw.endswith("?") or any(
            low == q or low.startswith(q + " ") for q in _QUESTION_OPENERS
        ):
            return IntentLabel.QUESTION

        # Closing / proceed.
        if low in _CHECKOUT_TOKENS or any(
            " " in t and t in low for t in _CHECKOUT_TOKENS
        ):
            return IntentLabel.CHECKOUT

        # Everything else in an ordering context is treated as a mutation attempt;
        # elsewhere it is UNKNOWN.  Both are MUTATING_INTENTS so the existing flow
        # is preserved — the router only *diverts* the clearly non-mutating turns.
        if phase == "ordering":
            return IntentLabel.MUTATION
        return IntentLabel.UNKNOWN
