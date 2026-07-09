"""UAE VAT application + tax invoice document builders (Cat 13)."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.compliance.tax_settings import DEFAULT_VAT_RATE, tax_settings

DEFAULT_UAE_VAT_RATE = DEFAULT_VAT_RATE
Q = Decimal("0.01")


def _q(d: Decimal) -> Decimal:
    return Decimal(str(d)).quantize(Q, rounding=ROUND_HALF_UP)


def vat_from_exclusive(net: Decimal, rate: Decimal) -> Decimal:
    return _q(net * rate)


def vat_from_inclusive(gross: Decimal, rate: Decimal) -> tuple[Decimal, Decimal]:
    """Return (net, vat) extracted from a VAT-inclusive amount."""
    if rate <= 0:
        return _q(gross), Decimal("0.00")
    net = _q(gross / (Decimal("1") + rate))
    vat = _q(gross - net)
    return net, vat


def apply_vat(
    order,
    vat_rate: Decimal = DEFAULT_UAE_VAT_RATE,
    *,
    pricing_mode: str = "exclusive",
) -> None:
    """Snapshot VAT onto the order at confirm time.

    * exclusive: prices/subtotal are net; VAT is computed on top.
    * inclusive: subtotal is treated as gross; VAT is extracted and net is
      stored for reporting while vat_amount is the tax portion.
    """
    mode = (pricing_mode or "exclusive").lower()
    rate = Decimal(str(vat_rate))
    order.vat_rate = rate
    if hasattr(order, "tax_pricing_mode"):
        order.tax_pricing_mode = mode
    subtotal = Decimal(str(order.subtotal or 0))
    if mode == "inclusive":
        _net, vat = vat_from_inclusive(subtotal, rate)
        order.vat_amount_aed = vat
    else:
        order.vat_amount_aed = vat_from_exclusive(subtotal, rate)


def apply_line_vat(
    item,
    *,
    rate: Decimal,
    pricing_mode: str = "exclusive",
) -> None:
    """Stamp per-line VAT for multi-rate breakdown."""
    line_gross = Decimal(str(item.price_aed or 0)) * int(item.qty or 0)
    item.vat_rate = rate
    if pricing_mode == "inclusive":
        _net, vat = vat_from_inclusive(line_gross, rate)
        item.vat_amount_aed = vat
    else:
        item.vat_amount_aed = vat_from_exclusive(line_gross, rate)


def resolve_invoice_kind(
    *,
    total_aed: Decimal,
    buyer_trn: str | None,
    threshold: Decimal,
) -> str:
    """B2B (buyer TRN present) → full tax invoice; else simplified if under threshold."""
    if buyer_trn and str(buyer_trn).strip():
        return "tax_invoice"
    if total_aed > threshold:
        return "tax_invoice"
    return "simplified_tax_invoice"


async def apply_order_vat_from_settings(
    session: AsyncSession, *, order, restaurant
) -> None:
    """Apply VAT using restaurant tax settings + optional per-dish rates on lines."""
    from app.menu.models import Dish
    from app.ordering.models import OrderItem

    cfg = tax_settings(restaurant.settings if restaurant else None)
    mode = cfg["tax_pricing_mode"]
    default_rate = cfg["default_vat_rate"]
    apply_vat(order, default_rate, pricing_mode=mode)

    items = list(
        (
            await session.scalars(
                select(OrderItem).where(OrderItem.order_id == order.id)
            )
        ).all()
    )
    total_line_vat = Decimal("0.00")
    for item in items:
        rate = default_rate
        if item.dish_id:
            dish = await session.get(Dish, item.dish_id)
            if dish is not None and getattr(dish, "vat_rate", None) is not None:
                rate = Decimal(str(dish.vat_rate))
        apply_line_vat(item, rate=rate, pricing_mode=mode)
        total_line_vat += Decimal(str(item.vat_amount_aed or 0))
    if items:
        # Prefer summed line VAT for multi-rate accuracy.
        order.vat_amount_aed = _q(total_line_vat)

    buyer_trn = None
    if isinstance(getattr(order, "additional_details", None), str):
        # optional buyer TRN in additional_details meta is not used; check settings path
        pass
    kind = resolve_invoice_kind(
        total_aed=Decimal(str(order.total or 0)),
        buyer_trn=buyer_trn,
        threshold=cfg["simplified_invoice_threshold_aed"],
    )
    if hasattr(order, "invoice_kind"):
        order.invoice_kind = kind
    await session.flush()


async def build_tax_invoice(
    session: AsyncSession,
    *,
    order_id: int,
    restaurant_id: int,
    document_type: str | None = None,
    buyer_trn: str | None = None,
    buyer_name: str | None = None,
) -> dict:
    """Build bilingual UAE tax invoice (full or simplified)."""
    from app.identity.models import Restaurant
    from app.ordering.models import Customer, Order, OrderItem
    from app.ordering.receipt_i18n import bilingual_labels, invoice_labels

    order = await session.get(Order, order_id)
    if order is None or order.restaurant_id != restaurant_id:
        raise ValueError(f"order {order_id} not found")
    restaurant = await session.get(Restaurant, restaurant_id)
    cfg = tax_settings(restaurant.settings if restaurant else None)
    items = list(
        (
            await session.scalars(select(OrderItem).where(OrderItem.order_id == order_id))
        ).all()
    )
    customer = (
        await session.get(Customer, order.customer_id) if order.customer_id else None
    )

    kind = document_type or getattr(order, "invoice_kind", None) or resolve_invoice_kind(
        total_aed=Decimal(str(order.total or 0)),
        buyer_trn=buyer_trn,
        threshold=cfg["simplified_invoice_threshold_aed"],
    )
    mode = getattr(order, "tax_pricing_mode", None) or cfg["tax_pricing_mode"]
    labels = invoice_labels(kind)

    # Multi-rate breakdown
    rate_buckets: dict[str, dict] = {}
    line_items = []
    for item in items:
        rate = Decimal(str(getattr(item, "vat_rate", None) or order.vat_rate or cfg["default_vat_rate"]))
        line_total = Decimal(str(item.price_aed)) * int(item.qty)
        vat_amt = Decimal(str(getattr(item, "vat_amount_aed", None) or 0))
        if vat_amt == 0 and line_total > 0:
            if mode == "inclusive":
                _n, vat_amt = vat_from_inclusive(line_total, rate)
            else:
                vat_amt = vat_from_exclusive(line_total, rate)
        key = str(rate)
        b = rate_buckets.setdefault(
            key,
            {"vat_rate": key, "taxable_aed": Decimal("0"), "vat_aed": Decimal("0")},
        )
        if mode == "inclusive":
            net, _ = vat_from_inclusive(line_total, rate)
            b["taxable_aed"] += net
        else:
            b["taxable_aed"] += line_total
        b["vat_aed"] += vat_amt
        line_items.append(
            {
                "dish_name": item.dish_name,
                "qty": item.qty,
                "price_aed": str(item.price_aed),
                "line_total_aed": str(_q(line_total)),
                "vat_rate": str(rate),
                "vat_amount_aed": str(_q(vat_amt)),
                "taxable_aed": str(
                    _q(vat_from_inclusive(line_total, rate)[0])
                    if mode == "inclusive"
                    else _q(line_total)
                ),
            }
        )

    vat_breakdown = [
        {
            "vat_rate": v["vat_rate"],
            "taxable_aed": str(_q(v["taxable_aed"])),
            "vat_aed": str(_q(v["vat_aed"])),
        }
        for v in rate_buckets.values()
    ]

    trn = cfg["trn"]
    legal_name = cfg.get("legal_name") or (restaurant.name if restaurant else "")
    legal_name_ar = cfg.get("legal_name_ar")

    return {
        "document_type": kind,
        "simplified": kind == "simplified_tax_invoice",
        "restaurant_name": restaurant.name if restaurant else "",
        "legal_name": legal_name,
        "legal_name_ar": legal_name_ar,
        "trn": trn,
        "branch_trn": trn,  # per-restaurant TRN is the branch TRN in multi-branch
        "invoice_number": order.order_number,
        "order_id": order.id,
        "tax_pricing_mode": mode,
        "buyer": {
            "name": buyer_name or (customer.name if customer else None),
            "phone": customer.phone if customer else None,
            "trn": buyer_trn,
        },
        "line_items": line_items,
        "vat_breakdown": vat_breakdown,
        "subtotal_aed": str(order.subtotal),
        "delivery_fee_aed": str(order.delivery_fee_aed),
        "vat_rate": str(order.vat_rate),
        "vat_amount_aed": str(order.vat_amount_aed),
        "total_aed": str(order.total),
        "currency": getattr(restaurant, "currency", None) or "AED",
        "labels": labels,
        "labels_ar": labels["ar"],
        "labels_en": labels["en"],
        # backward-compat key used by existing tests
        "bilingual": bilingual_labels(),
    }


def build_structured_einvoice_payload(invoice: dict) -> dict:
    """PINT-AE / UAE e-invoicing oriented structured JSON (ASP-ready).

    Not full UBL XML; a stable JSON profile that an ASP adapter can map.
    """
    return {
        "profile": "PINT-AE-JSON-v1",
        "documentTypeCode": (
            "simplified"
            if invoice.get("simplified")
            else "tax_invoice"
        ),
        "invoiceNumber": invoice.get("invoice_number"),
        "currency": invoice.get("currency") or "AED",
        "seller": {
            "name": invoice.get("legal_name") or invoice.get("restaurant_name"),
            "nameAr": invoice.get("legal_name_ar"),
            "trn": invoice.get("trn"),
        },
        "buyer": invoice.get("buyer") or {},
        "taxPricingMode": invoice.get("tax_pricing_mode"),
        "lines": [
            {
                "description": li["dish_name"],
                "quantity": li["qty"],
                "unitPrice": li["price_aed"],
                "lineTotal": li["line_total_aed"],
                "vatRate": li.get("vat_rate"),
                "vatAmount": li.get("vat_amount_aed"),
                "taxableAmount": li.get("taxable_aed"),
            }
            for li in invoice.get("line_items") or []
        ],
        "taxSubtotals": invoice.get("vat_breakdown") or [],
        "documentTotals": {
            "taxExclusiveAmount": invoice.get("subtotal_aed"),
            "taxAmount": invoice.get("vat_amount_aed"),
            "taxInclusiveAmount": invoice.get("total_aed"),
            "deliveryFee": invoice.get("delivery_fee_aed"),
        },
        "labels": {
            "en": invoice.get("labels_en") or {},
            "ar": invoice.get("labels_ar") or {},
        },
    }
