from collections import List
from testing.suite import TestSuite
from testing import assert_equal, assert_true

from pardal_router_mojo.fr.autoroute.incomplete_free_space_expansion_room import IncompleteFreeSpaceExpansionRoom
from pardal_router_mojo.fr.board.shape_search_tree_90_degree_tree import ShapeSearchTree90DegreeLite
from pardal_router_mojo.fr.geometry.planar.int_box import IntBox
from pardal_router_mojo.fr.geometry.planar.int_point import IntPoint

def test_complete_shape_cuts_room_against_obstacle():
    board_bbox = IntBox(IntPoint(0, 0), IntPoint(100, 100))
    tree = ShapeSearchTree90DegreeLite(board_bbox)
    # obstacle vertical strip in the middle (net 1 on layer 0)
    _ = tree.insert_obstacle(IntBox(IntPoint(40, 0), IntPoint(60, 100)), 0, 1, True)

    room = IncompleteFreeSpaceExpansionRoom(
        IntBox(IntPoint(0, 0), IntPoint(100, 100)),
        0,
        IntBox(IntPoint(10, 10), IntPoint(20, 20)),
    )
    res: List[IncompleteFreeSpaceExpansionRoom] = tree.complete_shape(room, 1, -1, IntBox.empty())
    assert_true(len(res) >= 1)
    # The contained shape is left of obstacle => expect a left-side room with ur.x == 40
    assert_equal(res[0].get_shape().ur.x, 40)

def test_complete_shape_ignores_other_net():
    board_bbox = IntBox(IntPoint(0, 0), IntPoint(100, 100))
    tree = ShapeSearchTree90DegreeLite(board_bbox)
    _ = tree.insert_obstacle(IntBox(IntPoint(40, 0), IntPoint(60, 100)), 0, 2, True)

    room = IncompleteFreeSpaceExpansionRoom(
        IntBox(IntPoint(0, 0), IntPoint(100, 100)),
        0,
        IntBox(IntPoint(10, 10), IntPoint(20, 20)),
    )
    res: List[IncompleteFreeSpaceExpansionRoom] = tree.complete_shape(room, 1, -1, IntBox.empty())
    assert_equal(len(res), 1)
    assert_equal(res[0].get_shape().ur.x, 100)

def main():
    TestSuite.discover_tests[__functions_in_module()]().run()

