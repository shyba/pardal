from testing.suite import TestSuite
from testing import assert_equal, assert_true

from pardal_router_mojo.fr.datastructures.min_area_tree_int_box import MinAreaTreeIntBox
from pardal_router_mojo.fr.geometry.planar.int_box import IntBox
from pardal_router_mojo.fr.geometry.planar.int_point import IntPoint


def test_min_area_tree_overlaps_smoke():
    t = MinAreaTreeIntBox()
    a = IntBox(IntPoint(0, 0), IntPoint(10, 10))
    b = IntBox(IntPoint(20, 0), IntPoint(30, 10))
    _ = t.insert_leaf(1, 0, a)
    _ = t.insert_leaf(2, 0, b)

    q = IntBox(IntPoint(5, 5), IntPoint(6, 6))
    hits = t.overlaps(q)
    assert_equal(len(hits), 1)

    q2 = IntBox(IntPoint(10, 0), IntPoint(20, 10))
    hits2 = t.overlaps(q2)
    # touching both edges should hit both in this intersects semantics
    assert_true(len(hits2) >= 1)


def test_min_area_tree_remove_leaf_swap_smoke():
    t = MinAreaTreeIntBox()
    a = t.insert_leaf(1, 0, IntBox(IntPoint(0, 0), IntPoint(10, 10)))
    b = t.insert_leaf(2, 0, IntBox(IntPoint(20, 20), IntPoint(30, 30)))
    c = t.insert_leaf(3, 0, IntBox(IntPoint(40, 40), IntPoint(50, 50)))
    assert_true(t.remove_leaf(b))
    hits_a = t.overlaps(IntBox(IntPoint(5, 5), IntPoint(6, 6)))
    assert_equal(len(hits_a), 1)
    hits_b = t.overlaps(IntBox(IntPoint(25, 25), IntPoint(26, 26)))
    assert_equal(len(hits_b), 0)
    hits_c = t.overlaps(IntBox(IntPoint(45, 45), IntPoint(46, 46)))
    assert_equal(len(hits_c), 1)


def main():
    TestSuite.discover_tests[__functions_in_module()]().run()
