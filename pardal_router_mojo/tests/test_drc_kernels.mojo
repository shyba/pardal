from collections import List

from testing import assert_true
from testing.suite import TestSuite

from pardal_router_mojo.drc_kernels import check_circle_segment_clearance, check_segment_clearance
from pardal_router_mojo.geometry import Circle, Segment, Vec2
from pardal_router_mojo.spatial_index import SpatialSegmentIndex


def test_check_circle_segment_clearance():
    var seg = Segment(Vec2(0.0, 0.0), Vec2(10.0, 0.0))
    var c_ok = Circle(Vec2(5.0, 5.0), 1.0)
    var c_bad = Circle(Vec2(5.0, 1.1), 1.0)
    assert_true(not check_circle_segment_clearance(seg=seg, circle=c_ok, clearance=0.5))
    assert_true(check_circle_segment_clearance(seg=seg, circle=c_bad, clearance=0.5))


def test_check_segment_clearance_simple():
    var idx = SpatialSegmentIndex(origin_x=0.0, origin_y=0.0, cols=20, rows=20, cell_size=1.0)
    _ = idx.add_segment(Segment(Vec2(0.0, 0.0), Vec2(10.0, 0.0)), UInt32(1), 0.2)  # id 0
    _ = idx.add_segment(Segment(Vec2(0.0, 2.0), Vec2(10.0, 2.0)), UInt32(2), 0.2)  # id 1
    _ = idx.add_segment(Segment(Vec2(0.0, 0.2), Vec2(10.0, 0.2)), UInt32(3), 0.2)  # id 2

    # Segment 2 is within 0.5mm of segment 0 -> violation; segment 1 is not.
    var viol = check_segment_clearance(index=idx, seg=idx.segs[2], clearance=0.5, self_id=2)
    var any0 = False
    var any1 = False
    for v in viol:
        if (v.a == 2 and v.b == 0) or (v.a == 0 and v.b == 2):
            any0 = True
        if (v.a == 2 and v.b == 1) or (v.a == 1 and v.b == 2):
            any1 = True
    assert_true(any0)
    assert_true(not any1)


def main():
    TestSuite.discover_tests[__functions_in_module()]().run()
