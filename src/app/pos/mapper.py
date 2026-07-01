"""Map a normalized :class:`PosMenu` into upsertable dish records.

Pure functions (no I/O) so the mapping is trivially testable. Currency is hard-coded to
AED for now. Only real sellable items (``productType == 1``) become dishes; modifiers and
combos (types 2/3) are ignored in this phase.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.pos.port import PosMenu

# Hard-coded currency for now (POS endpoint doesn't return one).
CURRENCY = "AED"


def _clean_name(raw: str) -> str:
    """Tidy a POS name for customers: drop the leading "-" artifact and title-case the
    ALL-CAPS exports (e.g. "-SAMOSA CHEESE" -> "Samosa Cheese")."""
    n = (raw or "").strip().lstrip("-").strip()
    if n and n == n.upper():
        n = n.title()
    return n or "Item"


@dataclass(frozen=True)
class PosDishRecord:
    pos_product_id: str
    name: str
    price_aed: Decimal
    category: str | None
    description: str | None


def map_pos_menu(menu: PosMenu) -> list[PosDishRecord]:
    """Sellable POS products → dish records, with category names resolved."""
    records: list[PosDishRecord] = []
    seen: set[str] = set()
    for p in menu.products:
        if p.product_type != 1:
            continue  # modifiers / combos are not standalone dishes (this phase)
        if not p.name or p.price is None or p.price <= 0:
            continue
        if p.pos_product_id in seen:
            continue
        seen.add(p.pos_product_id)
        records.append(
            PosDishRecord(
                pos_product_id=p.pos_product_id,
                name=_clean_name(p.name),
                price_aed=p.price,
                category=menu.category_name(p.category_id),
                description=_clean_name(p.description) if p.description else None,
            )
        )
    return records
