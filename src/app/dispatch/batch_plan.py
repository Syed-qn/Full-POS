"""Shared batch planning for preview (dry) and dispatch (live)."""

from __future__ import annotations

from dataclasses import dataclass

from app.dispatch.batching import OrderCandidate, PlannedBatch, build_batches


@dataclass
class BatchPlanSettings:
    proximity_km: float = 1.5
    window_min: int = 10
    max_per_batch: int = 3
    buffer_per_order: int = 10
    max_detour_km: float = 0.0
    delivery_zones: list[dict] | None = None
    engine: str = "greedy"


def run_batch_plan(
    candidates: list[OrderCandidate],
    *,
    settings: BatchPlanSettings,
    geo_provider,
    origin: tuple[float, float] | None,
    dry_run: bool = True,
) -> list[PlannedBatch]:
    """Return planned batches using the same greedy rules as dispatch."""
    return build_batches(
        candidates,
        geo_provider=geo_provider,
        origin=origin,
        max_per_batch=settings.max_per_batch,
        proximity_km=settings.proximity_km,
        window_min=settings.window_min,
        buffer_per_order=settings.buffer_per_order,
        max_detour_km=settings.max_detour_km,
        delivery_zones=settings.delivery_zones,
    )


def labels_from_batches(batches: list[PlannedBatch]) -> dict[int, str]:
    """Map order_id -> preview label (A, B, …) for batches with 2+ orders."""
    labels: dict[int, str] = {}
    group_index = 0
    for batch in batches:
        if len(batch.orders) < 2:
            continue
        label = chr(ord("A") + group_index)
        group_index += 1
        for order in batch.orders:
            labels[order.order_id] = label
    return labels