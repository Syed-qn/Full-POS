from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class DishOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dish_number: int | None
    name: str
    price_aed: Decimal | None
    category: str | None
    description: str | None
    is_available: bool


class MenuOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version: int
    status: str
    dishes: list[DishOut]


class DishIn(BaseModel):
    dish_number: int
    name: str
    price_aed: Decimal
    category: str | None = None
    description: str | None = None


class DishPatch(BaseModel):
    dish_number: int | None = None
    name: str | None = None
    price_aed: Decimal | None = None
    category: str | None = None
    description: str | None = None


class DiffOut(BaseModel):
    price_changes: list[dict]
    added: list[dict]
    removed: list[dict]
    conflicts: list[dict]


class MenuWithDiffOut(MenuOut):
    diff_vs_active: DiffOut | None = None
