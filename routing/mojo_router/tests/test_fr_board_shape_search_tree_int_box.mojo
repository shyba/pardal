from testing.suite import TestSuite
from testing import assert_equal, assert_true

from pardal_router_mojo.fr.board.search_tree_object import SearchTreeObject
from pardal_router_mojo.fr.board.shape_search_tree_int_box import ShapeSearchTreeIntBox
from pardal_router_mojo.fr.geometry.planar.int_box import IntBox
from pardal_router_mojo.fr.geometry.planar.int_point import IntPoint


def test_shape_search_tree_int_box_overlaps_smoke():
    tree = ShapeSearchTreeIntBox(IntBox(IntPoint(0, 0), IntPoint(100, 100)))
    _ = tree.insert_object(
        SearchTreeObject(
            IntBox(IntPoint(0, 0), IntPoint(10, 10)),
            0,
            1,
            0,
            True,
            True,
            False,
        )
    )
    hits = tree.overlaps(IntBox(IntPoint(5, 5), IntPoint(6, 6)))
    assert_equal(len(hits), 1)
    assert_equal(hits[0].object_id, 0)
    assert_equal(hits[0].shape_index, 0)


def test_shape_search_tree_int_box_remove_object_removes_leaves():
    tree = ShapeSearchTreeIntBox(IntBox(IntPoint(0, 0), IntPoint(100, 100)))
    _ = tree.insert_object(
        SearchTreeObject(
            IntBox(IntPoint(0, 0), IntPoint(10, 10)),
            0,
            1,
            0,
            True,
            True,
            False,
        )
    )
    hits = tree.overlaps(IntBox(IntPoint(5, 5), IntPoint(6, 6)))
    assert_equal(len(hits), 1)
    assert_equal(tree.remove_object(0), 1)
    hits2 = tree.overlaps(IntBox(IntPoint(5, 5), IntPoint(6, 6)))
    assert_equal(len(hits2), 0)


def main():
    TestSuite.discover_tests[__functions_in_module()]().run()
