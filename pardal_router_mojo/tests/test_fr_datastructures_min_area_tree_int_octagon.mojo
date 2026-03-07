from testing.suite import TestSuite
from testing import assert_equal, assert_true

from pardal_router_mojo.fr.datastructures.min_area_tree_int_octagon import (
    MinAreaTreeIntOctagon,
)
from pardal_router_mojo.fr.geometry.planar.int_octagon import IntOctagon


def test_min_area_tree_int_octagon_overlaps_smoke():
    t = MinAreaTreeIntOctagon()
    a = IntOctagon(0, 10, 0, 10, -10, 10, 0, 20).normalize()
    b = IntOctagon(20, 30, 0, 10, 10, 30, 20, 40).normalize()
    _ = t.insert_leaf(1, 0, a)
    _ = t.insert_leaf(2, 0, b)
    q = IntOctagon(5, 6, 5, 6, -1, 11, 0, 12).normalize()
    hits = t.overlaps(q)
    assert_equal(len(hits), 1)


def test_min_area_tree_int_octagon_remove_leaf_swap_smoke():
    t = MinAreaTreeIntOctagon()
    a = IntOctagon.from_freerouting(0, 0, 10, 10, -10, 10, 0, 20).normalize()
    b = IntOctagon.from_freerouting(20, 0, 30, 10, 10, 30, 20, 40).normalize()
    c = IntOctagon.from_freerouting(40, 0, 50, 10, 30, 50, 40, 60).normalize()
    _ = t.insert_leaf(1, 0, a)
    bi = t.insert_leaf(2, 0, b)
    _ = t.insert_leaf(3, 0, c)
    assert_true(t.remove_leaf(bi))
    hits_a = t.overlaps(IntOctagon.from_box(5, 5, 6, 6))
    assert_equal(len(hits_a), 1)
    hits_b = t.overlaps(IntOctagon.from_box(25, 5, 26, 6))
    assert_equal(len(hits_b), 0)


def main():
    TestSuite.discover_tests[__functions_in_module()]().run()
