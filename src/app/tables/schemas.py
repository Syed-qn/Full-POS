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
    # Live dine-in enrichment: the open order sitting on this table, if any.
    order_id: int | None = None
    order_total_aed: str | None = None
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
