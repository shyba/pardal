from testing.suite import TestSuite
from testing import assert_equal, assert_true

from pardal_router_mojo.fr.geometry.planar.float_point import FloatPoint
from pardal_router_mojo.fr.geometry.planar.int_direction import IntDirection

def test_float_point_distance_and_round():
    a = FloatPoint(0.0, 0.0)
    b = FloatPoint(3.0, 4.0)
    assert_equal(b.size(), 5.0)
    assert_equal(a.distance(b), 5.0)
    r = FloatPoint(1.2, 3.8).round()
    assert_equal(r.x, 1)
    assert_equal(r.y, 4)

def test_float_point_round_left_right_smoke():
    p = FloatPoint(1.2, 3.8)
    d = IntDirection(1, 0)
    _ = p.round_to_the_left(d)
    _ = p.round_to_the_right(d)
    assert_true(True)

def main():
    TestSuite.discover_tests[__functions_in_module()]().run()

