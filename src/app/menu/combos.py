from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TimestampMixin


class Combo(Base, TimestampMixin):
    """A fixed bundle of 2+ existing dishes sold together at a special price."""

    __tablename__ = "combos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    menu_id: Mapped[int] = mapped_column(ForeignKey("menus.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    price_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)

    items: Mapped[list["ComboItem"]] = relationship(
        "ComboItem", back_populates="combo", cascade="all, delete-orphan"
    )


class ComboItem(Base, TimestampMixin):
    """One component dish (and quantity) within a combo."""

    __tablename__ = "combo_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    combo_id: Mapped[int] = mapped_column(ForeignKey("combos.id"), index=True)
    dish_id: Mapped[int] = mapped_column(ForeignKey("dishes.id"), index=True)
    qty: Mapped[int] = mapped_column(Integer, default=1)

    combo: Mapped["Combo"] = relationship("Combo", back_populates="items")
