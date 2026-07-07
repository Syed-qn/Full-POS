from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ReferralCodeOut(BaseModel):
    customer_id: int
    code: str


class ReferralRedeemIn(BaseModel):
    code: str = Field(min_length=1)
    new_customer_id: int


class ReferralRedeemOut(BaseModel):
    referrer_customer_id: int
    new_customer_id: int
    bonus_aed: Decimal


class NpsResponseIn(BaseModel):
    customer_id: int
    score: int = Field(ge=0, le=10)
    comment: str | None = None


class NpsResponseOut(BaseModel):
    id: int
    order_id: int
    customer_id: int
    score: int
    comment: str | None
    created_at: datetime


class NpsSummaryOut(BaseModel):
    nps_score: float
    promoters: int
    passives: int
    detractors: int
    total_responses: int
