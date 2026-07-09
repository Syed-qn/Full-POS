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
    yield_pct: Decimal = Decimal("100.00")


class WasteIn(BaseModel):
    quantity: Decimal
    reason: str | None = None
    reason_type: str = "wastage"  # wastage | spoilage | theft | over_portion | other
    batch_id: int | None = None


class RestockIn(BaseModel):
    quantity: Decimal


class StockCountIn(BaseModel):
    counted_qty: Decimal


class StockCountOut(BaseModel):
    variance: Decimal
    previous_stock: Decimal
    counted_stock: Decimal
    variance_pct: float | None = None


class BatchIn(BaseModel):
    qty: Decimal
    expiry_date: date
    location_id: int | None = None


class BatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ingredient_id: int
    qty: Decimal
    qty_remaining: Decimal | None = None
    expiry_date: date
    received_at: datetime
    location_id: int | None = None


class VendorIn(BaseModel):
    name: str
    phone: str | None = None
    email: str | None = None
    notes: str | None = None


class VendorPatch(BaseModel):
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    notes: str | None = None
    is_active: bool | None = None


class VendorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    phone: str | None = None
    email: str | None = None
    notes: str | None = None
    is_active: bool = True


class PurchaseOrderLineIn(BaseModel):
    ingredient_id: int
    qty_ordered: Decimal
    unit_cost_aed: Decimal


class PurchaseOrderIn(BaseModel):
    vendor_id: int
    lines: list[PurchaseOrderLineIn]
    notes: str | None = None


class PurchaseOrderLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ingredient_id: int
    qty_ordered: Decimal
    qty_received: Decimal = Decimal("0")
    unit_cost_aed: Decimal


class PurchaseOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    vendor_id: int
    status: str
    notes: str | None = None
    lines: list[PurchaseOrderLineOut] = []


class GrnLineIn(BaseModel):
    po_line_id: int
    qty_received: Decimal
    unit_cost_aed: Decimal | None = None
    expiry_date: date | None = None


class GrnIn(BaseModel):
    po_id: int
    lines: list[GrnLineIn]
    notes: str | None = None


class GrnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    po_id: int
    grn_number: str
    received_by: str
    notes: str | None = None


class StockLocationIn(BaseModel):
    name: str
    code: str
    kitchen_role: str = "branch"  # branch | central | commissary


class StockLocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    code: str
    kitchen_role: str
    is_active: bool = True


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
    conversion_factor: Decimal = Decimal("1")
    priority: int = 0


class SubstituteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ingredient_id: int
    substitute_ingredient_id: int
    notes: str | None = None
    conversion_factor: Decimal | None = None
    priority: int | None = None


class StockClosingOut(BaseModel):
    ingredient_id: int
    ingredient_name: str
    closing_stock: Decimal
    unit: str


class VendorPriceComparisonOut(BaseModel):
    vendor_id: int
    vendor_name: str
    unit_cost_aed: Decimal
    purchase_order_id: int
    purchase_order_line_id: int


class InventoryValuationRowOut(BaseModel):
    ingredient_id: int
    ingredient_name: str
    unit: str
    current_stock: Decimal
    cost_per_unit_aed: Decimal
    value_aed: Decimal


class InventoryValuationOut(BaseModel):
    total_value_aed: Decimal
    rows: list[InventoryValuationRowOut]


class StockAdjustmentIn(BaseModel):
    requested_qty: Decimal
    reason: str | None = None
    requested_by: str = "manager"


class StockAdjustmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ingredient_id: int
    requested_qty: Decimal
    previous_qty_snapshot: Decimal
    reason: str | None = None
    status: str
    requested_by: str
    approved_by: str | None = None
    decided_at: datetime | None = None


class LowStockAlertOut(BaseModel):
    enqueued: bool
    reason: str | None = None
    outbox_id: int | None = None
