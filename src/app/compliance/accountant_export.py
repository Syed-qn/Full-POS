"""Accountant export pack — orders, VAT, credit notes, refund notes (Cat 13)."""

from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.compliance.models import RefundNote
from app.compliance.tax_settings import tax_settings
from app.ordering.models import Order, OrderItem


def _dt_start(d: date) -> datetime:
    # DB timestamps are often naive UTC; keep comparisons offset-naive.
    return datetime.combine(d, time.min)


def _dt_end(d: date) -> datetime:
    return datetime.combine(d, time.max)


async def build_accountant_export(
    session: AsyncSession,
    *,
    restaurant,
    start_date: date,
    end_date: date,
    format: str = "json",
) -> dict:
    """Export fiscal period for accountants (JSON or CSV strings)."""
    cfg = tax_settings(restaurant.settings)
    start = _dt_start(start_date)
    end = _dt_end(end_date)

    orders = list(
        (
            await session.scalars(
                select(Order)
                .where(
                    Order.restaurant_id == restaurant.id,
                    Order.created_at >= start,
                    Order.created_at <= end,
                    Order.status.notin_(["draft"]),
                )
                .order_by(Order.id.asc())
            )
        ).all()
    )
    order_ids = [o.id for o in orders]
    items_by_order: dict[int, list] = {oid: [] for oid in order_ids}
    if order_ids:
        items = list(
            (
                await session.scalars(
                    select(OrderItem).where(OrderItem.order_id.in_(order_ids))
                )
            ).all()
        )
        for it in items:
            items_by_order.setdefault(it.order_id, []).append(it)

    refund_notes = list(
        (
            await session.scalars(
                select(RefundNote)
                .where(
                    RefundNote.restaurant_id == restaurant.id,
                    RefundNote.issued_at >= start,
                    RefundNote.issued_at <= end,
                )
                .order_by(RefundNote.id.asc())
            )
        ).all()
    )

    credit_notes: list = []
    try:
        from app.payments.models import CreditNote

        credit_notes = list(
            (
                await session.scalars(
                    select(CreditNote)
                    .where(
                        CreditNote.restaurant_id == restaurant.id,
                        CreditNote.issued_at >= start,
                        CreditNote.issued_at <= end,
                    )
                    .order_by(CreditNote.id.asc())
                )
            ).all()
        )
    except Exception:  # noqa: BLE001
        credit_notes = []

    rows = []
    vat_total = Decimal("0.00")
    net_total = Decimal("0.00")
    gross_total = Decimal("0.00")
    for o in orders:
        vat = Decimal(str(o.vat_amount_aed or 0))
        sub = Decimal(str(o.subtotal or 0))
        tot = Decimal(str(o.total or 0))
        vat_total += vat
        net_total += sub
        gross_total += tot
        line_vat = [
            {
                "dish_name": it.dish_name,
                "qty": it.qty,
                "price_aed": str(it.price_aed),
                "vat_rate": str(getattr(it, "vat_rate", None) or o.vat_rate),
                "vat_amount_aed": str(getattr(it, "vat_amount_aed", None) or 0),
            }
            for it in items_by_order.get(o.id, [])
        ]
        rows.append(
            {
                "order_id": o.id,
                "order_number": o.order_number,
                "status": o.status,
                "invoice_kind": getattr(o, "invoice_kind", None),
                "tax_pricing_mode": getattr(o, "tax_pricing_mode", None),
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "subtotal_aed": str(sub),
                "vat_rate": str(o.vat_rate),
                "vat_amount_aed": str(vat),
                "delivery_fee_aed": str(o.delivery_fee_aed or 0),
                "total_aed": str(tot),
                "line_items": line_vat,
            }
        )

    payload = {
        "export_type": "accountant_pack",
        "restaurant_id": restaurant.id,
        "restaurant_name": restaurant.name,
        "trn": cfg.get("trn"),
        "legal_name": cfg.get("legal_name") or restaurant.name,
        "legal_name_ar": cfg.get("legal_name_ar"),
        "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "currency": getattr(restaurant, "currency", None) or "AED",
        "summary": {
            "order_count": len(rows),
            "net_total_aed": str(net_total),
            "vat_total_aed": str(vat_total),
            "gross_total_aed": str(gross_total),
            "refund_note_count": len(refund_notes),
            "credit_note_count": len(credit_notes),
        },
        "orders": rows,
        "refund_notes": [
            {
                "refund_note_number": n.refund_note_number,
                "order_id": n.order_id,
                "amount_aed": str(n.amount_aed),
                "vat_amount_aed": str(n.vat_amount_aed),
                "reason": n.reason,
                "issued_at": n.issued_at.isoformat() if n.issued_at else None,
            }
            for n in refund_notes
        ],
        "credit_notes": [
            {
                "credit_note_number": getattr(n, "credit_note_number", None),
                "order_id": getattr(n, "order_id", None),
                "amount_aed": str(getattr(n, "amount_aed", 0)),
                "issued_at": n.issued_at.isoformat()
                if getattr(n, "issued_at", None)
                else None,
            }
            for n in credit_notes
        ],
    }

    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(
            [
                "order_number",
                "status",
                "invoice_kind",
                "created_at",
                "subtotal_aed",
                "vat_amount_aed",
                "total_aed",
            ]
        )
        for r in rows:
            w.writerow(
                [
                    r["order_number"],
                    r["status"],
                    r["invoice_kind"],
                    r["created_at"],
                    r["subtotal_aed"],
                    r["vat_amount_aed"],
                    r["total_aed"],
                ]
            )
        payload["csv"] = buf.getvalue()
        payload["format"] = "csv"
    else:
        payload["format"] = "json"
        payload["json_bytes"] = len(json.dumps(payload, default=str))

    return payload
