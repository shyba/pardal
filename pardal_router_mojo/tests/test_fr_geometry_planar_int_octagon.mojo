from testing.suite import TestSuite
from testing import assert_true, assert_equal

from pardal_router_mojo.fr.geometry.planar.int_octagon import IntOctagon
from pardal_router_mojo.fr.geometry.planar.float_point import FloatPoint
from pardal_router_mojo.fr.geometry.planar.side import Side


def test_int_octagon_normalize_empty_when_invalid():
    o = IntOctagon(10, 0, 0, 10, 0, 0, 0, 0)  # leftX > rightX
    n = o.normalize()
    assert_true(n.is_empty())


def test_int_octagon_contains_smoke():
    # Build a simple axis-aligned box-like octagon.
    o = IntOctagon(0, 10, 0, 10, -10, 10, 0, 20).normalize()
    assert_true(o.contains(FloatPoint(5.0, 5.0)))
    assert_true(not o.contains(FloatPoint(-1.0, 5.0)))


def test_int_octagon_corners_smoke():
    o = IntOctagon(0, 10, 0, 10, -10, 10, 0, 20).normalize()
    c0 = o.corner(0)
    c4 = o.corner(4)
    assert_equal(c0.y, o.bottomY)
    assert_equal(c4.y, o.topY)


def test_int_octagon_intersects_overlaps_and_side_of_border_line():
    a = IntOctagon(0, 10, 0, 10, -10, 10, 0, 20).normalize()
    b = IntOctagon(10, 20, 0, 10, 0, 20, 10, 30).normalize()
    assert_true(a.intersects(b))  # touching at x=10
    assert_true(not a.overlaps(b))
    c = IntOctagon(5, 15, 0, 10, -5, 15, 5, 25).normalize()
    assert_true(a.overlaps(c))
    isect = a.intersection(c)
    assert_true(not isect.is_empty())
    assert_true(isect.is_contained_in(a))
    # Border line 0 is bottom boundary: point below is ON_THE_RIGHT (inside is ON_THE_LEFT).
    s0 = a.side_of_border_line(0, -1, 0)
    assert_equal(s0._value, Side.on_the_right()._value)


def main():
    TestSuite.discover_tests[__functions_in_module()]().run()
