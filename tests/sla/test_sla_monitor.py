from app.cod.models import CodCollection, RiderShiftReconciliation
from app.coupons.models import Coupon
from app.sla.models import SlaEvent


def test_sla_event_importable():
    assert SlaEvent.__tablename__ == "sla_events"


def test_coupon_importable():
    assert Coupon.__tablename__ == "coupons"


def test_cod_collection_importable():
    assert CodCollection.__tablename__ == "cod_collections"


def test_reconciliation_importable():
    assert RiderShiftReconciliation.__tablename__ == "rider_shift_reconciliations"
