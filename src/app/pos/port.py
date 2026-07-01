"""POS provider port + normalized domain types + a Fake for tests.

External POS systems live behind this port exactly like ``llm/port.py`` and the
WhatsApp/geo adapters: prod uses ``CratisPosAdapter``, tests/dev use ``FakePos`` (chosen
by ``APP_POS_PROVIDER``). The sync service depends only on this interface, so it never
touches the network in tests.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class PosCategory:
    pos_category_id: str
    name: str


@dataclass(frozen=True)
class PosProduct:
    pos_product_id: str
    name: str
    price: Decimal
    category_id: str | None = None
    description: str | None = None
    name_ar: str | None = None
    plu: str | None = None
    # POS productType: 1 = sellable item, 2 = modifier/sub, 3 = combo (provider-specific).
    product_type: int = 1


@dataclass(frozen=True)
class PosMenu:
    products: list[PosProduct] = field(default_factory=list)
    categories: list[PosCategory] = field(default_factory=list)

    def category_name(self, category_id: str | None) -> str | None:
        if not category_id:
            return None
        for c in self.categories:
            if c.pos_category_id == category_id and (c.name or "").strip():
                return c.name
        return None


class PosProvider(ABC):
    """Read a restaurant's live menu from its POS."""

    @abstractmethod
    async def fetch_menu(
        self, *, account: str, location: str, base_url: str | None = None
    ) -> PosMenu:  # pragma: no cover - interface
        ...


class FakePos(PosProvider):
    """Deterministic in-memory POS for tests/dev. Override the menu per test as needed."""

    def __init__(self, menu: PosMenu | None = None) -> None:
        self._menu = menu or PosMenu(
            categories=[
                PosCategory(pos_category_id="220", name="APPETIZER"),
                PosCategory(pos_category_id="227", name="COLD BEVERAGES"),
            ],
            products=[
                PosProduct(
                    pos_product_id="19680", name="Samosa Cheese", price=Decimal("12.00"),
                    category_id="220", description="Crispy cheese samosa", plu="EXAP001",
                    product_type=1,
                ),
                PosProduct(
                    pos_product_id="19697", name="Fruit Juice Apple", price=Decimal("9.00"),
                    category_id="227", plu="EXCB001", product_type=1,
                ),
                # productType 2 (modifier) — must be filtered OUT of the dish list.
                PosProduct(
                    pos_product_id="50001", name="Extra Cheese", price=Decimal("2.00"),
                    category_id="220", product_type=2,
                ),
            ],
        )

    async def fetch_menu(
        self, *, account: str, location: str, base_url: str | None = None
    ) -> PosMenu:
        return self._menu
