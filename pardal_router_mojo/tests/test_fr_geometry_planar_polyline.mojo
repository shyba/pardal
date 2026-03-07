from collections import List
from testing.suite import TestSuite
from testing import assert_equal, assert_true

from pardal_router_mojo.fr.geometry.planar.polyline import Polyline


def test_polyline_filters_parallel_consecutive():
    ax = List[Int]()
    ay = List[Int]()
    bx = List[Int]()
    by = List[Int]()
    ax.append(0)
    ax.append(0)
    ax.append(0)
    ax.append(0)
    ay.append(0)
    ay.append(1)
    ay.append(0)
    ay.append(0)
    bx.append(1)
    bx.append(1)
    bx.append(0)
    bx.append(1)
    by.append(0)
    by.append(1)
    by.append(1)
    by.append(1)
    p = Polyline.from_segments(ax, ay, bx, by)
    assert_true(p.line_count() >= 3)


def test_polyline_corner_approx_smoke():
    ax = List[Int]()
    ay = List[Int]()
    bx = List[Int]()
    by = List[Int]()
    ax.append(0)
    ax.append(0)
    ax.append(0)
    ay.append(0)
    ay.append(0)
    ay.append(1)
    bx.append(1)
    bx.append(0)
    bx.append(1)
    by.append(0)
    by.append(1)
    by.append(0)
    p = Polyline.from_segments(ax, ay, bx, by)
    assert_true(p.line_count() == 3)
    c0 = p.corner_approx(0)
    assert_equal(Int(round(c0.x)), 0)
    assert_equal(Int(round(c0.y)), 0)


def test_polyline_offset_box_smoke():
    # Polyline with a single horizontal segment between x=0 and x=10 at y=5.
    # In Polyline terms: 3 lines where the middle is the segment direction.
    ax = List[Int]()
    ay = List[Int]()
    bx = List[Int]()
    by = List[Int]()
    # start closing line (vertical at x=0)
    ax.append(0)
    ay.append(5)
    bx.append(0)
    by.append(6)
    # middle line (horizontal y=5)
    ax.append(0)
    ay.append(5)
    bx.append(10)
    by.append(5)
    # end closing line (vertical at x=10)
    ax.append(10)
    ay.append(5)
    bx.append(10)
    by.append(6)
    p = Polyline.from_segments(ax, ay, bx, by)
    bb = p.offset_box(2, 0)
    assert_equal(bb.ll.x, -2)
    assert_equal(bb.ur.x, 12)
    assert_equal(bb.ll.y, 3)
    assert_equal(bb.ur.y, 7)


def main():
    TestSuite.discover_tests[__functions_in_module()]().run()
