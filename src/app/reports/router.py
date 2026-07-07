from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.reports.zreport import build_z_report

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


@router.get("/z-report")
async def z_report(
    target_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    report = await build_z_report(session, restaurant_id=restaurant.id, target_date=target_date)
    return {
        **report,
        "gross_sales_aed": str(report["gross_sales_aed"]),
        "total_discounts_aed": str(report["total_discounts_aed"]),
        "cod_collected_aed": str(report["cod_collected_aed"]),
        "drawer_sessions": [
            {
                **s,
                "opening_float_aed": str(s["opening_float_aed"]),
                "closing_count_aed": str(s["closing_count_aed"]) if s["closing_count_aed"] is not None else None,
                "variance_aed": str(s["variance_aed"]) if s["variance_aed"] is not None else None,
            }
            for s in report["drawer_sessions"]
        ],
    }
