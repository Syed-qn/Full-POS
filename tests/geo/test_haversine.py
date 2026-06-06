from app.geo.haversine import distance_km


def test_same_point_is_zero():
    assert distance_km(25.2048, 55.2708, 25.2048, 55.2708) == 0.0


def test_known_distance_dubai_to_deira():
    # Dubai Mall area (~25.1972, 55.2796) to Deira (~25.2697, 55.3094) ≈ 8.5 km
    d = distance_km(25.1972, 55.2796, 25.2697, 55.3094)
    assert 7.5 < d < 9.5


def test_distance_is_symmetric():
    d1 = distance_km(25.2048, 55.2708, 25.1500, 55.2200)
    d2 = distance_km(25.1500, 55.2200, 25.2048, 55.2708)
    assert abs(d1 - d2) < 0.001


def test_distance_gt_10km():
    # Dubai to Abu Dhabi ≈ 130 km
    d = distance_km(25.2048, 55.2708, 24.4539, 54.3773)
    assert d > 10.0
