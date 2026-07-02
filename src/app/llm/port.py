import re
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Protocol

from pydantic import BaseModel

# Em/en dashes used as clause separators (with optional surrounding spaces). We
# strip these from customer-facing AI replies because the LLM tends to lean on
# "—" as a separator. A hyphen between letters (compound words like "long-grain")
# is intentionally left alone — only standalone dashes are rewritten.
_SEP_DASH_RE = re.compile(r"\s*[—–]\s*|\s+-\s+")


def strip_dashes(text: str) -> str:
    """Rewrite em/en/standalone-hyphen separators in an AI reply as commas.

    Compound-word hyphens ("long-grain", "extra-tender") have no surrounding
    spaces, so they are preserved. Collapses any resulting ", ," duplication.
    """
    if not text:
        return text
    out = _SEP_DASH_RE.sub(", ", text)
    return re.sub(r",\s*,", ",", out)


@dataclass
class UploadedFile:
    filename: str
    content: bytes
    mime: str


class DishDraft(BaseModel):
    dish_number: int | None = None
    name: str
    price_aed: Decimal | None = None
    category: str | None = None
    description: str | None = None


class MenuExtractor(Protocol):
    async def extract_menu(self, files: list[UploadedFile]) -> list[DishDraft]: ...


class DescriberPort(Protocol):
    def describe(self, name: str, raw_description: str, price_hint: str | None = None) -> str:
        """Return ≤3-line customer-facing description. NEVER include price."""
        ...


class IntentClassifierPort(Protocol):
    def classify(self, text: str) -> str:
        """Return one of: order_item | dish_question | cancel | modify | status | other."""
        ...


class IntentLabel(str, Enum):
    """Top-level multilingual router intent (W4).

    A single, phase-aware, language-agnostic classification of the customer's
    latest message.  It decides — BEFORE any cart mutation — whether the turn is
    an actual mutation, a question that must be answered (never mutating), a
    complaint/correction-explain, a global navigation intent, or noise.
    """

    MUTATION = "mutation"            # add / remove / set-qty / note — changes the cart
    QUESTION = "question"           # asks something; answer + re-show cart, never mutate
    COMPLAINT = "complaint"         # "why did you add 2" — explain, never mutate
    MENU = "menu"                   # wants the menu / catalogue text
    CATALOGUE = "catalogue"         # wants the interactive catalogue cards
    CHECKOUT = "checkout"           # "done" / "that's all" / proceed to pay
    ADDRESS = "address"             # gives / asks about delivery address
    CANCEL = "cancel"               # cancel the order
    CLEAR = "clear"                 # explicit empty-cart / fresh start
    SHOW_CART = "show_cart"         # "what's in my cart"
    GREETING = "greeting"           # hi / hello / salam (cart-aware)
    NON_ACTIONABLE = "non_actionable"  # reaction / system event / emoji — ignore or ack
    UNKNOWN = "unknown"             # cannot classify — fall through to existing flow


# Intents the router treats as safe to reach a cart mutation.  Anything NOT in
# this set (question/complaint/checkout/…) must never drive a silent cart change.
MUTATING_INTENTS = frozenset({IntentLabel.MUTATION, IntentLabel.UNKNOWN})

# Intents that answer/explain and must NEVER mutate the cart.
NON_MUTATING_INTENTS = frozenset(
    {IntentLabel.QUESTION, IntentLabel.COMPLAINT, IntentLabel.NON_ACTIONABLE}
)


class RouterClassifierPort(Protocol):
    """Top-level multilingual intent router (W4).

    LLM-driven and language-agnostic: the production implementation prompts the
    model for a single enum label and NEVER relies on English phrase tables on
    the live path.  ``cart_context`` (a rendered cart summary) and ``phase``
    (ordering | address_capture | awaiting_confirmation | post_order) let the
    classifier disambiguate — e.g. a bare dish name during ``awaiting_confirmation``
    is still a mutation, while "why did you add 2" is always a complaint.
    """

    async def classify_intent(
        self, text: str, cart_context: str, phase: str
    ) -> IntentLabel: ...


class CompletionDetectorPort(Protocol):
    async def is_completion(self, text: str) -> bool:
        """True if the message means the customer is finished / wants to proceed,
        in ANY language. NOT a completion if they name a dish or ask a question."""
        ...


class KitchenSummarizerPort(Protocol):
    """Tier-2 kitchen digest: LLM compresses inbound chat into net-new lines only.

    Tier 1 (structured cart/notes) is rendered in code — this port NEVER rewrites
    the authoritative block.  Language-agnostic; no phrase tables on the live path.
    """

    async def supplement_from_chat(
        self, structured_block: str, inbound_messages: list[str]
    ) -> list[str]:
        """Return 0–2 additional kitchen/delivery lines not in ``structured_block``."""
        ...


class ComplaintSummarizerPort(Protocol):
    """E-10 sub-agent: distill post-delivery complaint chat for staff handoff.

    Returns ``{"issue": str, "suggested_action": str}`` — never compensates.
    """

    async def summarize(self, order_context: str, chat_snippet: str) -> dict: ...


class ModifySummarizerPort(Protocol):
    """E-10 sub-agent: distill order modification proposal for staff handoff.

    Returns ``{"summary": str, "change_count": int, "suggested_action": str}``.
    """

    async def summarize(
        self, order_context: str, proposed_text: str, chat_snippet: str = "",
    ) -> dict: ...


class ThoughtEvaluatorPort(Protocol):
    """E-17 ToT-lite: resolve ambiguous router UNKNOWN turns."""

    async def evaluate(
        self, text: str, phase: str, *, cart_nonempty: bool,
    ) -> str | None: ...


class ArbiterPort(Protocol):
    async def arbitrate(self, query: str, candidates: list) -> object | None:
        """Given ambiguous matches, return the single best Dish or None."""
        ...


class ForecastAdjusterPort(Protocol):
    def parse_override(self, text: str) -> dict:
        """Plain-English manager override -> parsed_effect DSL dict (see adjust.py shape)."""
        ...


class SegmentCompilerPort(Protocol):
    def compile(self, text: str) -> dict:
        """Translate plain-English audience description into a validated segment DSL.

        The returned dict MUST pass ``app.marketing.segments.validate_dsl`` — the
        caller validates and rejects anything unsafe (never executes raw input).
        """
        ...


@dataclass
class ConversationAgentResult:
    """Result from the AI conversation agent."""
    message: str
    action: str
    # Ordering actions: add_item | remove_item | update_qty | proceed_to_address
    # Address actions:  send_location_request | save_address_text | use_saved_address | proceed_to_confirmation
    # Confirmation:     confirm_order | request_modification | cancel_order
    # Post-order:       status_query
    # Any phase:        no_action | cancel_order
    action_data: dict  # keys vary by action — see design spec


class ConversationAgentPort(Protocol):
    async def respond(
        self,
        *,
        restaurant_name: str,
        dialogue_phase: str,   # ordering | address_capture | awaiting_confirmation | post_order
        history: list[dict],   # [{"role": "user"|"assistant", "content": str}, ...]
        context: dict,         # phase-specific data dict
    ) -> ConversationAgentResult: ...
