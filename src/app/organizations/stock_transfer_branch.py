"""Branch-manager stock transfers, in two phases.

The org-level create/complete pair in ``stock_transfer.py`` is HQ raising a
movement and applying it in one go. That is not how stock actually travels: it
leaves one branch, spends time in a van, and arrives at another. Recording both
ends at a single instant means the same kilos are either in both branches at
once or in neither, and neither branch's food cost is right.

So here a branch DISPATCHES (stock leaves, status ``in_transit``) and the
destination CONFIRMS what turned up (stock arrives, status ``completed``). Both
sides record the same product and quantity against one document, which is the
whole point of a transfer rather than two unrelated stock edits.

Matching is by ingredient NAME, following the original module: ingredients are
restaurant-scoped rows, so the same item has a different id in each branch.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import Restaurant
from app.inventory.models import Ingredient
from app.organizations.models import StockTransfer, StockTransferLine


async def _sibling_branch(
    session: AsyncSession, *, restaurant_id: int, other_id: int
) -> tuple[Restaurant, Restaurant]:
    """Both branches, proven to sit in the SAME organization.

    A transfer is the one operation that deliberately reaches outside the
    caller's own restaurant, so this is the check that stops it reaching into
    somebody else's business.
    """
    mine = await session.get(Restaurant, restaurant_id)
    other = await session.get(Restaurant, other_id)
    if mine is None or other is None:
        raise ValueError("branch not found")
    if mine.id == other.id:
        raise ValueError("cannot transfer to the same branch")
    if mine.organization_id is None or mine.organization_id != other.organization_id:
        raise ValueError("both branches must belong to the same organization")
    return mine, other


async def list_sibling_branches(
    session: AsyncSession, *, restaurant_id: int
) -> list[dict]:
    """The other branches this one may send stock to.

    ``/organizations/branches`` cannot serve this: it takes
    ``current_organization``, which 403s a branch manager by design. A manager
    still has to pick a destination, so they get the one fact they need — the
    names of their siblings — without HQ access.
    """
    mine = await session.get(Restaurant, restaurant_id)
    if mine is None or mine.organization_id is None:
        return []
    rows = (
        await session.scalars(
            select(Restaurant)
            .where(
                Restaurant.organization_id == mine.organization_id,
                Restaurant.id != mine.id,
            )
            .order_by(Restaurant.name)
        )
    ).all()
    return [{"id": b.id, "name": b.name} for b in rows]


async def dispatch_stock_transfer(
    session: AsyncSession,
    *,
    from_restaurant_id: int,
    to_restaurant_id: int,
    lines: list[dict],
    dispatched_by: str,
    note: str | None = None,
) -> StockTransfer:
    """Send stock out of ``from_restaurant_id``. Deducts immediately.

    Deducting at dispatch rather than on arrival is deliberate: once the van
    has gone, the food is not in the sending kitchen, and a branch that can
    still see it on screen will plan to cook with it.
    """
    if not lines:
        raise ValueError("a transfer needs at least one line")
    mine, other = await _sibling_branch(
        session, restaurant_id=from_restaurant_id, other_id=to_restaurant_id
    )

    transfer = StockTransfer(
        organization_id=mine.organization_id,
        from_restaurant_id=mine.id,
        to_restaurant_id=other.id,
        status="in_transit",
        dispatched_by=dispatched_by,
        note=note,
    )
    session.add(transfer)
    await session.flush()

    for line in lines:
        name = str(line["ingredient_name"]).strip()
        qty = Decimal(str(line["quantity"]))
        if qty <= 0:
            raise ValueError("transfer quantity must be greater than zero")
        source = await session.scalar(
            select(Ingredient).where(
                Ingredient.restaurant_id == mine.id,
                Ingredient.name == name,
            )
        )
        if source is None:
            raise ValueError(f"this branch has no ingredient named {name!r}")
        # You cannot send what you do not have. Allowing it would push the
        # sender negative and invent stock at the far end.
        if source.current_stock < qty:
            raise ValueError(
                f"only {source.current_stock} {source.unit} of {name} in stock"
            )
        source.current_stock -= qty
        session.add(
            StockTransferLine(
                transfer_id=transfer.id,
                ingredient_name=name,
                unit=line.get("unit") or source.unit,
                quantity=qty,
            )
        )
    await session.flush()
    return transfer


async def request_stock_transfer(
    session: AsyncSession,
    *,
    requesting_restaurant_id: int,
    from_restaurant_id: int,
    lines: list[dict],
    requested_by: str,
    note: str | None = None,
) -> StockTransfer:
    """Ask another branch to send you stock. Moves nothing.

    The full trade flow is request -> dispatch -> receive; this is the first
    leg, and it exists because the branch that RUNS OUT is the one that knows.
    Without it the holder has to guess, which in practice means a phone call
    that leaves no record of what was asked for or whether it was ever sent.

    Deliberately no stock effect: the holder has not agreed yet, and deducting
    on a request would let any branch empty another's store by asking.
    """
    if not lines:
        raise ValueError("a request needs at least one line")
    mine, holder = await _sibling_branch(
        session, restaurant_id=requesting_restaurant_id, other_id=from_restaurant_id
    )

    # from/to describe where the STOCK will travel, so a request is stored the
    # same way round as a dispatch: out of the holder, into the asker. Nothing
    # downstream has to special-case which end is which.
    transfer = StockTransfer(
        organization_id=mine.organization_id,
        from_restaurant_id=holder.id,
        to_restaurant_id=mine.id,
        status="pending",
        note=note,
    )
    session.add(transfer)
    await session.flush()

    for line in lines:
        name = str(line["ingredient_name"]).strip()
        qty = Decimal(str(line["quantity"]))
        if qty <= 0:
            raise ValueError("requested quantity must be greater than zero")
        # The unit comes from whichever branch knows the item. A request may
        # name something the asking branch has never stocked — that is often
        # exactly why they are asking.
        known = await session.scalar(
            select(Ingredient).where(
                Ingredient.restaurant_id.in_([mine.id, holder.id]),
                Ingredient.name == name,
            )
        )
        session.add(
            StockTransferLine(
                transfer_id=transfer.id,
                ingredient_name=name,
                unit=line.get("unit") or (known.unit if known else "unit"),
                qty_requested=qty,
                quantity=qty,
            )
        )
    await session.flush()
    return transfer


async def approve_stock_transfer(
    session: AsyncSession,
    *,
    transfer_id: int,
    from_restaurant_id: int,
    dispatched_by: str,
    quantities: dict[str, Decimal] | None = None,
) -> StockTransfer:
    """Agree to a request and send it. Only the branch being asked may do this.

    ``quantities`` sends less than was asked for — the ordinary case when you
    have some to spare but not all of it. The request stays on the line as
    ``qty_requested``, so "asked 10, sent 6" survives instead of the document
    claiming 6 was all anyone ever wanted.
    """
    transfer = await session.get(StockTransfer, transfer_id)
    if transfer is None:
        raise ValueError("stock transfer not found")
    if transfer.from_restaurant_id != from_restaurant_id:
        raise ValueError("only the branch being asked can approve this request")
    if transfer.status != "pending":
        raise ValueError(f"cannot approve a transfer that is {transfer.status}")

    lines = (
        await session.scalars(
            select(StockTransferLine).where(StockTransferLine.transfer_id == transfer.id)
        )
    ).all()

    sending = []
    for line in lines:
        asked = line.qty_requested if line.qty_requested is not None else line.quantity
        qty = Decimal(str((quantities or {}).get(line.ingredient_name, asked)))
        if qty < 0:
            raise ValueError("approved quantity cannot be negative")
        if qty > asked:
            raise ValueError(
                f"cannot send {qty} of {line.ingredient_name}: only {asked} was asked for"
            )
        line.quantity = qty
        if qty > 0:
            sending.append(line)

    if not sending:
        raise ValueError("approving nothing is a decline — use decline instead")

    for line in sending:
        source = await session.scalar(
            select(Ingredient).where(
                Ingredient.restaurant_id == transfer.from_restaurant_id,
                Ingredient.name == line.ingredient_name,
            )
        )
        if source is None:
            raise ValueError(f"this branch has no ingredient named {line.ingredient_name!r}")
        if source.current_stock < line.quantity:
            raise ValueError(
                f"only {source.current_stock} {source.unit} of "
                f"{line.ingredient_name} in stock"
            )
        source.current_stock -= line.quantity

    transfer.status = "in_transit"
    transfer.dispatched_by = dispatched_by
    await session.flush()
    return transfer


async def decline_stock_transfer(
    session: AsyncSession,
    *,
    transfer_id: int,
    from_restaurant_id: int,
    reason: str | None = None,
) -> StockTransfer:
    """Turn a request down. Nothing has moved, so nothing is returned."""
    transfer = await session.get(StockTransfer, transfer_id)
    if transfer is None:
        raise ValueError("stock transfer not found")
    if transfer.from_restaurant_id != from_restaurant_id:
        raise ValueError("only the branch being asked can decline this request")
    if transfer.status != "pending":
        raise ValueError(f"cannot decline a transfer that is {transfer.status}")
    transfer.status = "cancelled"
    if reason:
        # A bare "cancelled" tells the asking branch nothing about whether to
        # ask again, ask elsewhere, or buy it in.
        transfer.note = f"Declined: {reason}" if not transfer.note else (
            f"{transfer.note} · Declined: {reason}"
        )
    await session.flush()
    return transfer


async def withdraw_stock_request(
    session: AsyncSession, *, transfer_id: int, requesting_restaurant_id: int
) -> StockTransfer:
    """Take back a request you raised, before the other branch acts on it."""
    transfer = await session.get(StockTransfer, transfer_id)
    if transfer is None:
        raise ValueError("stock transfer not found")
    if transfer.to_restaurant_id != requesting_restaurant_id:
        raise ValueError("only the branch that asked can withdraw this request")
    if transfer.status == "cancelled":
        return transfer
    if transfer.status != "pending":
        # Once it has been sent it is a delivery, not a request; taking it back
        # is the sender's cancel, which has stock to return.
        raise ValueError(f"cannot withdraw a transfer that is {transfer.status}")
    transfer.status = "cancelled"
    await session.flush()
    return transfer


async def receive_stock_transfer(
    session: AsyncSession,
    *,
    transfer_id: int,
    to_restaurant_id: int,
    received_by: str,
    received: dict[str, Decimal] | None = None,
) -> StockTransfer:
    """Confirm arrival at the destination branch. Adds what actually turned up.

    ``received`` maps ingredient name to the quantity actually counted in.
    Anything not listed is assumed to have arrived in full, so the ordinary
    case is one click. A short line leaves ``quantity`` and ``qty_received``
    different, and that difference IS the record of the discrepancy —
    rewriting ``quantity`` would erase the evidence that something went missing
    between the two branches.
    """
    transfer = await session.get(StockTransfer, transfer_id)
    if transfer is None:
        raise ValueError("stock transfer not found")
    # Only the branch it was sent TO may accept it. A sender confirming its own
    # delivery would defeat the entire control.
    if transfer.to_restaurant_id != to_restaurant_id:
        raise ValueError("only the destination branch can receive this transfer")
    if transfer.status == "completed":
        return transfer
    if transfer.status != "in_transit":
        raise ValueError(f"cannot receive a transfer that is {transfer.status}")

    lines = (
        await session.scalars(
            select(StockTransferLine).where(StockTransferLine.transfer_id == transfer.id)
        )
    ).all()

    for line in lines:
        arrived = (
            line.quantity
            if received is None
            else received.get(line.ingredient_name, line.quantity)
        )
        arrived = Decimal(str(arrived))
        if arrived < 0:
            raise ValueError("received quantity cannot be negative")
        if arrived > line.quantity:
            raise ValueError(
                f"cannot receive {arrived} of {line.ingredient_name}: only "
                f"{line.quantity} was sent"
            )
        line.qty_received = arrived
        if arrived == 0:
            continue

        dest = await session.scalar(
            select(Ingredient).where(
                Ingredient.restaurant_id == transfer.to_restaurant_id,
                Ingredient.name == line.ingredient_name,
            )
        )
        if dest is None:
            # A branch that does not stock this item yet gets it created rather
            # than the delivery being turned away at the door.
            dest = Ingredient(
                restaurant_id=transfer.to_restaurant_id,
                name=line.ingredient_name,
                unit=line.unit,
                current_stock=Decimal("0.000"),
                low_stock_threshold=Decimal("0.000"),
            )
            session.add(dest)
            await session.flush()
        dest.current_stock += arrived

    transfer.status = "completed"
    transfer.received_by = received_by
    await session.flush()
    return transfer


async def cancel_stock_transfer(
    session: AsyncSession, *, transfer_id: int, from_restaurant_id: int
) -> StockTransfer:
    """Call a dispatch back. Returns the stock to the sending branch.

    Only the sender, and only before the destination has accepted it — after
    that the stock belongs to the other branch and taking it back would
    silently overdraw their store.
    """
    transfer = await session.get(StockTransfer, transfer_id)
    if transfer is None:
        raise ValueError("stock transfer not found")
    if transfer.from_restaurant_id != from_restaurant_id:
        raise ValueError("only the sending branch can cancel this transfer")
    if transfer.status == "cancelled":
        return transfer
    if transfer.status != "in_transit":
        raise ValueError(f"cannot cancel a transfer that is {transfer.status}")

    lines = (
        await session.scalars(
            select(StockTransferLine).where(StockTransferLine.transfer_id == transfer.id)
        )
    ).all()
    for line in lines:
        source = await session.scalar(
            select(Ingredient).where(
                Ingredient.restaurant_id == transfer.from_restaurant_id,
                Ingredient.name == line.ingredient_name,
            )
        )
        if source is not None:
            source.current_stock += line.quantity

    transfer.status = "cancelled"
    await session.flush()
    return transfer


async def list_branch_transfers(
    session: AsyncSession, *, restaurant_id: int, limit: int = 50
) -> list[dict]:
    """Transfers this branch sent or is due to receive, newest first."""
    rows = (
        await session.scalars(
            select(StockTransfer)
            .where(
                (StockTransfer.from_restaurant_id == restaurant_id)
                | (StockTransfer.to_restaurant_id == restaurant_id)
            )
            .order_by(StockTransfer.id.desc())
            .limit(limit)
        )
    ).all()
    if not rows:
        return []

    line_rows = (
        await session.scalars(
            select(StockTransferLine).where(
                StockTransferLine.transfer_id.in_([r.id for r in rows])
            )
        )
    ).all()
    by_transfer: dict[int, list] = {}
    for line in line_rows:
        by_transfer.setdefault(line.transfer_id, []).append(line)

    branch_ids = {r.from_restaurant_id for r in rows} | {r.to_restaurant_id for r in rows}
    names = {
        b.id: b.name
        for b in (
            await session.scalars(select(Restaurant).where(Restaurant.id.in_(branch_ids)))
        ).all()
    }

    return [
        {
            "id": r.id,
            "status": r.status,
            "direction": "out" if r.from_restaurant_id == restaurant_id else "in",
            "from_restaurant_id": r.from_restaurant_id,
            "from_branch_name": names.get(r.from_restaurant_id, ""),
            "to_restaurant_id": r.to_restaurant_id,
            "to_branch_name": names.get(r.to_restaurant_id, ""),
            "dispatched_by": r.dispatched_by,
            "received_by": r.received_by,
            "note": r.note,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "lines": [
                {
                    "ingredient_name": line.ingredient_name,
                    "unit": line.unit,
                    "qty_requested": (
                        None if line.qty_requested is None else str(line.qty_requested)
                    ),
                    "quantity": str(line.quantity),
                    "qty_received": (
                        None if line.qty_received is None else str(line.qty_received)
                    ),
                }
                for line in by_transfer.get(r.id, [])
            ],
        }
        for r in rows
    ]
