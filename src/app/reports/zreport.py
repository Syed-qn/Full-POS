from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cashdrawer.models import CashDrawerSession
from app.cod.models import CodCollection
from app.ordering.models import Order


async def build_z_report(session: AsyncSession, *, restaurant_id: int, target_date: date) -> dict:
    day_start = datetime.combine(target_date, time.min)
    day_end = datetime.combine(target_date, time.max)

    orders = (await session.scalars(
        select(Order).where(
            Order.restaurant_id == restaurant_id,
            Order.created_at >= day_start,
            Order.created_at <= day_end,
        )
    )).all()
    delivered = [o for o in orders if o.status == "delivered"]

    collections = (await session.scalars(
        select(CodCollection).where(
            CodCollection.restaurant_id == restaurant_id,
            CodCollection.collected_at >= day_start,
            CodCollection.collected_at <= day_end,
        )
    )).all()

    sessions = (await session.scalars(
        select(CashDrawerSession).where(
            CashDrawerSession.restaurant_id == restaurant_id,
            CashDrawerSession.opened_at >= day_start,
            CashDrawerSession.opened_at <= day_end,
        )
    )).all()

    return {
        "date": target_date.isoformat(),
        "order_count": len(orders),
        "delivered_order_count": len(delivered),
        "gross_sales_aed": sum((o.total for o in delivered), Decimal("0.00")),
        "total_discounts_aed": sum(
            (
                (o.coupon_discount_aed or Decimal("0"))
                + (getattr(o, "manager_discount_aed", None) or Decimal("0"))
                + (getattr(o, "staff_discount_aed", None) or Decimal("0"))
                for o in delivered
            ),
            Decimal("0.00"),
        ),
        "cod_collected_aed": sum((c.amount_aed for c in collections), Decimal("0.00")),
        "drawer_sessions": [
            {
                "id": s.id,
                "opening_float_aed": s.opening_float_aed,
                "closing_count_aed": s.closing_count_aed,
                "variance_aed": s.variance_aed,
                "status": s.status,
            }
            for s in sessions
        ],
    }
