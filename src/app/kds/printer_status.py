from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class PrinterStatus(Base, TimestampMixin):
    """Per-station printer heartbeat, used to detect a dead printer so the
    kitchen can fall back to another one. One row per (restaurant, station)."""

    __tablename__ = "printer_statuses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("kitchen_stations.id"), index=True)
    healthy: Mapped[bool] = mapped_column(Boolean, default=True)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


async def record_printer_heartbeat(
    session: AsyncSession, *, restaurant_id: int, station_id: int, healthy: bool
) -> None:
    row = await session.scalar(
        select(PrinterStatus).where(
            PrinterStatus.restaurant_id == restaurant_id,
            PrinterStatus.station_id == station_id,
        )
    )
    now = datetime.now(timezone.utc)
    if row is None:
        session.add(PrinterStatus(
            restaurant_id=restaurant_id, station_id=station_id,
            healthy=healthy, last_heartbeat_at=now,
        ))
    else:
        row.healthy = healthy
        row.last_heartbeat_at = now
    await session.flush()


async def get_printer_status(session: AsyncSession, *, restaurant_id: int) -> list[dict]:
    rows = (await session.scalars(
        select(PrinterStatus).where(PrinterStatus.restaurant_id == restaurant_id)
    )).all()
    return [
        {
            "station_id": row.station_id,
            "healthy": row.healthy,
            "last_heartbeat_at": row.last_heartbeat_at,
        }
        for row in rows
    ]
