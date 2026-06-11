from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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

    @field_validator("delivery_fee_tiers")
    @classmethod
    def _validate_tiers(cls, v: list[dict] | None) -> list[dict] | None:
        """Each tier needs a positive ascending ``max_km`` and a non-negative
        ``fee_aed`` — so the dynamic fee/radius config can't be saved broken."""
        if v is None:
            return v
        if not v:
            raise ValueError("delivery_fee_tiers must have at least one tier")
        prev_km = 0.0
        for tier in v:
            if not isinstance(tier, dict) or "max_km" not in tier or "fee_aed" not in tier:
                raise ValueError("each tier needs 'max_km' and 'fee_aed'")
            try:
                km = float(tier["max_km"])
                fee = float(tier["fee_aed"])
            except (TypeError, ValueError) as exc:
                raise ValueError("max_km and fee_aed must be numbers") from exc
            if km <= prev_km:
                raise ValueError("tiers must be ascending with positive max_km")
            if fee < 0:
                raise ValueError("fee_aed must be >= 0")
            prev_km = km
        return v


class ProfilePatch(BaseModel):
    name: str = Field(min_length=1, max_length=255)
