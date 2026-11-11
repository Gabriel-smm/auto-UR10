"""grip_width.py: width <-> pos through the calibration points."""

from grip_width import CALIBRATION, pos_for, width_for


def test_calibration_points():
    for width, pos in CALIBRATION:
        assert pos_for(width) == pos
        assert width_for(pos) == width


def test_round_trip_and_clamp():
    for width in (10, 20, 40, 60, 80):
        assert abs(width_for(pos_for(width)) - width) < 0.5
    assert pos_for(200) == 3 and pos_for(-5) == 228
    assert width_for(255) == 0.0 and width_for(0) == 85.0
