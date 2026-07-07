from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class KitchenStation(Base, TimestampMixin):
    __tablename__ = "kitchen_stations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    printer_ip: Mapped[str | None] = mapped_column(String(64))
    printer_port: Mapped[int | None] = mapped_column(Integer)


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
