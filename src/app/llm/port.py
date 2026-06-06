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
