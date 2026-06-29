from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CouponCreateIn(BaseModel):
    discount_type: str = Field(default="fixed", pattern="^(fixed|percent)$")
    discount_value: Decimal = Field(gt=0)
    kind: str = Field(default="multi_use", pattern="^(single_use|multi_use)$")
    min_order_aed: Decimal = Field(default=Decimal("0.00"), ge=0)
    max_discount_aed: Decimal | None = None
    applies_to: str = Field(default="whole_order", pattern="^(whole_order|delivery_fee|specific_dishes)$")
    per_customer_limit: int | None = Field(default=None, ge=1)
    total_redemption_limit: int | None = Field(default=None, ge=1)
    valid_from: datetime | None = None
    expires_at: datetime | None = None
    code: str | None = None


class CouponIssueIn(BaseModel):
    customer_id: int
    discount_aed: Decimal = Field(gt=0)
    validity_days: int = Field(default=30, ge=1)


class CouponOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    kind: str
    discount_type: str
    discount_aed: Decimal | None
    percent: Decimal | None
    max_discount_aed: Decimal | None
    min_order_aed: Decimal
    applies_to: str
    per_customer_limit: int | None
    total_redemption_limit: int | None
    status: str
    valid_from: datetime | None
    expires_at: datetime | None
    created_at: datetime
