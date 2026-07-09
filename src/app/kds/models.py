from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


# First-class station types for grill/fry/beverage/dessert/pizza/cloud kitchens.
STATION_TYPES = frozenset(
    {
        "main",
        "grill",
        "fry",
        "beverage",
        "dessert",
        "pizza",
        "cloud",
        "general",
    }
)

DEFAULT_STATION_PRESETS: list[tuple[str, str]] = [
    ("Main", "main"),
    ("Grill", "grill"),
    ("Fry", "fry"),
    ("Beverage", "beverage"),
    ("Dessert", "dessert"),
    ("Pizza", "pizza"),
    ("Cloud Kitchen", "cloud"),
]


class KitchenStation(Base, TimestampMixin):
    __tablename__ = "kitchen_stations"
    __table_args__ = (
        UniqueConstraint(
            "restaurant_id", "kitchen_code", "name", name="uq_kitchen_stations_rest_code_name"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    # grill | fry | beverage | dessert | pizza | cloud | main | general
    station_type: Mapped[str] = mapped_column(String(24), default="general", server_default="general")
    # Multi-kitchen within one restaurant (e.g. "main", "cloud-a", "brand-2").
    kitchen_code: Mapped[str] = mapped_column(String(32), default="main", server_default="main")
    printer_ip: Mapped[str | None] = mapped_column(String(64))
    printer_port: Mapped[int | None] = mapped_column(Integer)
    # When this station's printer is unhealthy, print jobs route here instead.
    fallback_station_id: Mapped[int | None] = mapped_column(ForeignKey("kitchen_stations.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class CategoryStationDefault(Base, TimestampMixin):
    __tablename__ = "category_station_defaults"
    __table_args__ = (UniqueConstraint("restaurant_id", "category"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    category: Mapped[str] = mapped_column(String(128))
    station_id: Mapped[int] = mapped_column(ForeignKey("kitchen_stations.id"))


class PrintJob(Base, TimestampMixin):
    __tablename__ = "print_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("kitchen_stations.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    payload: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    # True when this job was re-routed because the original station printer was down.
    via_fallback: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    original_station_id: Mapped[int | None] = mapped_column(ForeignKey("kitchen_stations.id"))
