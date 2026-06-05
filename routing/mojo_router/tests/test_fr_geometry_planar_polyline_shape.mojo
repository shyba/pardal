from testing.suite import TestSuite
from testing import assert_equal, assert_true

from pardal_router_mojo.fr.geometry.planar.int_box import IntBox
from pardal_router_mojo.fr.geometry.planar.int_point import IntPoint
from pardal_router_mojo.fr.geometry.planar.line_segment import LineSegment
from pardal_router_mojo.fr.geometry.planar.polyline_shape import PolylineShapeBox


def test_polyline_shape_box_border_order_smoke():
    shape = PolylineShapeBox(IntBox(IntPoint(0, 0), IntPoint(10, 5)))
    assert_equal(shape.border_line_count(), 4)
    # Bottom edge is RIGHT (y=0).
    l0 = shape.border_line(0)
    assert_true(l0.a.y == 0 and l0.b.y == 0)
    assert_true(l0.b.x > l0.a.x)


def test_line_segment_from_polyline_shape_box_smoke():
    shape = PolylineShapeBox(IntBox(IntPoint(0, 0), IntPoint(10, 5)))
    seg = LineSegment.from_polyline_shape_box(shape, 0)
    bb = seg.bounding_box()
    assert_equal(bb.ll.x, 0)
    assert_equal(bb.ur.x, 10)


def main():
    TestSuite.discover_tests[__functions_in_module()]().run()
