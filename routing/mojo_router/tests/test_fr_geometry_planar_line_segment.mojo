from testing.suite import TestSuite
from testing import assert_equal

from pardal_router_mojo.fr.geometry.planar.int_point import IntPoint
from pardal_router_mojo.fr.geometry.planar.line import Line
from pardal_router_mojo.fr.geometry.planar.line_segment import LineSegment

def test_line_segment_bounding_box_smoke():
    # Segment of a horizontal line between x=0 and x=10 at y=5
    start = Line.from_points(IntPoint(0, 5), IntPoint(0, 6))     # vertical at x=0
    middle = Line.from_points(IntPoint(0, 5), IntPoint(1, 5))    # horizontal y=5
    end = Line.from_points(IntPoint(10, 5), IntPoint(10, 6))     # vertical at x=10
    seg = LineSegment.from_lines(start, middle, end)
    bb = seg.bounding_box()
    assert_equal(bb.ll.x, 0)
    assert_equal(bb.ur.x, 10)
    assert_equal(bb.ll.y, 5)
    assert_equal(bb.ur.y, 5)

def test_line_segment_opposite_smoke():
    start = Line.from_points(IntPoint(0, 0), IntPoint(0, 1))
    middle = Line.from_points(IntPoint(0, 0), IntPoint(1, 0))
    end = Line.from_points(IntPoint(1, 0), IntPoint(1, 1))
    seg = LineSegment.from_lines(start, middle, end)
    opp = seg.opposite()
    bb = opp.bounding_box()
    assert_equal(bb.ll.x, 0)
    assert_equal(bb.ur.x, 1)

def main():
    TestSuite.discover_tests[__functions_in_module()]().run()

