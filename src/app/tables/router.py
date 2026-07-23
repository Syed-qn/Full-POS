from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.db import get_session
from app.identity.deps import current_restaurant
from app.staff.deps import current_restaurant_any, require_role
from app.tables.models import DiningTable
from app.tables.schemas import (
    FloorLayoutIn,
    FloorLayoutOut,
    StatusIn,
    TableIn,
    TableOut,
    TablePositionIn,
    TableUpdateIn,
    TransferIn,
)
from app.tables.service import (
    DuplicateTableLabelError,
    InvalidTableTransitionError,
    TableInUseError,
    TableNotFoundError,
    archive_table,
    assert_label_free,
    transfer_order,
    transition_status,
    update_table,
    update_table_position,
)

router = APIRouter(prefix="/api/v1/tables", tags=["tables"])


@router.post("", response_model=TableOut, status_code=status.HTTP_201_CREATED)
async def create_table(
    body: TableIn,
    # Floor layout is a manager decision; waiters/cashiers read it only.
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    try:
        await assert_label_free(session, restaurant_id=restaurant.id, label=body.label)
    except DuplicateTableLabelError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    payload = body.model_dump()
    payload["label"] = payload["label"].strip()
    table = DiningTable(restaurant_id=restaurant.id, **payload)
    session.add(table)
    await session.flush()
    await record_audit(
        session, actor="manager", entity="table", entity_id=str(table.id),
        action="table_created", restaurant_id=restaurant.id,
        before=None, after={"label": table.label, "seats": table.seats},
    )
    await session.commit()
    await session.refresh(table)
    return table


@router.patch("/{table_id}", response_model=TableOut)
async def edit_table(
    table_id: int,
    body: TableUpdateIn,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    """Rename / re-seat / re-place a table from the manager floor editor."""
    before = await session.get(DiningTable, table_id)
    snapshot = (
        {"label": before.label, "seats": before.seats, "pos_x": before.pos_x, "pos_y": before.pos_y}
        if before
        else None
    )
    try:
        table = await update_table(
            session,
            restaurant_id=restaurant.id,
            table_id=table_id,
            **body.model_dump(exclude_unset=True),
        )
    except TableNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DuplicateTableLabelError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await record_audit(
        session, actor="manager", entity="table", entity_id=str(table.id),
        action="table_updated", restaurant_id=restaurant.id,
        before=snapshot,
        after={"label": table.label, "seats": table.seats, "pos_x": table.pos_x, "pos_y": table.pos_y},
    )
    await session.commit()
    await session.refresh(table)
    return table


@router.delete("/{table_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_table(
    table_id: int,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    """Remove a table from the floor. Archives rather than hard-deletes so past
    orders keep pointing at the table they were served on."""
    try:
        table = await archive_table(session, restaurant_id=restaurant.id, table_id=table_id)
    except TableNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TableInUseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await record_audit(
        session, actor="manager", entity="table", entity_id=str(table.id),
        action="table_archived", restaurant_id=restaurant.id,
        before={"label": table.label}, after=None,
    )
    await session.commit()
    return None


@router.get("/layout", response_model=FloorLayoutOut)
async def get_floor_layout(
    # Every floor surface (manager, waiter, cashier) draws the same entrance.
    restaurant=Depends(current_restaurant_any),
):
    layout = (restaurant.settings or {}).get("floor_layout") or {}
    return FloorLayoutOut(
        entrance_x=layout.get("entrance_x"),
        entrance_y=layout.get("entrance_y"),
        entrance_rot=layout.get("entrance_rot") or 0.0,
    )


@router.put("/layout", response_model=FloorLayoutOut)
async def set_floor_layout(
    body: FloorLayoutIn,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    from sqlalchemy.orm.attributes import flag_modified

    settings = dict(restaurant.settings or {})
    before = settings.get("floor_layout")
    settings["floor_layout"] = {
        "entrance_x": body.entrance_x,
        "entrance_y": body.entrance_y,
        "entrance_rot": body.entrance_rot % 360,
    }
    restaurant.settings = settings
    flag_modified(restaurant, "settings")
    await record_audit(
        session, actor="manager", entity="restaurant", entity_id=str(restaurant.id),
        action="floor_layout_updated", restaurant_id=restaurant.id,
        before=before, after=settings["floor_layout"],
    )
    await session.commit()
    return FloorLayoutOut(**settings["floor_layout"])


@router.get("", response_model=list[TableOut])
async def list_tables(
    restaurant=Depends(current_restaurant_any),
    session: AsyncSession = Depends(get_session),
):
    """Live floor: each table plus its open order (if any) so the floor plan
    reflects real dine-in state — ordered/needs-bill, running bill, and waiter."""
    from app.ordering.models import Order
    from app.ordering.order_types import OPEN_ORDER_STATUSES
    from app.staff.models import StaffMember

    tables = list(
        await session.scalars(
            select(DiningTable)
            .where(
                DiningTable.restaurant_id == restaurant.id,
                DiningTable.archived_at.is_(None),
            )
            .order_by(DiningTable.label)
        )
    )
    table_ids = [t.id for t in tables]

    # Most-recent open order per table (created_at desc -> setdefault keeps newest).
    open_by_table: dict[int, Order] = {}
    if table_ids:
        orders = await session.scalars(
            select(Order)
            .where(
                Order.restaurant_id == restaurant.id,
                Order.table_id.in_(table_ids),
                Order.status.in_(OPEN_ORDER_STATUSES),
            )
            .order_by(Order.created_at.desc())
        )
        for o in orders:
            if o.table_id is not None:
                open_by_table.setdefault(o.table_id, o)

    staff_ids = {o.staff_id for o in open_by_table.values() if o.staff_id}
    staff_names: dict[int, str] = {}
    if staff_ids:
        for sm in await session.scalars(
            select(StaffMember).where(StaffMember.id.in_(staff_ids))
        ):
            staff_names[sm.id] = sm.name

    # How many other tables' bills were merged into each open order (for undo-merge).
    from app.ordering.models import OrderItem

    merged_counts: dict[int, int] = {}
    open_order_ids = [o.id for o in open_by_table.values()]
    if open_order_ids:
        rows = await session.execute(
            select(
                OrderItem.order_id,
                func.count(distinct(OrderItem.merged_from_order_id)),
            )
            .where(
                OrderItem.order_id.in_(open_order_ids),
                OrderItem.merged_from_order_id.isnot(None),
            )
            .group_by(OrderItem.order_id)
        )
        for oid, cnt in rows.all():
            merged_counts[oid] = cnt

    out: list[TableOut] = []
    for t in tables:
        order = open_by_table.get(t.id)
        if order is not None:
            # Dine-in is two-state: a table is free or occupied with an open tab.
            # Any open order → "ordered" (shown as "Occupied") until it's paid/closed,
            # EXCEPT once the waiter requests the bill: surface "needs_bill" so the
            # cashier floor can pull that table forward to collect payment.
            display_status = "needs_bill" if t.status == "needs_bill" else "ordered"
            out.append(
                TableOut(
                    id=t.id,
                    label=t.label,
                    seats=t.seats,
                    pos_x=t.pos_x,
                    pos_y=t.pos_y,
                    rotation=t.rotation or 0.0,
                    status=display_status,
                    qr_token=t.qr_token,
                    order_id=order.id,
                    order_total_aed=str(order.total),
                    waiter=staff_names.get(order.staff_id) if order.staff_id else None,
                    guests=order.covers,
                    merged_count=merged_counts.get(order.id, 0),
                    seated_since=(
                        order.created_at.isoformat() if order.created_at else None
                    ),
                )
            )
        else:
            # No open order: "ordered"/"needs_bill" are order-driven and can't
            # persist once the order closed/cancelled — collapse to available.
            # Manual states (reserved, cleaning, seated) are preserved.
            base = TableOut.model_validate(t)
            if base.status in ("ordered", "needs_bill"):
                base.status = "available"
            out.append(base)
    return out


@router.patch("/{table_id}/status", response_model=TableOut)
async def update_table_status(
    table_id: int,
    body: StatusIn,
    # Floor staff flip seated/needs_bill/cleaning during service.
    restaurant=Depends(require_role("manager", "cashier", "waiter")),
    session: AsyncSession = Depends(get_session),
):
    before_table = await session.get(DiningTable, table_id)
    before_status = before_table.status if before_table else None
    try:
        table = await transition_status(
            session, table_id=table_id, restaurant_id=restaurant.id, to_status=body.status
        )
    except TableNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTableTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await record_audit(
        session, actor="manager", entity="table", entity_id=str(table.id),
        action="status_change", restaurant_id=restaurant.id,
        before={"status": before_status}, after={"status": table.status},
    )
    await session.commit()
    await session.refresh(table)
    return table


@router.patch("/{table_id}/position", response_model=TableOut)
async def update_table_position_endpoint(
    table_id: int,
    body: TablePositionIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        table = await update_table_position(
            session, restaurant_id=restaurant.id, table_id=table_id,
            pos_x=body.pos_x, pos_y=body.pos_y,
        )
    except TableNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(table)
    return table


@router.patch("/{table_id}/transfer-order")
async def transfer_order_to_table(
    table_id: int,
    body: TransferIn,
    restaurant=Depends(require_role("manager", "cashier", "waiter")),
    session: AsyncSession = Depends(get_session),
):
    try:
        order = await transfer_order(
            session, order_id=body.order_id, restaurant_id=restaurant.id, to_table_id=table_id,
        )
    except TableNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await record_audit(
        session, actor="manager", entity="order", entity_id=str(order.id),
        action="table_transfer", restaurant_id=restaurant.id,
        before=None, after={"table_id": table_id},
    )
    await session.commit()
    return {"order_id": order.id, "table_id": order.table_id}


@router.post("/{table_id}/qr-token")
async def issue_table_qr_token(
    table_id: int,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """Issue (or return existing) QR token for tableside/QR ordering."""
    from app.ordering.qr_orders import ensure_table_qr_token

    try:
        table = await ensure_table_qr_token(
            session, restaurant_id=restaurant.id, table_id=table_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return {
        "table_id": table.id,
        "label": table.label,
        "qr_token": table.qr_token,
        "order_path": f"/api/v1/public/qr/{table.qr_token}/orders",
    }


@router.post("/{table_id}/tableside-order")
async def tableside_order_endpoint(
    table_id: int,
    body: dict,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """Waiter tableside order entry for a physical table."""
    from app.ordering.qr_orders import create_tableside_order
    from app.ordering.router import _enrich

    try:
        order = await create_tableside_order(
            session,
            restaurant_id=restaurant.id,
            table_id=table_id,
            staff_id=body.get("staff_id"),
            customer_phone=body["customer_phone"],
            customer_name=body.get("customer_name"),
            items=body.get("items") or [],
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return await _enrich(session, order)
