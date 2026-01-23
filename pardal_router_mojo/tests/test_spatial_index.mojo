from collections import List

from testing import assert_equal, assert_true
from testing.suite import TestSuite

from pardal_router_mojo.geometry import AABB, Segment, Vec2
from pardal_router_mojo.spatial_index import SpatialSegmentIndex


def test_spatial_index_aabb_query_dedup():
    var idx = SpatialSegmentIndex(origin_x=0.0, origin_y=0.0, cols=10, rows=10, cell_size=1.0)
    var s0 = Segment(Vec2(0.0, 0.0), Vec2(5.0, 0.0))
    var s1 = Segment(Vec2(2.0, 2.0), Vec2(2.0, 6.0))
    var id0 = idx.add_segment(s0, UInt32(1), 0.2)
    var id1 = idx.add_segment(s1, UInt32(2), 0.3)
    assert_equal(id0, 0)
    assert_equal(id1, 1)

    var hits = idx.query_aabb(AABB(1.0, -1.0, 3.0, 1.0))
    # s0 intersects; s1 doesn't.
    assert_equal(len(hits), 1)
    assert_equal(hits[0], 0)

    var hits2 = idx.query_aabb(AABB(1.5, 1.5, 2.5, 2.5))
    assert_equal(len(hits2), 1)
    assert_equal(hits2[0], 1)


def test_spatial_index_large_query_hits_both():
    var idx = SpatialSegmentIndex(origin_x=0.0, origin_y=0.0, cols=10, rows=10, cell_size=1.0)
    _ = idx.add_segment(Segment(Vec2(0.0, 0.0), Vec2(5.0, 0.0)), UInt32(1), 0.2)
    _ = idx.add_segment(Segment(Vec2(2.0, 2.0), Vec2(2.0, 6.0)), UInt32(2), 0.2)
    var hits = idx.query_aabb(AABB(-1.0, -1.0, 10.0, 10.0))
    assert_true(len(hits) == 2)


def main():
    TestSuite.discover_tests[__functions_in_module()]().run()
