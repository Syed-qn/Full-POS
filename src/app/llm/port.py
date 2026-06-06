from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel


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
