from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Numeric, String
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
