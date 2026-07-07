from pydantic import BaseModel, ConfigDict


class TableIn(BaseModel):
    label: str
    seats: int = 2
    pos_x: float = 0.0
    pos_y: float = 0.0


class TableOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    label: str
    seats: int
    pos_x: float
    pos_y: float
    status: str


class StatusIn(BaseModel):
    status: str


class TransferIn(BaseModel):
    order_id: int
