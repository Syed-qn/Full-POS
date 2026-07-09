from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class OrgSignupIn(BaseModel):
    name: str
    owner_email: str
    password: str


class OrgLoginIn(BaseModel):
    owner_email: str
    password: str


class BranchIn(BaseModel):
    name: str
    lat: float
    lng: float
    region: str | None = None
    currency: str = "AED"
    locale: str = "en"
    is_central_kitchen: bool = False


class BranchPatchIn(BaseModel):
    name: str | None = None
    region: str | None = None
    currency: str | None = None
    locale: str | None = None
    is_central_kitchen: bool | None = None


class OrgSettingsIn(BaseModel):
    royalty_pct: Decimal | None = None
    default_currency: str | None = None
    default_locale: str | None = None
    settings: dict[str, Any] | None = None


class StockTransferLineIn(BaseModel):
    ingredient_name: str
    unit: str
    quantity: Decimal


class StockTransferIn(BaseModel):
    from_restaurant_id: int
    to_restaurant_id: int
    lines: list[StockTransferLineIn]


class OrgMenuItemIn(BaseModel):
    name: str
    base_price_aed: Decimal
    category: str | None = None
    description: str | None = None
    name_ar: str | None = None
    dish_number: int | None = None


class BranchPriceIn(BaseModel):
    org_menu_item_id: int
    restaurant_id: int
    price_aed: Decimal


class MenuPublishIn(BaseModel):
    target_restaurant_ids: list[int] = Field(default_factory=list)
    org_menu_item_ids: list[int] = Field(default_factory=list)
    notes: str | None = None


class MenuPublishDecisionIn(BaseModel):
    approve: bool = True
    approved_by: str = "hq"


class BulkUpdateIn(BaseModel):
    restaurant_ids: list[int]
    action: str  # set_available | set_price_delta | set_region | set_currency | set_locale
    payload: dict[str, Any] = Field(default_factory=dict)


class OrgCustomerIn(BaseModel):
    phone: str
    name: str | None = None
    preferred_locale: str | None = None


class LoyaltyCreditIn(BaseModel):
    phone: str
    points: int = 0
    spend_aed: Decimal = Decimal("0")


class OrgPromotionIn(BaseModel):
    code: str
    title: str
    discount_aed: Decimal = Decimal("0")
    discount_pct: Decimal | None = None
    target_restaurant_ids: list[int] = Field(default_factory=list)


class OrgMemberIn(BaseModel):
    email: str
    name: str
    role: str = "branch_manager"
    branch_ids: list[int] = Field(default_factory=list)
    pin: str | None = None


class CentralKitchenRequestIn(BaseModel):
    from_restaurant_id: int
    items: list[dict[str, Any]]
    notes: str | None = None
    central_kitchen_id: int | None = None


class CentralKitchenStatusIn(BaseModel):
    status: str
