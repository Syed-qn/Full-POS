"""Pydantic I/O schemas for the predictions REST API."""
from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class ForecastRequest(BaseModel):
    horizon: str = Field(..., pattern=r"^(breakfast|lunch|dinner|midnight|next_1h)$")
    on_date: date | None = None  # defaults to today in service


class PrepAheadResponse(BaseModel):
    dish_id: int
    dish_name: str
    predicted_qty: float
    confidence: str


class ForecastResponse(BaseModel):
    run_id: int
    horizon: str
    target_date: date
    predictions: dict[str, Any]
    adjusted: bool


class OverrideRequest(BaseModel):
    raw_text: str = Field(..., min_length=5, max_length=500)
    active_from: str | None = None  # ISO datetime; defaults to now
    active_to: str | None = None    # ISO datetime; defaults to +7 days


class OverrideResponse(BaseModel):
    id: int
    text: str
    parsed_effect: dict
