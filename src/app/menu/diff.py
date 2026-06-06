from dataclasses import dataclass, field
from decimal import Decimal

from app.llm.port import DishDraft
from app.menu.models import Dish


def _norm(name: str) -> str:
    return " ".join(name.lower().split())


@dataclass
class DiffReport:
    price_changes: list[dict] = field(default_factory=list)
    added: list[DishDraft] = field(default_factory=list)
    removed: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)


def diff_menus(old_dishes: list[Dish], new_drafts: list[DishDraft]) -> DiffReport:
    report = DiffReport()
    old_by_number = {d.dish_number: d for d in old_dishes}
    matched_numbers: set[int | None] = set()

    for draft in new_drafts:
        old = old_by_number.get(draft.dish_number)
        if old is None:
            report.added.append(draft)
            continue
        matched_numbers.add(old.dish_number)
        if _norm(old.name) != _norm(draft.name):
            report.conflicts.append({
                "dish_number": old.dish_number,
                "old_name": old.name,
                "new_name": draft.name,
            })
        elif (
            draft.price_aed is not None
            and Decimal(old.price_aed) != Decimal(draft.price_aed)
        ):
            report.price_changes.append({
                "dish_number": old.dish_number,
                "name": old.name,
                "old_price": Decimal(old.price_aed),
                "new_price": Decimal(draft.price_aed),
            })

    for d in old_dishes:
        if d.dish_number not in matched_numbers:
            report.removed.append({"dish_number": d.dish_number, "name": d.name})
    return report
