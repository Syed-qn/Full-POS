from pydantic import BaseModel, ConfigDict, Field


class TableIn(BaseModel):
    label: str = Field(min_length=1, max_length=32)
    seats: int = Field(default=2, ge=1, le=20)
    pos_x: float = 0.0
    pos_y: float = 0.0
    rotation: float = 0.0


class TableUpdateIn(BaseModel):
    """Manager floor-plan edit. Every field optional — a drag sends only the
    coordinates, the edit dialog sends only label/seats."""

    label: str | None = Field(default=None, min_length=1, max_length=32)
    seats: int | None = Field(default=None, ge=1, le=20)
    pos_x: float | None = None
    pos_y: float | None = None
    rotation: float | None = None


class FloorLayoutIn(BaseModel):
    """Where the room's entrance marker sits, in the same float grid units as
    table pos_x/pos_y, plus how it is turned. Restaurant-wide, stored in
    Restaurant.settings."""

    entrance_x: float
    entrance_y: float
    entrance_rot: float = 0.0


class FloorLayoutOut(BaseModel):
    entrance_x: float | None = None
    entrance_y: float | None = None
    entrance_rot: float = 0.0


class TableBillOut(BaseModel):
    """One open bill sitting on a table.

    A table can hold several at once — two parties sharing it, each paying for
    their own food — so the floor lists them rather than showing one and hiding
    the rest.
    """

    order_id: int
    order_number: str | None = None
    daily_token: int | None = None
    total_aed: str
    # A name a HUMAN gave this bill ("Ahmed"). Normally null: the number a cashier
    # reads is a position derived from this list, never a stored guess — a stamped
    # "Bill 2" collides between two splits and stays wrong once Bill 1 is paid.
    guest_label: str | None = None
    guests: int | None = None
    waiter: str | None = None
    seated_since: str | None = None


class TableOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    label: str
    seats: int
    pos_x: float
    pos_y: float
    rotation: float = 0.0
    # Live display status — derived from the table's open order when one exists
    # (ordered / needs_bill), else the table's own base status.
    status: str
    qr_token: str | None = None
    # Live dine-in enrichment: the NEWEST open order sitting on this table, if
    # any. Kept single-valued for every existing reader (KDS, Live Ops, the e2e
    # specs); a split table's full set is in `bills`.
    order_id: int | None = None
    order_total_aed: str | None = None
    # Every open bill on this table, OLDEST FIRST — so the floor can number them
    # by position and "Bill 1" is the party that sat down first. Empty when free.
    bills: list[TableBillOut] = []
    # len(bills) — so the floor can badge "2 bills" without walking the list.
    bill_count: int = 0
    # JOINED TABLES — one party, one invoice, several tables.
    # On a SECONDARY: the id/label of the table holding the invoice.
    merged_into_table_id: int | None = None
    merged_into_label: str | None = None
    # On a PRIMARY: the labels of the tables joined to it (empty otherwise).
    joined_labels: list[str] = []
    guests: int | None = None
    waiter: str | None = None
    # How many other tables' bills were merged into this table's order (>0 → can undo).
    merged_count: int = 0
    # ISO 8601 of when the open order started — drives the "seated for X min" timer.
    seated_since: str | None = None


class TablePositionIn(BaseModel):
    pos_x: float
    pos_y: float


class StatusIn(BaseModel):
    status: str


class TransferIn(BaseModel):
    order_id: int


class JoinTablesIn(BaseModel):
    """Tables to join onto the one named in the path, which holds the invoice."""

    table_ids: list[int] = Field(min_length=1)
    # WHICH of the primary's bills the joined tables share. Required only when the
    # primary carries more than one — with two parties at that table, guessing
    # would put the arriving guests' food on a stranger's bill.
    into_order_id: int | None = None
    # WHICH bill on a joining table comes along, when that table seats more than
    # one party. Only the named bill moves; the table keeps its independence
    # because the other party is still sitting on it.
    from_order_ids: list[int] | None = None
