from app.dispatch.models import Assignment, Batch, BatchOrder, RiderLocation
from app.dispatch.scoring import RiderCandidate, rank_riders, score_rider


def test_batch_model_importable():
    assert Batch.__tablename__ == "batches"


def test_batch_order_model_importable():
    assert BatchOrder.__tablename__ == "batch_orders"


def test_rider_location_model_importable():
    assert RiderLocation.__tablename__ == "rider_locations"


def test_assignment_model_importable():
    assert Assignment.__tablename__ == "assignments"


def test_score_rider_closer_is_better():
    near = RiderCandidate(rider_id=1, distance_km=1.0, active_orders=0, on_time_pct=100.0)
    far = RiderCandidate(rider_id=2, distance_km=8.0, active_orders=0, on_time_pct=100.0)
    assert score_rider(near).composite < score_rider(far).composite


def test_score_rider_workload_penalty():
    idle = RiderCandidate(rider_id=1, distance_km=2.0, active_orders=0, on_time_pct=100.0)
    busy = RiderCandidate(rider_id=2, distance_km=2.0, active_orders=3, on_time_pct=100.0)
    assert score_rider(idle).composite < score_rider(busy).composite


def test_score_rider_on_time_reward():
    reliable = RiderCandidate(rider_id=1, distance_km=2.0, active_orders=1, on_time_pct=98.0)
    flaky = RiderCandidate(rider_id=2, distance_km=2.0, active_orders=1, on_time_pct=60.0)
    assert score_rider(reliable).composite < score_rider(flaky).composite


def test_score_returns_explainability_payload():
    s = score_rider(RiderCandidate(rider_id=1, distance_km=2.0, active_orders=1, on_time_pct=90.0))
    assert set(s.breakdown) >= {"distance_km", "workload_score", "on_time_pct", "composite"}


def test_rank_riders_orders_best_first():
    cands = [
        RiderCandidate(rider_id=1, distance_km=9.0, active_orders=2, on_time_pct=70.0),
        RiderCandidate(rider_id=2, distance_km=1.0, active_orders=0, on_time_pct=99.0),
    ]
    ranked = rank_riders(cands)
    assert ranked[0].rider_id == 2


def test_rank_riders_empty_returns_empty():
    assert rank_riders([]) == []
