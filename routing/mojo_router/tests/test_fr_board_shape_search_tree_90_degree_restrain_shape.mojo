from collections import List
from testing.suite import TestSuite
from testing import assert_equal

from pardal_router_mojo.fr.autoroute.incomplete_free_space_expansion_room import IncompleteFreeSpaceExpansionRoom
from pardal_router_mojo.fr.board.shape_search_tree_90_degree import restrain_shape
from pardal_router_mojo.fr.geometry.planar.int_box import IntBox
from pardal_router_mojo.fr.geometry.planar.int_point import IntPoint

def test_restrain_shape_smoke_returns_list():
    room = IncompleteFreeSpaceExpansionRoom(
        IntBox(IntPoint(0, 0), IntPoint(100, 100)),
        0,
        IntBox(IntPoint(10, 10), IntPoint(20, 20)),
    )
    obstacle = IntBox(IntPoint(40, 0), IntPoint(60, 100))
    res: List[IncompleteFreeSpaceExpansionRoom] = restrain_shape(room, obstacle)
    assert_equal(len(res), 1)
    s = res[0].get_shape()
    # Contained box is left of obstacle, so cut should be at obstacle.ll.x (keep left side).
    assert_equal(s.ur.x, 40)

def main():
    TestSuite.discover_tests[__functions_in_module()]().run()
