from datetime import date, datetime, timedelta

from sqlalchemy import BigInteger, DateTime, ForeignKey, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class Shift(Base, TimestampMixin):
    __tablename__ = "shifts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff_members.id"), index=True)
    scheduled_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    scheduled_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))


async def create_shift(
    session: AsyncSession, *, restaurant_id: int, staff_id: int,
    scheduled_start: datetime, scheduled_end: datetime,
) -> Shift:
    shift = Shift(
        restaurant_id=restaurant_id, staff_id=staff_id,
        scheduled_start=scheduled_start, scheduled_end=scheduled_end,
    )
    session.add(shift)
    await session.flush()
    return shift


async def list_shifts_for_week(
    session: AsyncSession, *, restaurant_id: int, week_start: date,
) -> list[Shift]:
    week_end = week_start + timedelta(days=7)
    rows = await session.scalars(
        select(Shift)
        .where(
            Shift.restaurant_id == restaurant_id,
            Shift.scheduled_start >= week_start,
            Shift.scheduled_start < week_end,
        )
        .order_by(Shift.scheduled_start)
    )
    return list(rows)
