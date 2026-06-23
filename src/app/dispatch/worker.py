"""Periodic dispatch sweep (Celery beat).

Runs the dispatch engine for every restaurant that currently has ready, unassigned
orders. Two reasons this must be periodic rather than purely event-driven (the
``_auto_dispatch_on_ready`` hook that fires when a kitchen marks an order ready):

  1. Batch hold window — a freshly-ready lone order is intentionally HELD for up to
     ``batch_hold_seconds`` so a neighbour can join its batch. The sweep is what
     re-evaluates and releases it once the window matures (or a mate appears).
  2. No-rider retry — an order left ready because no rider was free would otherwise
     sit forever until some *other* order happened to become ready. The sweep retries
     it every tick (the no-rider manager alert is idempotency-bucketed to avoid spam).

Idempotent and best-effort: a failure for one restaurant never blocks the others.
"""
from __future__ import annotations

import asyncio

from celery import shared_task

from app.dispatch.service import sweep_ready_once


@shared_task(name="dispatch.sweep_ready", bind=True, max_retries=3, default_retry_delay=10)
def dispatch_sweep_ready(self) -> None:  # type: ignore[override]
    asyncio.run(sweep_ready_once())
