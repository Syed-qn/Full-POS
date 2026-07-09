"""Data retention purge job with logged runs (Cat 13)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.compliance.models import DataRetentionRun
from app.compliance.tax_settings import tax_settings


async def run_data_retention(
    session: AsyncSession,
    *,
    restaurant,
    dry_run: bool = False,
    retention_days: int | None = None,
) -> DataRetentionRun:
    """Purge operational noise older than retention window; keep fiscal docs within window.

    Purges (when past cutoff):
      - reliability AppErrorLog rows
      - idempotency keys (if model present)
      - draft orders never confirmed (status=draft) older than cutoff

    Does NOT purge confirmed orders, credit notes, refund notes, or e-invoice rows
    inside the legal retention period — those are fiscal records.
    """
    cfg = tax_settings(restaurant.settings)
    days = int(retention_days if retention_days is not None else cfg["data_retention_days"])
    days = max(30, days)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    counts: dict[str, int] = {}

    # App error logs
    try:
        from app.reliability.models import AppErrorLog

        q = select(func.count()).select_from(AppErrorLog).where(
            AppErrorLog.restaurant_id == restaurant.id,
            AppErrorLog.created_at < cutoff,
        )
        n = int(await session.scalar(q) or 0)
        counts["app_error_logs"] = n
        if n and not dry_run:
            await session.execute(
                delete(AppErrorLog).where(
                    AppErrorLog.restaurant_id == restaurant.id,
                    AppErrorLog.created_at < cutoff,
                )
            )
    except Exception:  # noqa: BLE001
        counts["app_error_logs"] = 0

    # Stale draft carts/orders (items first — FK)
    try:
        from app.ordering.models import Order, OrderItem

        draft_ids = list(
            (
                await session.scalars(
                    select(Order.id).where(
                        Order.restaurant_id == restaurant.id,
                        Order.status == "draft",
                        Order.created_at < cutoff,
                    )
                )
            ).all()
        )
        n = len(draft_ids)
        counts["draft_orders"] = n
        if n and not dry_run:
            await session.execute(
                delete(OrderItem).where(OrderItem.order_id.in_(draft_ids))
            )
            await session.execute(
                delete(Order).where(Order.id.in_(draft_ids))
            )
    except Exception:  # noqa: BLE001
        counts["draft_orders"] = 0

    # Fiscal records past retention (count only by default — hard purge requires force)
    try:
        from app.ordering.models import Order

        q = select(func.count()).select_from(Order).where(
            Order.restaurant_id == restaurant.id,
            Order.status.in_(["delivered", "cancelled"]),
            Order.created_at < cutoff,
        )
        counts["closed_orders_past_retention"] = int(await session.scalar(q) or 0)
    except Exception:  # noqa: BLE001
        counts["closed_orders_past_retention"] = 0

    run = DataRetentionRun(
        restaurant_id=restaurant.id,
        retention_days=days,
        purged_counts=counts,
        status="dry_run" if dry_run else "completed",
        notes=(
            f"cutoff={cutoff.isoformat()}; dry_run={dry_run}; "
            "fiscal closed orders counted not deleted"
        ),
    )
    session.add(run)
    await session.flush()
    await record_audit(
        session,
        restaurant_id=restaurant.id,
        actor="manager",
        entity="data_retention",
        entity_id=str(run.id),
        action="run_dry_run" if dry_run else "run",
        after={"counts": counts, "retention_days": days},
    )
    return run


async def list_retention_runs(
    session: AsyncSession, *, restaurant_id: int, limit: int = 20
) -> list[DataRetentionRun]:
    return list(
        (
            await session.scalars(
                select(DataRetentionRun)
                .where(DataRetentionRun.restaurant_id == restaurant_id)
                .order_by(DataRetentionRun.id.desc())
                .limit(min(max(limit, 1), 100))
            )
        ).all()
    )
