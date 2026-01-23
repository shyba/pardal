from collections import List

from testing import assert_equal, assert_true
from testing.suite import TestSuite

from pardal_router_mojo.grid import Grid
from pardal_router_mojo.router import _pull_tight_path


def test_pull_tight_removes_collinear():
    # Straight line with redundant points.
    var g = Grid(1, 10, 10)
    var p = List[Int]()
    p.append(g.idx(0, 1, 1))
    p.append(g.idx(0, 2, 1))
    p.append(g.idx(0, 3, 1))
    p.append(g.idx(0, 4, 1))
    var out = _pull_tight_path(g, UInt32(1), p, False, False, False)
    assert_equal(len(out), 2)


def test_pull_tight_shortcuts_zigzag():
    var g = Grid(1, 10, 10)
    var p = List[Int]()
    # zigzag but LOS exists from start->end (axis-aligned not possible; use diagonal)
    p.append(g.idx(0, 1, 1))
    p.append(g.idx(0, 2, 1))
    p.append(g.idx(0, 2, 2))
    p.append(g.idx(0, 3, 2))
    p.append(g.idx(0, 3, 3))
    var out = _pull_tight_path(g, UInt32(1), p, True, False, False)
    assert_true(len(out) <= 3)


def main():
    TestSuite.discover_tests[__functions_in_module()]().run()

