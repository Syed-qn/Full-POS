from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.reports.analytics import (
    avg_prep_time_by_item,
    avg_prep_time_by_staff,
    inventory_usage,
    item_performance,
    labor_hours,
    retention_report,
    sales_rollup,
    table_turn_time,
)
from app.reports.csv_export import rows_to_csv
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


@router.get("/item-performance")
async def item_performance_report(
    start_date: date, end_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = await item_performance(session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date)
    return [
        {**r, "revenue_aed": str(r["revenue_aed"]), "food_cost_aed": str(r["food_cost_aed"]), "margin_aed": str(r["margin_aed"])}
        for r in rows
    ]


@router.get("/item-performance.csv")
async def item_performance_csv(
    start_date: date, end_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = await item_performance(session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date)
    csv_rows = [
        {
            "dish_name": r["dish_name"], "order_count": r["order_count"],
            "revenue_aed": str(r["revenue_aed"]), "food_cost_aed": str(r["food_cost_aed"]),
            "margin_aed": str(r["margin_aed"]), "margin_pct": r["margin_pct"],
        }
        for r in rows
    ]
    return PlainTextResponse(
        rows_to_csv(csv_rows), media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=item-performance-{start_date}-to-{end_date}.csv"},
    )


@router.get("/inventory-usage")
async def inventory_usage_report(
    start_date: date, end_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = await inventory_usage(session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date)
    return [{**r, "quantity_used": str(r["quantity_used"])} for r in rows]


@router.get("/table-turn-time")
async def table_turn_time_report(
    start_date: date, end_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await table_turn_time(session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date)


@router.get("/prep-time-by-item")
async def prep_time_by_item_report(
    start_date: date, end_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await avg_prep_time_by_item(
        session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date
    )


@router.get("/prep-time-by-staff")
async def prep_time_by_staff_report(
    start_date: date, end_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await avg_prep_time_by_staff(
        session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date
    )


@router.get("/labor-hours")
async def labor_hours_report(
    target_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await labor_hours(session, restaurant_id=restaurant.id, target_date=target_date)


@router.get("/sales-rollup")
async def sales_rollup_report(
    start_date: date, end_date: date, granularity: str = "daily",
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        rows = await sales_rollup(
            session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date,
            granularity=granularity,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [{**r, "revenue_aed": str(r["revenue_aed"])} for r in rows]


@router.get("/retention")
async def retention_endpoint(
    start_date: date, end_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await retention_report(session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date)


@router.get("/nps-summary")
async def nps_summary_report(
    start_date: date, end_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    from app.loyalty.nps import nps_summary

    return await nps_summary(
        session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date
    )
