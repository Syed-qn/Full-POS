from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import Restaurant
from app.inventory.models import Ingredient
from app.organizations.models import StockTransfer, StockTransferLine


async def create_stock_transfer(
    session: AsyncSession,
    *,
    org_id: int,
    from_restaurant_id: int,
    to_restaurant_id: int,
    lines: list[dict],
) -> StockTransfer:
    """Create a pending cross-branch stock transfer.

    Both restaurants must belong to `org_id` — a transfer can only move
    stock between branches of the SAME organization.
    """
    from_branch = await session.get(Restaurant, from_restaurant_id)
    to_branch = await session.get(Restaurant, to_restaurant_id)
    if from_branch is None or from_branch.organization_id != org_id:
        raise ValueError("from_restaurant_id does not belong to this organization")
    if to_branch is None or to_branch.organization_id != org_id:
        raise ValueError("to_restaurant_id does not belong to this organization")

    transfer = StockTransfer(
        organization_id=org_id,
        from_restaurant_id=from_restaurant_id,
        to_restaurant_id=to_restaurant_id,
        status="pending",
    )
    session.add(transfer)
    await session.flush()

    for line in lines:
        session.add(StockTransferLine(
            transfer_id=transfer.id,
            ingredient_name=line["ingredient_name"],
            unit=line["unit"],
            quantity=Decimal(str(line["quantity"])),
        ))
    await session.flush()
    return transfer


async def complete_stock_transfer(session: AsyncSession, *, transfer_id: int) -> StockTransfer:
    """Move stock from the source branch to the destination branch.

    Matched by ingredient NAME (see StockTransferLine docstring — ingredients
    are restaurant-scoped rows, so id matching across branches is not
    possible). Decrements the source ingredient's current_stock; increments
    the destination's matching ingredient (by name), creating it there if it
    doesn't exist yet.
    """
    transfer = await session.get(StockTransfer, transfer_id)
    if transfer is None:
        raise ValueError(f"stock transfer {transfer_id} not found")
    if transfer.status == "completed":
        return transfer

    lines = (await session.scalars(
        select(StockTransferLine).where(StockTransferLine.transfer_id == transfer_id)
    )).all()

    for line in lines:
        source_ing = await session.scalar(
            select(Ingredient).where(
                Ingredient.restaurant_id == transfer.from_restaurant_id,
                Ingredient.name == line.ingredient_name,
            )
        )
        if source_ing is None:
            raise ValueError(
                f"source branch has no ingredient named {line.ingredient_name!r}"
            )
        source_ing.current_stock -= line.quantity

        dest_ing = await session.scalar(
            select(Ingredient).where(
                Ingredient.restaurant_id == transfer.to_restaurant_id,
                Ingredient.name == line.ingredient_name,
            )
        )
        if dest_ing is None:
            dest_ing = Ingredient(
                restaurant_id=transfer.to_restaurant_id,
                name=line.ingredient_name,
                unit=line.unit,
                current_stock=Decimal("0.000"),
                low_stock_threshold=Decimal("0.000"),
            )
            session.add(dest_ing)
            await session.flush()
        dest_ing.current_stock += line.quantity

    transfer.status = "completed"
    await session.flush()
    return transfer
