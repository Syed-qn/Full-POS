from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.inventory.service import daily_stock_closing, inventory_valuation
from app.reports.analytics import (
    avg_prep_time_by_item,
    avg_prep_time_by_staff,
    driver_performance_report,
    inventory_usage,
    invoice_sequence_report,
    item_performance,
    labor_hours,
    retention_report,
    sales_rollup,
    table_turn_time,
)
from app.reports.csv_export import rows_to_csv
from app.reports.extended import (
    average_delivery_time,
    average_order_value,
    build_owner_daily_summary,
    dead_menu_items,
    discount_report,
    food_cost_report,
    forecasted_sales_aed,
    gross_profit_report,
    peak_hour_report,
    refund_report,
    retention_cohort_report,
    sales_by_category,
    sales_by_channel,
    sales_by_payment_method,
    sales_by_waiter,
    send_owner_whatsapp_report,
    slow_moving_items,
    tax_report,
    top_selling_items,
    void_report,
    wastage_report,
)
from app.reports.xlsx_export import build_xlsx
from app.reports.zreport import build_z_report

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


def _money_rows(rows: list[dict], money_keys: tuple[str, ...]) -> list[dict]:
    out = []
    for r in rows:
        nr = dict(r)
        for k in money_keys:
            if k in nr and not isinstance(nr[k], str):
                nr[k] = str(nr[k])
        out.append(nr)
    return out


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
        {
            **r,
            "revenue_aed": str(r["revenue_aed"]),
            "food_cost_aed": str(r["food_cost_aed"]),
            "margin_aed": str(r["margin_aed"]),
            "food_cost_pct": r.get("food_cost_pct", 0.0),
        }
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


