from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin

# Waste / spoilage reason classification
WASTE_REASON_TYPES = frozenset({"wastage", "spoilage", "theft", "over_portion", "other"})

# Kitchen role for multi-location / commissary inventory
KITCHEN_ROLES = frozenset({"branch", "central", "commissary"})


class StockLocation(Base, TimestampMixin):
    """Sub-location within a restaurant (walk-in, prep, bar, central kitchen, commissary)."""

    __tablename__ = "stock_locations"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "code", name="uq_stock_locations_restaurant_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    code: Mapped[str] = mapped_column(String(32))
    # branch | central | commissary
    kitchen_role: Mapped[str] = mapped_column(String(16), default="branch", server_default="branch")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class Ingredient(Base, TimestampMixin):
    __tablename__ = "ingredients"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    unit: Mapped[str] = mapped_column(String(16))
    current_stock: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=Decimal("0.000"))
    low_stock_threshold: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=Decimal("0.000"))
    par_level: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=Decimal("0.000"))
    cost_per_unit_aed: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0.0000"))
    # Default stock location (multi-location support).
    location_id: Mapped[int | None] = mapped_column(ForeignKey("stock_locations.id"), index=True)
    # Preferred vendor for reorders.
    preferred_vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id"), index=True)


class DishIngredient(Base, TimestampMixin):
    __tablename__ = "dish_ingredients"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    dish_id: Mapped[int] = mapped_column(ForeignKey("dishes.id"), index=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), index=True)
    quantity_per_dish: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    # Recipe yield % (e.g. 90 means 10% loss in prep). Default 100 = full yield.
    yield_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("100.00"), server_default="100.00"
    )


class WasteLog(Base, TimestampMixin):
    __tablename__ = "waste_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    reason: Mapped[str | None] = mapped_column(String(256))
    # wastage | spoilage | theft | over_portion | other
    reason_type: Mapped[str] = mapped_column(String(16), default="wastage", server_default="wastage")
    recorded_by: Mapped[str] = mapped_column(String(64))
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("ingredient_batches.id"))


class Vendor(Base, TimestampMixin):
    __tablename__ = "vendors"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    notes: Mapped[str | None] = mapped_column(String(256))


class PurchaseOrder(Base, TimestampMixin):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), index=True)
    # draft | ordered | partial | received | cancelled
    status: Mapped[str] = mapped_column(String(16), default="draft")
    notes: Mapped[str | None] = mapped_column(String(256))


class PurchaseOrderLine(Base, TimestampMixin):
    __tablename__ = "purchase_order_lines"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), index=True)
    qty_ordered: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    qty_received: Mapped[Decimal] = mapped_column(
        Numeric(10, 3), default=Decimal("0.000"), server_default="0"
    )
    unit_cost_aed: Mapped[Decimal] = mapped_column(Numeric(10, 4))


class GoodsReceivedNote(Base, TimestampMixin):
    """GRN against a PO — supports partial receiving."""

    __tablename__ = "goods_received_notes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    grn_number: Mapped[str] = mapped_column(String(32), index=True)
    received_by: Mapped[str] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(String(256))


class GoodsReceivedLine(Base, TimestampMixin):
    __tablename__ = "goods_received_lines"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    grn_id: Mapped[int] = mapped_column(ForeignKey("goods_received_notes.id"), index=True)
    po_line_id: Mapped[int] = mapped_column(ForeignKey("purchase_order_lines.id"), index=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), index=True)
    qty_received: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    unit_cost_aed: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    expiry_date: Mapped[date | None] = mapped_column(Date)


class IngredientBatch(Base, TimestampMixin):
    __tablename__ = "ingredient_batches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), index=True)
    qty: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    # Remaining qty after FEFO deductions (starts equal to qty).
    qty_remaining: Mapped[Decimal] = mapped_column(
        Numeric(10, 3), default=Decimal("0.000"), server_default="0"
    )
    expiry_date: Mapped[date] = mapped_column(Date)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    location_id: Mapped[int | None] = mapped_column(ForeignKey("stock_locations.id"))


class IngredientSubstitute(Base, TimestampMixin):
    __tablename__ = "ingredient_substitutes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), index=True)
    substitute_ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), index=True)
    notes: Mapped[str | None] = mapped_column(String(256))
    # Conversion factor: 1 unit primary = factor units substitute (default 1:1).
    conversion_factor: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), default=Decimal("1.0000"), server_default="1"
    )
    priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class StockAdjustmentRequest(Base, TimestampMixin):
    __tablename__ = "stock_adjustment_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), index=True)
    requested_qty: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    previous_qty_snapshot: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    reason: Mapped[str | None] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    requested_by: Mapped[str] = mapped_column(String(64))
    approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StockCountLog(Base, TimestampMixin):
    """Historical stock counts for variance reporting."""

    __tablename__ = "stock_count_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), index=True)
    previous_stock: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    counted_stock: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    variance: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    counted_by: Mapped[str] = mapped_column(String(64), default="manager")


class StockClosingSnapshot(Base, TimestampMixin):
    """True EOD stock snapshot (one row per ingredient per calendar day)."""

    __tablename__ = "stock_closing_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "restaurant_id",
            "ingredient_id",
            "closing_date",
            name="uq_stock_closing_rest_ing_date",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), index=True)
    closing_date: Mapped[date] = mapped_column(Date, index=True)
    closing_stock: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    unit: Mapped[str] = mapped_column(String(16))
    valuation_aed: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))


class StockAnomalyAlert(Base, TimestampMixin):
    """Persisted over-portioning / theft-loss alerts."""

    __tablename__ = "stock_anomaly_alerts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), index=True)
    # over_portion | theft_loss | count_variance
    alert_type: Mapped[str] = mapped_column(String(24))
    expected_qty: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    actual_qty: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    variance_pct: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open")
    message: Mapped[str | None] = mapped_column(String(256))
