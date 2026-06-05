from testing.suite import TestSuite
from testing import assert_equal

from pardal_router_mojo.fr.geometry.planar.int_direction import IntDirection
from pardal_router_mojo.fr.geometry.planar.int_point import IntPoint
from pardal_router_mojo.fr.geometry.planar.line import Line

def test_line_side_of_point():
    l = Line.from_points(IntPoint(0, 0), IntPoint(1, 0))
    assert_equal(l.side_of_point(IntPoint(0, 1)).to_string(), "on_the_left")
    assert_equal(l.side_of_point(IntPoint(0, -1)).to_string(), "on_the_right")
    assert_equal(l.side_of_point(IntPoint(10, 0)).to_string(), "collinear")

def test_line_intersection_fast_paths():
    vertical = Line.from_points(IntPoint(5, 0), IntPoint(5, 10))
    horizontal = Line.from_points(IntPoint(0, 7), IntPoint(10, 7))
    p = vertical.intersection(horizontal)
    assert_equal(p.x, 5)
    assert_equal(p.y, 7)

def test_line_from_point_dir():
    l = Line.from_point_dir(IntPoint(0, 0), IntDirection(1, 0))
    assert_equal(l.b.x, 1)
    assert_equal(l.b.y, 0)

def main():
    TestSuite.discover_tests[__functions_in_module()]().run()

