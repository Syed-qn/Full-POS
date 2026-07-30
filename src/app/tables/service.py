from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ordering.models import Order
from app.tables.models import DiningTable

_TRANSITIONS: dict[str, set[str]] = {
    "available": {"seated"},
    "seated": {"ordered", "available"},
    "ordered": {"needs_bill", "available"},
    "needs_bill": {"cleaning"},
    "cleaning": {"available"},
}


def _announce(session: AsyncSession, restaurant_id: int, **fields) -> None:
    """Tell this branch's terminals the floor changed.

    Queued against the transaction, not sent now: these helpers flush but leave
    the commit to their caller, so pushing here would have other tills refetch
    the table before the new status is committed.
    """
    from app.realtime.hooks import queue_event

    queue_event(session, restaurant_id, "tables", **fields)


class TableNotFoundError(Exception):
    pass


class InvalidTableTransitionError(Exception):
    pass


class DuplicateTableLabelError(Exception):
    """Another live table on this floor already carries that label."""


class TableInUseError(Exception):
    """The table still has an open tab — it cannot be removed mid-service."""


async def _owned_table(
    session: AsyncSession, *, restaurant_id: int, table_id: int
) -> DiningTable:
    table = await session.get(DiningTable, table_id)
    if table is None or table.restaurant_id != restaurant_id or table.archived_at is not None:
        raise TableNotFoundError(f"table {table_id} not found")
    return table


async def assert_label_free(
    session: AsyncSession, *, restaurant_id: int, label: str, exclude_id: int | None = None
) -> None:
    """Labels are how staff call a table out loud — two T04s is an operational
    bug, not a cosmetic one. Enforced in the service (no DB constraint yet)."""
    stmt = select(func.count()).where(
        DiningTable.restaurant_id == restaurant_id,
        DiningTable.archived_at.is_(None),
        func.lower(DiningTable.label) == label.strip().lower(),
    )
    if exclude_id is not None:
        stmt = stmt.where(DiningTable.id != exclude_id)
    if (await session.scalar(stmt)) or 0:
        raise DuplicateTableLabelError(f"table {label} already exists")


async def update_table(
    session: AsyncSession,
    *,
    restaurant_id: int,
    table_id: int,
    label: str | None = None,
    seats: int | None = None,
    pos_x: float | None = None,
    pos_y: float | None = None,
    rotation: float | None = None,
) -> DiningTable:
    table = await _owned_table(session, restaurant_id=restaurant_id, table_id=table_id)
    if label is not None and label.strip() != table.label:
        await assert_label_free(
            session, restaurant_id=restaurant_id, label=label, exclude_id=table_id
        )
        table.label = label.strip()
    if seats is not None:
        table.seats = seats
    if pos_x is not None:
        table.pos_x = pos_x
    if pos_y is not None:
        table.pos_y = pos_y
    if rotation is not None:
        # Normalise to [0, 360) so repeated nudges never drift to 1080°.
        table.rotation = rotation % 360
    await session.flush()
    return table


async def archive_table(
    session: AsyncSession, *, restaurant_id: int, table_id: int
) -> DiningTable:
    """Soft delete — see DiningTable.archived_at. Refuses while a tab is open so
    a manager cannot make an unpaid order unreachable from the floor."""
    from app.ordering.order_types import OPEN_ORDER_STATUSES

    table = await _owned_table(session, restaurant_id=restaurant_id, table_id=table_id)
    open_count = await session.scalar(
        select(func.count()).where(
            Order.restaurant_id == restaurant_id,
            Order.table_id == table_id,
            Order.status.in_(OPEN_ORDER_STATUSES),
        )
    )
    if open_count:
        raise TableInUseError(f"table {table.label} still has an open order")
    table.archived_at = datetime.now(timezone.utc)
    await session.flush()
    return table


async def transition_status(
    session: AsyncSession, *, table_id: int, restaurant_id: int, to_status: str
) -> DiningTable:
    table = await session.get(DiningTable, table_id)
    if table is None or table.restaurant_id != restaurant_id:
        raise TableNotFoundError(f"table {table_id} not found")
    if to_status not in _TRANSITIONS.get(table.status, set()):
        raise InvalidTableTransitionError(f"cannot move table from {table.status} to {to_status}")
    table.status = to_status
    await session.flush()
    _announce(session, restaurant_id, table_id=table_id)
    return table


