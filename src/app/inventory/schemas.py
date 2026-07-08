from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class IngredientIn(BaseModel):
    name: str
    unit: str
    current_stock: Decimal = Decimal("0.000")
    low_stock_threshold: Decimal = Decimal("0.000")
    par_level: Decimal = Decimal("0.000")
    cost_per_unit_aed: Decimal = Decimal("0.0000")


class IngredientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    unit: str
    current_stock: Decimal
    low_stock_threshold: Decimal
    par_level: Decimal
    cost_per_unit_aed: Decimal


class CostIn(BaseModel):
    cost_per_unit_aed: Decimal


class RecipeLinkIn(BaseModel):
    dish_id: int
    quantity_per_dish: Decimal


class WasteIn(BaseModel):
    quantity: Decimal
    reason: str | None = None


class RestockIn(BaseModel):
    quantity: Decimal


class StockCountIn(BaseModel):
    counted_qty: Decimal


class StockCountOut(BaseModel):
    variance: Decimal
    previous_stock: Decimal
    counted_stock: Decimal


class BatchIn(BaseModel):
    qty: Decimal
    expiry_date: date


class BatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ingredient_id: int
    qty: Decimal
    expiry_date: date
    received_at: datetime


class VendorIn(BaseModel):
    name: str
    phone: str | None = None
    email: str | None = None


class VendorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    phone: str | None = None
    email: str | None = None


class PurchaseOrderLineIn(BaseModel):
    ingredient_id: int
    qty_ordered: Decimal
    unit_cost_aed: Decimal


class PurchaseOrderIn(BaseModel):
    vendor_id: int
    lines: list[PurchaseOrderLineIn]


class PurchaseOrderLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ingredient_id: int
    qty_ordered: Decimal
    unit_cost_aed: Decimal


class PurchaseOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    vendor_id: int
    status: str
    lines: list[PurchaseOrderLineOut] = []


class ReorderSuggestionOut(BaseModel):
    ingredient_id: int
    ingredient_name: str
    current_stock: Decimal
    par_level: Decimal
    suggested_order_qty: Decimal


class AnomalyCheckIn(BaseModel):
    expected_qty: Decimal
    actual_qty: Decimal
    threshold_pct: float = 15.0


class AnomalyCheckOut(BaseModel):
    ingredient_id: int
    expected_qty: Decimal
    actual_qty: Decimal
    variance_pct: float


class SubstituteIn(BaseModel):
    substitute_ingredient_id: int
    notes: str | None = None


class SubstituteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ingredient_id: int
    substitute_ingredient_id: int
    notes: str | None = None


class StockClosingOut(BaseModel):
    ingredient_id: int
    ingredient_name: str
    closing_stock: Decimal
    unit: str
