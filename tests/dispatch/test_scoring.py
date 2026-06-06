from app.dispatch.models import Assignment, Batch, BatchOrder, RiderLocation


def test_batch_model_importable():
    assert Batch.__tablename__ == "batches"


def test_batch_order_model_importable():
    assert BatchOrder.__tablename__ == "batch_orders"


def test_rider_location_model_importable():
    assert RiderLocation.__tablename__ == "rider_locations"


def test_assignment_model_importable():
    assert Assignment.__tablename__ == "assignments"
