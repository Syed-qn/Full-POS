from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_UAE_VAT_RATE = Decimal("0.0500")


def apply_vat(order, vat_rate: Decimal = DEFAULT_UAE_VAT_RATE) -> None:
    """Snapshot the VAT rate + amount onto the order at confirm time."""
    order.vat_rate = vat_rate
    order.vat_amount_aed = (order.subtotal * vat_rate).quantize(Decimal("0.01"))


async def build_tax_invoice(session: AsyncSession, *, order_id: int, restaurant_id: int) -> dict:
    from app.identity.models import Restaurant
    from app.ordering.models import Order, OrderItem
    from app.ordering.receipt_i18n import bilingual_labels

    order = await session.get(Order, order_id)
    if order is None or order.restaurant_id != restaurant_id:
        raise ValueError(f"order {order_id} not found")
    restaurant = await session.get(Restaurant, restaurant_id)
    items = (await session.scalars(
        select(OrderItem).where(OrderItem.order_id == order_id)
    )).all()

    return {
        "restaurant_name": restaurant.name,
        "trn": restaurant.settings.get("trn"),
        "invoice_number": order.order_number,
        "line_items": [
            {
                "dish_name": item.dish_name,
                "qty": item.qty,
                "price_aed": str(item.price_aed),
                "line_total_aed": str(item.price_aed * item.qty),
            }
            for item in items
        ],
        "subtotal_aed": str(order.subtotal),
        "delivery_fee_aed": str(order.delivery_fee_aed),
        "vat_rate": str(order.vat_rate),
        "vat_amount_aed": str(order.vat_amount_aed),
        "total_aed": str(order.total),
        # Fixed structural labels only (English is implicit in the field names
        # above) — dynamic data such as dish_name/restaurant_name is never
        # translated here, see receipt_i18n module docstring.
        "labels_ar": bilingual_labels()["ar"],
    }