async def update_table_position(
    session: AsyncSession, *, restaurant_id: int, table_id: int, pos_x: float, pos_y: float
) -> DiningTable:
    table = await session.get(DiningTable, table_id)
    if table is None or table.restaurant_id != restaurant_id:
        raise TableNotFoundError(f"table {table_id} not found")
    table.pos_x = pos_x
    table.pos_y = pos_y
    await session.flush()
    _announce(session, restaurant_id, table_id=table_id)
    return table


async def transfer_order(
    session: AsyncSession, *, order_id: int, restaurant_id: int, to_table_id: int
) -> Order:
    order = await session.get(Order, order_id)
    if order is None or order.restaurant_id != restaurant_id:
        raise TableNotFoundError(f"order {order_id} not found")
    order.table_id = to_table_id
    await session.flush()
    return order


class TableJoinError(Exception):
    """The requested table join is not legal (self-join, cross-tenant, …)."""


async def group_bill_order_id_for(
    session: AsyncSession, *, table_id: int | None
) -> int | None:
    """The order a round rung up at this table belongs on, when the table is part
    of a join group. None when it is not joined, or the group has no bill yet.

    Without this, a joined table's round would fall to the generic "newest addable
    tab on the table" rule, which can be a DIFFERENT bill from the one the join
    folded into — a table with two parties would see merged food on one bill and
    new food on the other.
    """
    if table_id is None:
        return None
    table = await session.get(DiningTable, table_id)
    if table is None:
        return None
    primary = table
    if table.merged_into_table_id:
        primary = await session.get(DiningTable, table.merged_into_table_id) or table
    return primary.group_bill_order_id


async def resolve_bill_table_id(
    session: AsyncSession, *, table_id: int | None
) -> int | None:
    """Follow a joined table to the table that HOLDS THE BILL.

    A party spread across three tables is one invoice, so an order rung up while
    the waiter stands at a secondary table belongs on the primary's bill. One hop
    only, because join_tables never creates a chain.
    """
    if table_id is None:
        return None
    table = await session.get(DiningTable, table_id)
    if table is None:
        return table_id
    return table.merged_into_table_id or table.id


async def group_table_ids(
    session: AsyncSession, *, restaurant_id: int, primary_id: int
) -> list[int]:
    """Every table in a join group, primary first."""
    rows = (
        await session.scalars(
            select(DiningTable.id).where(
                DiningTable.restaurant_id == restaurant_id,
                DiningTable.merged_into_table_id == primary_id,
                DiningTable.archived_at.is_(None),
            )
        )
    ).all()
    return [primary_id, *sorted(rows)]


