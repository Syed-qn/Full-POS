from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    owner_email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))


class StockTransfer(Base, TimestampMixin):
    """A stock movement between two branches (Restaurant rows) of the same org.

    Branches are separate `Restaurant` rows, so we link by restaurant id
    directly (from_restaurant_id / to_restaurant_id) rather than by a
    branch id — there is no separate "branch" table, each branch IS a
    Restaurant per the existing multi-branch design (see
    app.organizations.service.add_branch).
    """

    __tablename__ = "stock_transfers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    from_restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    to_restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    # pending | completed — completion is what actually moves stock (see
    # stock_transfer.complete_stock_transfer); creation only records intent.
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)


class StockTransferLine(Base, TimestampMixin):
    """One ingredient quantity on a StockTransfer.

    Ingredients are restaurant-scoped (app.inventory.models.Ingredient has
    its own restaurant_id and its own primary key per branch) — the source
    branch's "Tomatoes" and the destination branch's "Tomatoes" are two
    distinct DB rows with two distinct ids. There is no shared catalog
    table linking them. So a transfer line CANNOT reference a single
    ingredient_id that means the same thing on both sides; instead it
    records the ingredient_name (matched case-sensitively at completion
    time against each branch's own Ingredient.name) plus the unit and
    quantity to move. If the destination branch has no ingredient row
    with that name yet, completion creates one.
    """

    __tablename__ = "stock_transfer_lines"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    transfer_id: Mapped[int] = mapped_column(ForeignKey("stock_transfers.id"), index=True)
    ingredient_name: Mapped[str] = mapped_column(String(128))
    unit: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 3))
