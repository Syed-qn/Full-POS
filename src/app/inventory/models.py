from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class Ingredient(Base, TimestampMixin):
    __tablename__ = "ingredients"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    unit: Mapped[str] = mapped_column(String(16))
    current_stock: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=Decimal("0.000"))
    low_stock_threshold: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=Decimal("0.000"))
    # Target stock level to restock UP TO (distinct from low_stock_threshold, which is the
    # trigger point that flags an ingredient as "low").
    par_level: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=Decimal("0.000"))
    # Cost basis for food-cost/margin reporting — what THIS restaurant pays per unit.
    cost_per_unit_aed: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0.0000"))


class DishIngredient(Base, TimestampMixin):
    __tablename__ = "dish_ingredients"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    dish_id: Mapped[int] = mapped_column(ForeignKey("dishes.id"), index=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), index=True)
    quantity_per_dish: Mapped[Decimal] = mapped_column(Numeric(10, 3))


class WasteLog(Base, TimestampMixin):
    __tablename__ = "waste_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    reason: Mapped[str | None] = mapped_column(String(256))
    recorded_by: Mapped[str] = mapped_column(String(64))


class Vendor(Base, TimestampMixin):
    __tablename__ = "vendors"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(128))


class PurchaseOrder(Base, TimestampMixin):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")


class PurchaseOrderLine(Base, TimestampMixin):
    __tablename__ = "purchase_order_lines"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), index=True)
    qty_ordered: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    unit_cost_aed: Mapped[Decimal] = mapped_column(Numeric(10, 4))


class IngredientBatch(Base, TimestampMixin):
    __tablename__ = "ingredient_batches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), index=True)
    qty: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    expiry_date: Mapped[date] = mapped_column(Date)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IngredientSubstitute(Base, TimestampMixin):
    __tablename__ = "ingredient_substitutes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), index=True)
    substitute_ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), index=True)
    notes: Mapped[str | None] = mapped_column(String(256))


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
