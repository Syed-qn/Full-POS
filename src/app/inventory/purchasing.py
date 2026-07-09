from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.inventory.models import (
    GoodsReceivedLine,
    GoodsReceivedNote,
    Ingredient,
    PurchaseOrder,
    PurchaseOrderLine,
    Vendor,
)
from app.inventory.service import add_batch


async def create_vendor(
    session: AsyncSession,
    *,
    restaurant_id: int,
    name: str,
    phone: str | None = None,
    email: str | None = None,
    notes: str | None = None,
) -> Vendor:
    vendor = Vendor(
        restaurant_id=restaurant_id, name=name, phone=phone, email=email, notes=notes
    )
    session.add(vendor)
    await session.flush()
    return vendor


async def list_vendors(
    session: AsyncSession, *, restaurant_id: int, active_only: bool = True
) -> list[Vendor]:
    q = select(Vendor).where(Vendor.restaurant_id == restaurant_id)
    if active_only:
        q = q.where(Vendor.is_active.is_(True))
    return list((await session.scalars(q.order_by(Vendor.name))).all())


async def update_vendor(
    session: AsyncSession,
    *,
    restaurant_id: int,
    vendor_id: int,
    name: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    notes: str | None = None,
    is_active: bool | None = None,
) -> Vendor:
    vendor = await session.get(Vendor, vendor_id)
    if vendor is None or vendor.restaurant_id != restaurant_id:
        raise ValueError("vendor not found")
    if name is not None:
        vendor.name = name
    if phone is not None:
        vendor.phone = phone
    if email is not None:
        vendor.email = email
    if notes is not None:
        vendor.notes = notes
    if is_active is not None:
        vendor.is_active = is_active
    await session.flush()
    return vendor


async def create_purchase_order(
    session: AsyncSession,
    *,
    restaurant_id: int,
    vendor_id: int,
    lines: list[dict],
    notes: str | None = None,
) -> PurchaseOrder:
    vendor = await session.get(Vendor, vendor_id)
    if vendor is None or vendor.restaurant_id != restaurant_id:
        raise ValueError("vendor not found")
    po = PurchaseOrder(
        restaurant_id=restaurant_id, vendor_id=vendor_id, status="draft", notes=notes
    )
    session.add(po)
    await session.flush()

    for line in lines:
        session.add(
            PurchaseOrderLine(
                po_id=po.id,
                ingredient_id=line["ingredient_id"],
                qty_ordered=Decimal(str(line["qty_ordered"])),
                unit_cost_aed=Decimal(str(line["unit_cost_aed"])),
                qty_received=Decimal("0"),
            )
        )
    await session.flush()
    return po


async def list_purchase_orders(
    session: AsyncSession, *, restaurant_id: int, status: str | None = None
) -> list[PurchaseOrder]:
    q = select(PurchaseOrder).where(PurchaseOrder.restaurant_id == restaurant_id)
    if status:
        q = q.where(PurchaseOrder.status == status)
    return list((await session.scalars(q.order_by(PurchaseOrder.id.desc()))).all())


async def receive_purchase_order(
    session: AsyncSession, *, restaurant_id: int, po_id: int,
) -> PurchaseOrder:
    """Full receive (legacy): receive all remaining qty on every line."""
    po = await session.get(PurchaseOrder, po_id)
    if po is None or po.restaurant_id != restaurant_id:
        raise ValueError("purchase order not found")

    lines = (
        await session.scalars(
            select(PurchaseOrderLine).where(PurchaseOrderLine.po_id == po.id)
        )
    ).all()
    receive_lines = []
    for line in lines:
        remaining = line.qty_ordered - (line.qty_received or Decimal("0"))
        if remaining > 0:
            receive_lines.append(
                {
                    "po_line_id": line.id,
                    "qty_received": remaining,
                    "unit_cost_aed": line.unit_cost_aed,
                    "expiry_date": None,
                }
            )
    if receive_lines:
        await create_grn(
            session,
            restaurant_id=restaurant_id,
            po_id=po_id,
            lines=receive_lines,
            received_by="manager",
        )
    else:
        po.status = "received"
        await session.flush()
    return po


