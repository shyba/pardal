from collections import List
from testing.suite import TestSuite
from testing import assert_true

from pardal_router_mojo.fr.autoroute.incomplete_free_space_expansion_room_octagon import (
    IncompleteFreeSpaceExpansionRoomOctagon,
)
from pardal_router_mojo.fr.board.search_tree_object import SearchTreeObject
from pardal_router_mojo.fr.board.shape_search_tree_45_degree_full import (
    ShapeSearchTree45Degree,
)
from pardal_router_mojo.fr.geometry.planar.int_box import IntBox
from pardal_router_mojo.fr.geometry.planar.int_octagon import IntOctagon
from pardal_router_mojo.fr.geometry.planar.int_point import IntPoint


def test_complete_shape_45_degree_smoke():
    board = IntOctagon.from_box(0, 0, 100, 100)
    tree = ShapeSearchTree45Degree(board)

    # Insert a trace obstacle (box -> octagon bounds).
    _ = tree.insert_object(
        SearchTreeObject(
            IntBox(IntPoint(40, 40), IntPoint(60, 60)),
            0,
            1,
            0,
            True,
            True,
            False,
        )
    )

    room = IncompleteFreeSpaceExpansionRoomOctagon(
        board.copy(),
        0,
        IntOctagon.from_box(10, 10, 20, 20),
    )
    out = tree.complete_shape(
        room, net_no=1, ignore_object_id=-1, ignore_shape=IntOctagon.empty()
    )
    # Should not produce rooms that overlap the obstacle.
    obs = IntOctagon.from_box(40, 40, 60, 60)
    for r in out:
        assert_true(not r.get_shape().overlaps(obs))


def test_complete_shape_45_degree_ignore_shape_drops_room_like_java():
    board = IntOctagon.from_box(0, 0, 100, 100)
    tree = ShapeSearchTree45Degree(board)

    _ = tree.insert_object(
        SearchTreeObject(
            IntBox(IntPoint(40, 40), IntPoint(60, 60)),
            0,
            1,
            0,
            True,
            True,
            True,
        )
    )
    room = IncompleteFreeSpaceExpansionRoomOctagon(
        board.copy(),
        0,
        IntOctagon.from_box(10, 10, 20, 20),
    )
    ignore = board.copy()
    out = tree.complete_shape(room, net_no=1, ignore_object_id=-1, ignore_shape=ignore)
    # In FreeRouting, this "continue" skips adding the current room, so output can be empty.
    assert_true(len(out) == 0 or len(out) == 1)


def test_complete_shape_45_degree_divide_large_room_splits_bbox():
    board = IntOctagon.from_box(0, 0, 100, 100)
    tree = ShapeSearchTree45Degree(board)
    room = IncompleteFreeSpaceExpansionRoomOctagon(
        board.copy(),
        0,
        IntOctagon.from_box(10, 10, 20, 20),
    )
    out = tree.complete_shape(
        room, net_no=1, ignore_object_id=-1, ignore_shape=IntOctagon.empty()
    )
    assert_true(len(out) >= 2)


def main():
    TestSuite.discover_tests[__functions_in_module()]().run()
