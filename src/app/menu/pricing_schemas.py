from datetime import time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

_VALID_RULE_TYPES = {"time", "channel", "branch"}


class PriceRuleIn(BaseModel):
    rule_type: str
    price_aed: Decimal
    start_time: time | None = None
    end_time: time | None = None
    days_of_week: list[int] | None = None
    channel: str | None = None
    branch_id: int | None = None

    @field_validator("rule_type")
    @classmethod
    def _check_rule_type(cls, v: str) -> str:
        if v not in _VALID_RULE_TYPES:
            raise ValueError(f"rule_type must be one of {sorted(_VALID_RULE_TYPES)}")
        return v


class PriceRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dish_id: int
    rule_type: str
    price_aed: Decimal
    start_time: time | None = None
    end_time: time | None = None
    days_of_week: list[int] | None = None
    channel: str | None = None
    branch_id: int | None = None


class EffectivePriceOut(BaseModel):
    dish_id: int
    price_aed: Decimal
    channel: str | None = None
    branch_id: int | None = None
