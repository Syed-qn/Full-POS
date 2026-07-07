from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.inventory.models import Ingredient, PurchaseOrder, PurchaseOrderLine, Vendor


async def create_vendor(
    session: AsyncSession, *, restaurant_id: int, name: str,
    phone: str | None = None, email: str | None = None,
) -> Vendor:
    vendor = Vendor(restaurant_id=restaurant_id, name=name, phone=phone, email=email)
    session.add(vendor)
    await session.flush()
    return vendor


async def create_purchase_order(
    session: AsyncSession, *, restaurant_id: int, vendor_id: int, lines: list[dict],
) -> PurchaseOrder:
    po = PurchaseOrder(restaurant_id=restaurant_id, vendor_id=vendor_id, status="draft")
    session.add(po)
    await session.flush()

    for line in lines:
        session.add(PurchaseOrderLine(
            po_id=po.id,
            ingredient_id=line["ingredient_id"],
            qty_ordered=Decimal(str(line["qty_ordered"])),
            unit_cost_aed=Decimal(str(line["unit_cost_aed"])),
        ))
    await session.flush()
    return po


async def receive_purchase_order(
    session: AsyncSession, *, restaurant_id: int, po_id: int,
) -> PurchaseOrder:
    po = await session.get(PurchaseOrder, po_id)
    if po is None or po.restaurant_id != restaurant_id:
        raise ValueError("purchase order not found")

    lines = (await session.scalars(
        select(PurchaseOrderLine).where(PurchaseOrderLine.po_id == po.id)
    )).all()
    ingredient_ids = [line.ingredient_id for line in lines]
    ingredients = (await session.scalars(
        select(Ingredient).where(Ingredient.id.in_(ingredient_ids))
    )).all()
    ingredients_by_id = {i.id: i for i in ingredients}

    for line in lines:
        ingredient = ingredients_by_id.get(line.ingredient_id)
        if ingredient is not None:
            ingredient.current_stock += line.qty_ordered

    po.status = "received"
    await session.flush()
    return po
