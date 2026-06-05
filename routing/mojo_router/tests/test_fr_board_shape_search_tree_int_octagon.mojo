from testing.suite import TestSuite
from testing import assert_equal, assert_true

from pardal_router_mojo.fr.board.search_tree_object import SearchTreeObject
from pardal_router_mojo.fr.board.shape_search_tree_int_octagon import (
    ShapeSearchTreeIntOctagon,
)
from pardal_router_mojo.fr.board.layer import Layer
from pardal_router_mojo.fr.board.layer_structure import LayerStructure
from pardal_router_mojo.fr.geometry.planar.int_box import IntBox
from pardal_router_mojo.fr.geometry.planar.int_octagon import IntOctagon
from pardal_router_mojo.fr.geometry.planar.int_point import IntPoint
from pardal_router_mojo.fr.rules.clearance_matrix import ClearanceMatrix


def test_shape_search_tree_int_octagon_overlaps_smoke():
    tree = ShapeSearchTreeIntOctagon()
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
    q = IntOctagon.from_freerouting(5, 5, 6, 6, -1, 1, 10, 12).normalize()
    hits = tree.overlaps(q)
    assert_equal(len(hits), 1)
    assert_equal(hits[0].object_id, 0)


def test_shape_search_tree_int_octagon_clearance_compensation_expands():
    layers = LayerStructure([Layer("L0", True)])
    var cm = ClearanceMatrix(2, layers, ["a", "b"])
    # Set clearance matrix so that compensation when obj_cc=1 into tree_cc=1 is 5.
    cm.set_value(1, 1, 0, 10)
    var tree = ShapeSearchTreeIntOctagon()
    tree.clearance_matrix = cm^
    tree.compensated_clearance_class_no = 1
    _ = tree.insert_object(
        SearchTreeObject(
            IntBox(IntPoint(0, 0), IntPoint(10, 10)),
            0,
            1,
            1,
            True,
            True,
            False,
        )
    )
    q = IntOctagon.from_box(-4, -4, -3, -3)
    hits = tree.overlaps(q)
    assert_true(len(hits) == 1)


def test_shape_search_tree_int_octagon_remove_object_removes_leaves():
    var tree = ShapeSearchTreeIntOctagon()
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
    q = IntOctagon.from_box(5, 5, 6, 6)
    assert_equal(len(tree.overlaps(q)), 1)
    assert_equal(tree.remove_object(0), 1)
    assert_equal(len(tree.overlaps(q)), 0)


def main():
    TestSuite.discover_tests[__functions_in_module()]().run()
