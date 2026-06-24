import re
from dataclasses import dataclass
from decimal import Decimal
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
