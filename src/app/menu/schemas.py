from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class VariantIn(BaseModel):
    """One serving-size option on a dish, e.g. {"name": "4 serve", "price_aed": 60}."""

    name: str
    price_aed: Decimal
    dish_number: int | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("variant name cannot be blank")
        return v

    @field_validator("price_aed")
    @classmethod
    def _price_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("variant price must be greater than 0")
        return v


class VariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    price_aed: Decimal
    dish_number: int | None = None


def _unique_variant_names(variants: list[VariantIn]) -> list[VariantIn]:
    seen: set[str] = set()
    for v in variants:
        key = v.name.casefold()
        if key in seen:
            raise ValueError(f"duplicate variant name: {v.name}")
        seen.add(key)
    return variants


def serialize_variants(variants: list[VariantIn]) -> list[dict]:
    """Canonical JSONB shape for the dishes.variants column (prices as strings)."""
    return [
        {"name": v.name, "price_aed": str(v.price_aed), "dish_number": v.dish_number}
        for v in variants
    ]


class DishOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dish_number: int | None
    name: str
    price_aed: Decimal | None
    category: str | None
    description: str | None
    is_available: bool
    catalog_retailer_id: str | None = None
    variants: list[VariantOut] = []


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
    variants: list[VariantIn] = []

    @model_validator(mode="after")
    def _check_variants(self) -> "DishIn":
        _unique_variant_names(self.variants)
        return self


class DishPatch(BaseModel):
    dish_number: int | None = None
    name: str | None = None
    price_aed: Decimal | None = None
    category: str | None = None
    description: str | None = None
    variants: list[VariantIn] | None = None

    @model_validator(mode="after")
    def _check_variants(self) -> "DishPatch":
        if self.variants is not None:
            _unique_variant_names(self.variants)
        return self


class DiffOut(BaseModel):
    price_changes: list[dict]
    added: list[dict]
    removed: list[dict]
    conflicts: list[dict]


class MenuWithDiffOut(MenuOut):
    diff_vs_active: DiffOut | None = None


class AvailabilityIn(BaseModel):
    is_available: bool
