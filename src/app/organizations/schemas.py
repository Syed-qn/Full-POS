from decimal import Decimal

from pydantic import BaseModel


class OrgSignupIn(BaseModel):
    name: str
    owner_email: str
    password: str


class OrgLoginIn(BaseModel):
    owner_email: str
    password: str


class BranchIn(BaseModel):
    name: str
    lat: float
    lng: float


class StockTransferLineIn(BaseModel):
    ingredient_name: str
    unit: str
    quantity: Decimal


class StockTransferIn(BaseModel):
    from_restaurant_id: int
    to_restaurant_id: int
    lines: list[StockTransferLineIn]
