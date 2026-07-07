from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ModifierGroupIn(BaseModel):
    name: str
    min_select: int = 0
    max_select: int = 1
    required: bool = False


class ModifierIn(BaseModel):
    name: str
    price_delta_aed: Decimal = Decimal("0.00")


class ModifierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    price_delta_aed: Decimal


class ModifierGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    min_select: int
    max_select: int
    required: bool
