from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class DiningTable(Base, TimestampMixin):
    __tablename__ = "tables"
    __table_args__ = (UniqueConstraint("qr_token", name="uq_tables_qr_token"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    label: Mapped[str] = mapped_column(String(32))
    seats: Mapped[int] = mapped_column(Integer, default=2)
    pos_x: Mapped[float] = mapped_column(Float, default=0.0)
    pos_y: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="available")
    # Degrees clockwise. A real room has tables at angles — a banquette along a
    # diagonal wall, a bar-end two-top — so the plan must be able to say so.
    rotation: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    # Opaque token for QR-table ordering links (public order create).
    qr_token: Mapped[str | None] = mapped_column(String(64), index=True)
    # Soft delete. Orders keep a FK to their table, so a table a guest ever sat
    # at can never be hard-deleted without destroying order history — removing
    # a table from the floor archives it and every read filters it out.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # JOINED TABLES. One party too big for a single table (12 guests across three
    # tables) is ONE invoice: the secondary tables point at the table that holds
    # the bill. Both stay OCCUPIED while they eat — unlike an order merge, which
    # frees the other table at once and is right only when guests physically move.
    # Null = a table standing on its own. One level only: a primary is never
    # itself a secondary (joins resolve through to the primary), so this cannot
    # form a chain or a cycle.
    merged_into_table_id: Mapped[int | None] = mapped_column(
        ForeignKey("tables.id"), index=True
    )
    # WHICH bill is the group's invoice, set on the PRIMARY table. A table can
    # carry several bills at once (two parties sharing it), so "join T02 to T01" is
    # ambiguous until somebody says which party at T01 the T02 guests belong to.
    # Without this, folded-in food and later rounds land on DIFFERENT bills: the
    # join folded into the oldest, while order creation appends to the newest.
    # Plain BigInteger and not a ForeignKey to orders.id on purpose — orders
    # already reference tables.id, and a second FK the other way makes the two
    # tables mutually dependent, which alembic cannot order and a delete cannot
    # unwind. Cleared when the invoice settles.
    group_bill_order_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
