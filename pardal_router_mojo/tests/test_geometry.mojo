from collections import List

from testing import assert_equal, assert_true
from testing.suite import TestSuite

from pardal_router_mojo.geometry import (
    AABB,
    Circle,
    Segment,
    Vec2,
    aabb_from_points,
    aabb_intersects,
    circle_intersects_circle,
    circle_intersects_segment,
    dist_point_segment2,
    dist_point_polygon2,
    dist_segment_segment2,
    dist_segment_polygon2,
    segments_intersect,
    point_in_polygon,
)


def test_aabb_from_points():
    var pts = List[Vec2]()
    pts.append(Vec2(1.0, 2.0))
    pts.append(Vec2(-1.0, 4.0))
    pts.append(Vec2(3.0, -2.0))
    var bb = aabb_from_points(pts)
    assert_equal(bb.min_x, -1.0)
    assert_equal(bb.min_y, -2.0)
    assert_equal(bb.max_x, 3.0)
    assert_equal(bb.max_y, 4.0)


def test_aabb_intersects():
    assert_true(aabb_intersects(AABB(0.0, 0.0, 1.0, 1.0), AABB(1.0, 1.0, 2.0, 2.0)))
    assert_true(not aabb_intersects(AABB(0.0, 0.0, 1.0, 1.0), AABB(1.1, 0.0, 2.0, 1.0)))


def test_segments_intersect_cross():
    var a0 = Vec2(0.0, 0.0)
    var a1 = Vec2(2.0, 2.0)
    var b0 = Vec2(0.0, 2.0)
    var b1 = Vec2(2.0, 0.0)
    assert_true(segments_intersect(a0, a1, b0, b1))
    assert_equal(dist_segment_segment2(a0, a1, b0, b1), 0.0)


def test_segments_intersect_collinear_touch():
    var a0 = Vec2(0.0, 0.0)
    var a1 = Vec2(2.0, 0.0)
    var b0 = Vec2(2.0, 0.0)
    var b1 = Vec2(3.0, 0.0)
    assert_true(segments_intersect(a0, a1, b0, b1))
    assert_equal(dist_segment_segment2(a0, a1, b0, b1), 0.0)


def test_point_segment_distance():
    var p = Vec2(1.0, 1.0)
    var a = Vec2(0.0, 0.0)
    var b = Vec2(2.0, 0.0)
    assert_equal(dist_point_segment2(p, a, b), 1.0)


def test_circle_intersections():
    var c1 = Circle(Vec2(0.0, 0.0), 1.0)
    var c2 = Circle(Vec2(1.5, 0.0), 1.0)
    var c3 = Circle(Vec2(3.0, 0.0), 1.0)
    assert_true(circle_intersects_circle(c1, c2))
    assert_true(not circle_intersects_circle(c1, c3))

    var s = Segment(Vec2(-2.0, 0.0), Vec2(2.0, 0.0))
    assert_true(circle_intersects_segment(c1, s))
    var s2 = Segment(Vec2(-2.0, 2.0), Vec2(2.0, 2.0))
    assert_true(not circle_intersects_segment(c1, s2))


def test_point_in_polygon_and_distances():
    var poly = List[Vec2]()
    poly.append(Vec2(0.0, 0.0))
    poly.append(Vec2(10.0, 0.0))
    poly.append(Vec2(10.0, 10.0))
    poly.append(Vec2(0.0, 10.0))
    assert_true(point_in_polygon(Vec2(5.0, 5.0), poly))
    assert_true(not point_in_polygon(Vec2(15.0, 5.0), poly))
    assert_equal(dist_point_polygon2(Vec2(5.0, 5.0), poly), 0.0)
    assert_equal(dist_point_polygon2(Vec2(15.0, 5.0), poly), 25.0)
    assert_equal(dist_segment_polygon2(Vec2(15.0, 5.0), Vec2(15.0, 6.0), poly), 25.0)
    assert_equal(dist_segment_polygon2(Vec2(-1.0, 5.0), Vec2(1.0, 5.0), poly), 0.0)


def main():
    TestSuite.discover_tests[__functions_in_module()]().run()
