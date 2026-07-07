from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class IngredientIn(BaseModel):
    name: str
    unit: str
    current_stock: Decimal = Decimal("0.000")
    low_stock_threshold: Decimal = Decimal("0.000")


class IngredientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    unit: str
    current_stock: Decimal
    low_stock_threshold: Decimal


class RecipeLinkIn(BaseModel):
    dish_id: int
    quantity_per_dish: Decimal


class WasteIn(BaseModel):
    quantity: Decimal
    reason: str | None = None


class RestockIn(BaseModel):
    quantity: Decimal
