from collections import List

from testing import assert_equal, assert_true
from testing.suite import TestSuite

from pardal_router_mojo.grid import Grid
from pardal_router_mojo.router import BBox, _exit_candidates_from_start


def test_exit_candidates_from_start_falls_back_sides():
    # 1-layer 7x7; start at center. Preferred side will be left (tie),
    # but we block the entire left edge so candidates must come from other sides.
    var g = Grid(1, 7, 7)
    var net_id = UInt32(1)
    # Block left edge for this net by stamping unconditional base obstacles.
    var y = 0
    while y < 7:
        g.stamp_circle_base(0, 0, y, 0, UInt32(0xFFFF_FFFF))
        y += 1
    var bb = BBox(0, 0, 6, 6)
    var start_idx = g.idx(0, 3, 3)
    var c = _exit_candidates_from_start(g, start_idx, net_id, bb, 6)
    assert_true(len(c) > 0)
    # None of the candidates should be on the blocked left edge (x==0).
    for idx in c:
        var xy = idx % (g.width * g.height)
        var x = xy % g.width
        assert_true(x != 0)


def main():
    TestSuite.discover_tests[__functions_in_module()]().run()

