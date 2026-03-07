from testing.suite import TestSuite
from testing import assert_equal, assert_true

from pardal_router_mojo.fr.geometry.planar.int_box import IntBox
from pardal_router_mojo.fr.geometry.planar.int_point import IntPoint
from pardal_router_mojo.fr.geometry.planar.float_point import FloatPoint

def test_int_box_basic():
    b = IntBox(IntPoint(0, 0), IntPoint(10, 5))
    assert_true(not b.is_empty())
    assert_equal(b.width(), 10)
    assert_equal(b.height(), 5)
    assert_equal(b.dimension(), 2)
    assert_true(b.contains_inside(IntPoint(1, 1)))
    assert_true(not b.contains_inside(IntPoint(0, 0)))

def test_int_box_nearest_point_clamps():
    b = IntBox(IntPoint(0, 0), IntPoint(10, 10))
    p = b.nearest_point(FloatPoint(-5.0, 3.0))
    assert_equal(p.x, 0.0)
    assert_equal(p.y, 3.0)
    q = b.nearest_point(FloatPoint(5.0, 50.0))
    assert_equal(q.x, 5.0)
    assert_equal(q.y, 10.0)

def test_int_box_intersects_overlaps():
    a = IntBox(IntPoint(0, 0), IntPoint(10, 10))
    b = IntBox(IntPoint(10, 0), IntPoint(20, 10))
    # intersects uses <= (touching counts)
    assert_true(a.intersects(b))
    # overlaps uses < (touching not overlap)
    assert_true(not a.overlaps(b))

def test_int_box_union_intersection_offset():
    a = IntBox(IntPoint(0, 0), IntPoint(10, 10))
    b = IntBox(IntPoint(5, 5), IntPoint(20, 20))
    u = a.union(b)
    assert_equal(u.ll.x, 0)
    assert_equal(u.ll.y, 0)
    assert_equal(u.ur.x, 20)
    assert_equal(u.ur.y, 20)
    i = a.intersection(b)
    assert_equal(i.ll.x, 5)
    assert_equal(i.ll.y, 5)
    assert_equal(i.ur.x, 10)
    assert_equal(i.ur.y, 10)
    o = a.offset(2.0)
    assert_equal(o.ll.x, -2)
    assert_equal(o.ur.x, 12)

def test_int_box_shrink():
    a = IntBox(IntPoint(0, 0), IntPoint(10, 10))
    s = a.shrink(2)
    assert_equal(s.ll.x, 2)
    assert_equal(s.ur.x, 8)
    # shrink past vanishing clamps to center
    z = a.shrink(100)
    assert_equal(z.ll.x, 5)
    assert_equal(z.ur.x, 5)

def main():
    TestSuite.discover_tests[__functions_in_module()]().run()
