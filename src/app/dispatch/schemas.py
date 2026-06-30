"""Dispatch API schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DispatchKpisOut(BaseModel):
    batch_rate_pct: float
    avg_stops: float
    engine_fallback_pct: float
    window: str = "today"


class LiveMapStopOut(BaseModel):
    order_id: int
    order_number: str
    sequence: int
    lat: float
    lng: float
    sla_deadline: str | None = None


class LiveMapBatchOut(BaseModel):
    batch_id: int
    rider_id: int
    rider_name: str | None = None
    status: str
    color: str
    stops: list[LiveMapStopOut]
    polyline: list[list[float]]
    total_est_min: int | None = None


class SlaRingOut(BaseModel):
    order_id: int
    order_number: str
    lat: float
    lng: float
    sla_deadline: str
    minutes_remaining: float
    urgency: str
    radius_km: float


class LiveOpsMapOut(BaseModel):
    origin: dict
    batches: list[LiveMapBatchOut] = Field(default_factory=list)
    sla_rings: list[SlaRingOut] = Field(default_factory=list)


class AssignmentExplainOut(BaseModel):
    """Explainability row for ``GET /api/v1/dispatch/assignments``."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    rider_id: int
    batch_id: int | None
    assigned_at: datetime
    algorithm_score: dict