async def join_tables(
    session: AsyncSession,
    *,
    restaurant_id: int,
    primary_table_id: int,
    table_ids: list[int],
    into_order_id: int | None = None,
    actor: str = "manager",
) -> DiningTable:
    """Seat one party across several tables on a SINGLE invoice.

    Each secondary table is pointed at the primary and left OCCUPIED — the guests
    are still sitting there. Any open bill a secondary already carries is merged
    onto the primary's, so there is one invoice; where the secondary has no bill
    yet (the usual case, they have only just sat down) nothing needs merging and
    later rounds land on the primary through ``resolve_bill_table_id``.

    This is deliberately NOT ``merge_orders`` alone: that cancels the second bill
    and frees the second table at once, which is right only when guests physically
    move to one table.
    """
    from app.audit.service import record_audit
    from app.ordering.order_types import OPEN_ORDER_STATUSES
    from app.ordering.service import merge_orders

    primary = await _owned_table(
        session, restaurant_id=restaurant_id, table_id=primary_table_id
    )
    # Joining INTO a secondary is a request to join its group — resolve through
    # rather than refusing, so a waiter tapping any table of a group is right.
    if primary.merged_into_table_id:
        primary = await _owned_table(
            session,
            restaurant_id=restaurant_id,
            table_id=primary.merged_into_table_id,
        )

    wanted = [t for t in dict.fromkeys(table_ids) if t != primary.id]
    if not wanted:
        raise TableJoinError("pick at least one other table to join")

    async def _open_bills(table_id: int) -> list[Order]:
        return list(
            await session.scalars(
                select(Order).where(
                    Order.restaurant_id == restaurant_id,
                    Order.table_id == table_id,
                    Order.status.in_(sorted(OPEN_ORDER_STATUSES)),
                )
                .order_by(Order.created_at, Order.id)
            )
        )

    # WHICH of the primary's bills is the group invoice. A table can carry several
    # at once (two parties sharing it), so joining is ambiguous until somebody
    # says which party the arriving guests belong to — and guessing would put a
    # stranger's food on their bill. One bill needs no asking; none means the group
    # has not ordered yet and the first round will open it.
    existing = await _open_bills(primary.id)
    if into_order_id is not None:
        chosen = next((b for b in existing if b.id == into_order_id), None)
        if chosen is None:
            raise TableJoinError(
                f"bill {into_order_id} is not an open bill on table {primary.label}"
            )
        primary.group_bill_order_id = chosen.id
    elif len(existing) > 1:
        raise TableJoinError(
            f"table {primary.label} has {len(existing)} open bills — say which one "
            f"the joined tables share"
        )
    elif existing:
        primary.group_bill_order_id = existing[0].id

    def _target_bill_id() -> int | None:
        return primary.group_bill_order_id

    for tid in wanted:
        secondary = await _owned_table(
            session, restaurant_id=restaurant_id, table_id=tid
        )
        if secondary.merged_into_table_id == primary.id:
            continue  # already in this group — idempotent
        if secondary.merged_into_table_id:
            raise TableJoinError(
                f"table {secondary.label} is already joined to another table"
            )
        # A table that is itself a primary would create a chain; refuse rather
        # than silently re-parenting somebody else's group.
        if await session.scalar(
            select(func.count())
            .select_from(DiningTable)
            .where(DiningTable.merged_into_table_id == secondary.id)
        ):
            raise TableJoinError(
                f"table {secondary.label} already has tables joined to it"
            )

        secondary.merged_into_table_id = primary.id
        # Occupied, not free: guests are sitting there. "seated" when there is no
        # bill on the group yet, "ordered" once there is one.
        primary_bills = await _open_bills(primary.id)
        secondary.status = "ordered" if primary_bills else "seated"

        # One invoice: fold any bill the secondary already carries onto the group's
        # chosen bill. With no group bill yet, the secondary's own bill BECOMES it
        # — moving the order across rather than merging keeps its token and number,
        # so the party keeps the bill reference they were already given.
        for bill in await _open_bills(secondary.id):
            target_id = _target_bill_id()
            if target_id is not None and target_id != bill.id:
                await merge_orders(
                    session,
                    restaurant_id=restaurant_id,
                    primary_order_id=target_id,
                    secondary_order_id=bill.id,
                )
            else:
                bill.table_id = primary.id
                primary.group_bill_order_id = bill.id
                await session.flush()

    if primary.status in ("available", "cleaning", "needs_bill"):
        primary_bills = await _open_bills(primary.id)
        primary.status = "ordered" if primary_bills else "seated"

    await session.flush()
    await record_audit(
        session,
        actor=actor,
        restaurant_id=restaurant_id,
        entity="table",
        entity_id=str(primary.id),
        action="tables_joined",
        after={"primary": primary.label, "joined": wanted},
    )
    _announce(session, restaurant_id, table_id=primary.id)
    return primary


async def unjoin_table(
    session: AsyncSession,
    *,
    restaurant_id: int,
    table_id: int,
    actor: str = "manager",
) -> DiningTable:
    """Detach one table from its group. The invoice stays with the primary —
    splitting the food back out is a separate, explicit act (unmerge)."""
    from app.audit.service import record_audit

    table = await _owned_table(session, restaurant_id=restaurant_id, table_id=table_id)
    if not table.merged_into_table_id:
        raise TableJoinError(f"table {table.label} is not joined to another table")
    before = table.merged_into_table_id
    table.merged_into_table_id = None
    # Freed rather than left occupied: its food and its money are on the primary's
    # invoice, so there is nothing on this table left to pay for.
    table.status = "available"
    await session.flush()
    await record_audit(
        session,
        actor=actor,
        restaurant_id=restaurant_id,
        entity="table",
        entity_id=str(table.id),
        action="table_unjoined",
        before={"merged_into_table_id": before},
        after={"status": "available"},
    )
    _announce(session, restaurant_id, table_id=table.id)
    return table
