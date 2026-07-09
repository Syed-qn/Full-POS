from datetime import date, datetime
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
    # Set when the dish is owned by a POS sync (Cratis). The manager UI uses this to lock
    # editing — POS is the source of truth for name/price/category, so an edit here would
    # silently drift from (and be overwritten by) the next sync.
    pos_product_id: str | None = None
    # Meta Commerce catalogue product fields (see Dish model).
    image_url: str | None = None
    sale_price_aed: Decimal | None = None
    fb_product_category: str | None = None
    condition: str = "new"
    meta_status: str = "active"
    brand: str | None = None
    whatsapp_enabled: bool = True
    variants: list[VariantOut] = []
    updated_at: datetime
    # Cat-3 menu control
    allergens: list = []
    name_ar: str | None = None
    description_ar: str | None = None
    nutrition: dict = {}
    channels_allowed: list = []
    brand_menu_code: str | None = None
    stock_remaining: int | None = None
    auto_hide_when_oos: bool = False
    available_from: date | None = None
    available_until: date | None = None
    category_id: int | None = None


class MenuOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version: int
    status: str
    dishes: list[DishOut]


_CONDITIONS = {"new", "refurbished", "used"}
_META_STATUSES = {"active", "archived"}


def _validate_condition(v: str | None) -> str | None:
    if v is None:
        return v
    v = v.strip().lower()
    if v not in _CONDITIONS:
        raise ValueError(f"condition must be one of {sorted(_CONDITIONS)}")
    return v


def _validate_meta_status(v: str | None) -> str | None:
    if v is None:
        return v
    v = v.strip().lower()
    if v not in _META_STATUSES:
        raise ValueError(f"meta_status must be one of {sorted(_META_STATUSES)}")
    return v


class DishIn(BaseModel):
    dish_number: int
    name: str
    price_aed: Decimal
    category: str | None = None
    description: str | None = None
    # Meta Commerce catalogue product fields (all optional; sensible defaults).
    image_url: str | None = None
    sale_price_aed: Decimal | None = None
    fb_product_category: str | None = None
    condition: str = "new"
    meta_status: str = "active"
    brand: str | None = None
    whatsapp_enabled: bool = True
    # Content ID override; blank/None → auto-generated on push.
    catalog_retailer_id: str | None = None
    variants: list[VariantIn] = []
    allergens: list[str] = []
    name_ar: str | None = None
    description_ar: str | None = None
    nutrition: dict | None = None
    channels_allowed: list[str] = []
    brand_menu_code: str | None = None
    stock_remaining: int | None = None
    auto_hide_when_oos: bool = False
    available_from: date | None = None
    available_until: date | None = None
    category_id: int | None = None

    @field_validator("condition")
    @classmethod
    def _check_condition(cls, v: str) -> str:
        return _validate_condition(v) or "new"

    @field_validator("meta_status")
    @classmethod
    def _check_status(cls, v: str) -> str:
        return _validate_meta_status(v) or "active"

    @field_validator("sale_price_aed")
    @classmethod
    def _sale_price_positive(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v <= 0:
            raise ValueError("sale price must be greater than 0")
        return v

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
    image_url: str | None = None
    sale_price_aed: Decimal | None = None
    fb_product_category: str | None = None
    condition: str | None = None
    meta_status: str | None = None
    brand: str | None = None
    whatsapp_enabled: bool | None = None
    catalog_retailer_id: str | None = None
    variants: list[VariantIn] | None = None
    allergens: list[str] | None = None
    name_ar: str | None = None
    description_ar: str | None = None
    nutrition: dict | None = None
    channels_allowed: list[str] | None = None
    brand_menu_code: str | None = None
    stock_remaining: int | None = None
    auto_hide_when_oos: bool | None = None
    available_from: date | None = None
    available_until: date | None = None
    category_id: int | None = None

    @field_validator("condition")
    @classmethod
    def _check_condition(cls, v: str | None) -> str | None:
        return _validate_condition(v)

    @field_validator("meta_status")
    @classmethod
    def _check_status(cls, v: str | None) -> str | None:
        return _validate_meta_status(v)

    @field_validator("sale_price_aed")
    @classmethod
    def _sale_price_positive(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v <= 0:
            raise ValueError("sale price must be greater than 0")
        return v

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


class BulkPriceUpdateIn(BaseModel):
    """Bulk price update: either absolute price or percent delta."""

    dish_ids: list[int]
    price_aed: Decimal | None = None
    percent_delta: Decimal | None = None  # e.g. 10 = +10%, -5 = -5%


class BulkPriceUpdateOut(BaseModel):
    updated: int
    dish_ids: list[int]


class BulkCsvImportOut(BaseModel):
    created: int
    updated: int
    errors: list[str]


class SellRuleIn(BaseModel):
    rule_kind: str  # upsell | cross_sell
    suggest_dish_id: int
    trigger_dish_id: int | None = None
    trigger_category: str | None = None
    message: str | None = None
    sort_order: int = 0
    is_active: bool = True


class SellRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rule_kind: str
    trigger_dish_id: int | None
    trigger_category: str | None
    suggest_dish_id: int
    message: str | None
    sort_order: int
    is_active: bool


class MenuWithDiffOut(MenuOut):
    diff_vs_active: DiffOut | None = None


class AvailabilityIn(BaseModel):
    is_available: bool


class WhatsappToggleIn(BaseModel):
    """Manager turning a dish's WhatsApp catalogue presence on/off."""

    enabled: bool
