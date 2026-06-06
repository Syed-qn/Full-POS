from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SignupIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: str = Field(min_length=7, max_length=32)
    password: str = Field(min_length=8)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class LoginIn(BaseModel):
    phone: str = Field(min_length=7, max_length=32)
    password: str = Field(min_length=1)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RestaurantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone: str
    lat: float
    lng: float
    settings: dict


class RiderIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: str = Field(min_length=7, max_length=32)


class RiderPatch(BaseModel):
    status: Literal["available", "on_delivery", "off_shift", "deactivated"]


class RiderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone: str
    status: str


class SettingsPatch(BaseModel):
    max_orders_per_batch: int | None = Field(default=None, ge=1, le=6)
    max_items_per_order: int | None = Field(default=None, ge=1, le=100)
    delivery_fee_tiers: list[dict] | None = None