@router.get("/retention-cohort")
async def retention_cohort_endpoint(
    start_date: date, end_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await retention_cohort_report(
        session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date
    )


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


@router.get("/driver-performance")
async def driver_performance_endpoint(
    start_date: date, end_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await driver_performance_report(
        session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date
    )


@router.get("/daily-stock-closing")
async def daily_stock_closing_report(
    target_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = await daily_stock_closing(session, restaurant_id=restaurant.id, target_date=target_date)
    return [{**r, "closing_stock": str(r["closing_stock"])} for r in rows]


@router.get("/inventory-valuation")
async def inventory_valuation_report(
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    report = await inventory_valuation(session, restaurant_id=restaurant.id)
    return {
        "total_value_aed": str(report["total_value_aed"]),
        "rows": [
            {
                **row,
                "current_stock": str(row["current_stock"]),
                "cost_per_unit_aed": str(row["cost_per_unit_aed"]),
                "value_aed": str(row["value_aed"]),
            }
            for row in report["rows"]
        ],
    }


@router.get("/invoice-sequence-check")
async def invoice_sequence_check(
    start_date: date, end_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await invoice_sequence_report(
        session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date
    )


# ── Category 10 extended ──────────────────────────────────────────────────────


@router.get("/sales-by-category")
async def sales_by_category_endpoint(
    start_date: date, end_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = await sales_by_category(
        session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date
    )
    return _money_rows(rows, ("revenue_aed",))


@router.get("/sales-by-channel")
async def sales_by_channel_endpoint(
    start_date: date, end_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = await sales_by_channel(
        session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date
    )
    return _money_rows(rows, ("revenue_aed", "aov_aed"))


@router.get("/sales-by-waiter")
async def sales_by_waiter_endpoint(
    start_date: date, end_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = await sales_by_waiter(
        session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date
    )
    return _money_rows(rows, ("revenue_aed",))


@router.get("/sales-by-payment-method")
async def sales_by_payment_method_endpoint(
    start_date: date, end_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await sales_by_payment_method(
        session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date
    )


@router.get("/gross-profit")
async def gross_profit_endpoint(
    start_date: date, end_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await gross_profit_report(
        session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date
    )


@router.get("/food-cost")
async def food_cost_endpoint(
    start_date: date, end_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await food_cost_report(
        session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date
    )


@router.get("/discounts")
async def discounts_endpoint(
    start_date: date, end_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await discount_report(
        session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date
    )


@router.get("/voids")
async def voids_endpoint(
    start_date: date, end_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await void_report(
        session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date
    )


@router.get("/refunds")
async def refunds_endpoint(
    start_date: date, end_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await refund_report(
        session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date
    )


@router.get("/wastage")
async def wastage_endpoint(
    start_date: date, end_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await wastage_report(
        session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date
    )


@router.get("/top-selling")
async def top_selling_endpoint(
    start_date: date, end_date: date,
    limit: int = Query(default=10, ge=1, le=100),
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await top_selling_items(
        session,
        restaurant_id=restaurant.id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )


@router.get("/slow-moving")
async def slow_moving_endpoint(
    start_date: date, end_date: date,
    max_qty: int = Query(default=3, ge=0, le=50),
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await slow_moving_items(
        session,
        restaurant_id=restaurant.id,
        start_date=start_date,
        end_date=end_date,
        max_qty=max_qty,
    )


@router.get("/dead-menu-items")
async def dead_menu_endpoint(
    start_date: date, end_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await dead_menu_items(
        session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date
    )


@router.get("/aov")
async def aov_endpoint(
    start_date: date, end_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await average_order_value(
        session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date
    )


@router.get("/avg-delivery-time")
async def avg_delivery_endpoint(
    start_date: date, end_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await average_delivery_time(
        session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date
    )


@router.get("/peak-hours")
async def peak_hours_endpoint(
    start_date: date, end_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await peak_hour_report(
        session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date
    )


@router.get("/tax")
async def tax_endpoint(
    start_date: date, end_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await tax_report(
        session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date
    )


@router.get("/forecasted-sales")
async def forecasted_sales_endpoint(
    horizon: str = "tomorrow",
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await forecasted_sales_aed(
        session, restaurant_id=restaurant.id, horizon=horizon
    )


@router.get("/owner-daily-summary")
async def owner_daily_summary(
    target_date: date | None = None,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    day = target_date or date.today()
    return await build_owner_daily_summary(
        session, restaurant_id=restaurant.id, target_date=day
    )


@router.post("/owner-whatsapp-report")
async def owner_whatsapp_report(
    target_date: date | None = None,
    to_phone: str | None = None,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        result = await send_owner_whatsapp_report(
            session,
            restaurant=restaurant,
            target_date=target_date,
            to_phone=to_phone,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return result


@router.get("/export.xlsx")
async def export_workbook(
    start_date: date,
    end_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """Multi-sheet Excel export of core owner reports for the date range."""
    rid = restaurant.id
    items = await item_performance(
        session, restaurant_id=rid, start_date=start_date, end_date=end_date
    )
    channels = await sales_by_channel(
        session, restaurant_id=rid, start_date=start_date, end_date=end_date
    )
    waiters = await sales_by_waiter(
        session, restaurant_id=rid, start_date=start_date, end_date=end_date
    )
    cats = await sales_by_category(
        session, restaurant_id=rid, start_date=start_date, end_date=end_date
    )
    pays = await sales_by_payment_method(
        session, restaurant_id=rid, start_date=start_date, end_date=end_date
    )
    voids = await void_report(
        session, restaurant_id=rid, start_date=start_date, end_date=end_date
    )
    refunds = await refund_report(
        session, restaurant_id=rid, start_date=start_date, end_date=end_date
    )
    tax = await tax_report(
        session, restaurant_id=rid, start_date=start_date, end_date=end_date
    )
    aov = await average_order_value(
        session, restaurant_id=rid, start_date=start_date, end_date=end_date
    )

    sheets = {
        "Items": (
            ["dish", "qty", "revenue", "food_cost", "margin", "margin_pct"],
            [
                [
                    r["dish_name"],
                    str(r["order_count"]),
                    str(r["revenue_aed"]),
                    str(r["food_cost_aed"]),
                    str(r["margin_aed"]),
                    str(r["margin_pct"]),
                ]
                for r in items
            ],
        ),
        "Channels": (
            ["channel", "orders", "revenue", "aov"],
            [
                [c["channel"], str(c["order_count"]), str(c["revenue_aed"]), str(c["aov_aed"])]
                for c in channels
            ],
        ),
        "Waiters": (
            ["staff", "orders", "revenue"],
            [
                [w["staff_name"], str(w["order_count"]), str(w["revenue_aed"])]
                for w in waiters
            ],
        ),
        "Categories": (
            ["category", "qty", "revenue"],
            [[c["category"], str(c["qty"]), str(c["revenue_aed"])] for c in cats],
        ),
        "Payments": (
            ["tender", "txns", "gross", "refunded", "net"],
            [
                [
                    p["tender_type"],
                    str(p["txn_count"]),
                    p["gross_aed"],
                    p["refunded_aed"],
                    p["net_aed"],
                ]
                for p in pays
            ],
        ),
        "Voids": (
            ["order", "total", "reason"],
            [
                [v["order_number"], v["total_aed"], v["reason"] or ""]
                for v in voids["rows"]
            ],
        ),
        "Refunds": (
            ["txn", "order_id", "tender", "refunded"],
            [
                [str(r["txn_id"]), str(r["order_id"]), r["tender_type"], r["refunded_amount_aed"]]
                for r in refunds["rows"]
            ],
        ),
        "Summary": (
            ["metric", "value"],
            [
                ["AOV", aov["aov_aed"]],
                ["Orders", str(aov["order_count"])],
                ["Revenue", aov["revenue_aed"]],
                ["VAT total", tax["vat_total_aed"]],
                ["Void count", str(voids["void_count"])],
                ["Refund total", refunds["refunded_total_aed"]],
            ],
        ),
    }
    data = build_xlsx(sheets)
    filename = f"reports-{start_date}-to-{end_date}.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