async def create_grn(
    session: AsyncSession,
    *,
    restaurant_id: int,
    po_id: int,
    lines: list[dict],
    received_by: str = "manager",
    notes: str | None = None,
) -> GoodsReceivedNote:
    """Partial or full GRN against a PO. Updates stock, batches, costs, PO status."""
    po = await session.get(PurchaseOrder, po_id)
    if po is None or po.restaurant_id != restaurant_id:
        raise ValueError("purchase order not found")
    if po.status == "cancelled":
        raise ValueError("cannot receive a cancelled PO")

    # Sequential GRN number
    count = len(
        (
            await session.scalars(
                select(GoodsReceivedNote).where(
                    GoodsReceivedNote.restaurant_id == restaurant_id
                )
            )
        ).all()
    )
    grn_number = f"GRN-{restaurant_id}-{count + 1:04d}"
    grn = GoodsReceivedNote(
        restaurant_id=restaurant_id,
        po_id=po.id,
        grn_number=grn_number,
        received_by=received_by,
        notes=notes,
    )
    session.add(grn)
    await session.flush()

    for raw in lines:
        po_line = await session.get(PurchaseOrderLine, raw["po_line_id"])
        if po_line is None or po_line.po_id != po.id:
            raise ValueError(f"po_line {raw['po_line_id']} not found on PO")
        qty = Decimal(str(raw["qty_received"]))
        if qty <= 0:
            continue
        already = po_line.qty_received or Decimal("0")
        if already + qty > po_line.qty_ordered:
            raise ValueError(
                f"cannot receive {qty}: only {po_line.qty_ordered - already} remaining "
                f"on line {po_line.id}"
            )
        unit_cost = Decimal(str(raw.get("unit_cost_aed") or po_line.unit_cost_aed))
        expiry = raw.get("expiry_date")
        if isinstance(expiry, str):
            expiry = date.fromisoformat(expiry)

        session.add(
            GoodsReceivedLine(
                grn_id=grn.id,
                po_line_id=po_line.id,
                ingredient_id=po_line.ingredient_id,
                qty_received=qty,
                unit_cost_aed=unit_cost,
                expiry_date=expiry,
            )
        )
        po_line.qty_received = already + qty

        ingredient = await session.get(Ingredient, po_line.ingredient_id)
        if ingredient is not None:
            ingredient.current_stock += qty
            ingredient.cost_per_unit_aed = unit_cost  # latest cost tracking
            if expiry:
                await add_batch(
                    session,
                    restaurant_id=restaurant_id,
                    ingredient_id=ingredient.id,
                    qty=qty,
                    expiry_date=expiry,
                    update_stock=False,  # already updated current_stock
                )
            else:
                # Still track a batch without expiry (far future) for FEFO completeness
                await add_batch(
                    session,
                    restaurant_id=restaurant_id,
                    ingredient_id=ingredient.id,
                    qty=qty,
                    expiry_date=date(2099, 12, 31),
                    update_stock=False,
                )

    # Recompute PO status
    all_lines = (
        await session.scalars(
            select(PurchaseOrderLine).where(PurchaseOrderLine.po_id == po.id)
        )
    ).all()
    if all(line.qty_received >= line.qty_ordered for line in all_lines):
        po.status = "received"
    elif any((line.qty_received or 0) > 0 for line in all_lines):
        po.status = "partial"
    else:
        po.status = "ordered"
    await session.flush()
    return grn


async def list_grns(
    session: AsyncSession, *, restaurant_id: int, po_id: int | None = None
) -> list[GoodsReceivedNote]:
    q = select(GoodsReceivedNote).where(GoodsReceivedNote.restaurant_id == restaurant_id)
    if po_id is not None:
        q = q.where(GoodsReceivedNote.po_id == po_id)
    return list((await session.scalars(q.order_by(GoodsReceivedNote.id.desc()))).all())
