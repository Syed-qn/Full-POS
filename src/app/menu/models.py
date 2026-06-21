from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TimestampMixin


class Menu(Base, TimestampMixin):
    __tablename__ = "menus"
    __table_args__ = (UniqueConstraint("restaurant_id", "version"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="pending_confirmation")
    # pending_confirmation | active | superseded
    source_files: Mapped[list] = mapped_column(JSONB, default=list)

    dishes: Mapped[list["Dish"]] = relationship(
        back_populates="menu", cascade="all, delete-orphan", lazy="selectin"
    )


class Dish(Base, TimestampMixin):
    __tablename__ = "dishes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    menu_id: Mapped[int] = mapped_column(ForeignKey("menus.id"), index=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    dish_number: Mapped[int | None] = mapped_column(Integer)  # null = extraction gap, must fix before activate
    name: Mapped[str] = mapped_column(String(255))
    price_aed: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    category: Mapped[str | None] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(String(2000))
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    name_normalized: Mapped[str | None] = mapped_column(String(256))
    # Estimated cook time for one portion (minutes). Null = unknown -> the order's cook
    # estimate falls back to the restaurant's default_prep_minutes setting.
    prep_minutes: Mapped[int | None] = mapped_column(Integer)

    menu: Mapped["Menu"] = relationship(back_populates="dishes", lazy="raise_on_sql")


class MenuFile(Base, TimestampMixin):
    __tablename__ = "menu_files"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    menu_id: Mapped[int | None] = mapped_column(ForeignKey("menus.id"), index=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    content_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer)
    original_filename: Mapped[str | None] = mapped_column(String(512))
