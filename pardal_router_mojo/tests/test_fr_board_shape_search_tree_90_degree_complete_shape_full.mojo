from collections import List
from testing.suite import TestSuite
from testing import assert_equal, assert_true

from pardal_router_mojo.fr.autoroute.incomplete_free_space_expansion_room import (
    IncompleteFreeSpaceExpansionRoom,
)
from pardal_router_mojo.fr.board.search_tree_object import SearchTreeObject
from pardal_router_mojo.fr.board.shape_search_tree_90_degree_full import (
    ShapeSearchTree90Degree,
)
from pardal_router_mojo.fr.geometry.planar.int_box import IntBox
from pardal_router_mojo.fr.geometry.planar.int_point import IntPoint
from pardal_router_mojo.fr.geometry.planar.polyline import Polyline
from pardal_router_mojo.fr.geometry.planar.tile_shape import TileShapeBox


def test_complete_shape_full_ignores_intersection_in_door_shape():
    board_bb = IntBox(IntPoint(0, 0), IntPoint(100, 100))
    tree = ShapeSearchTree90Degree(board_bb)

    # Start room is a big box, contained box is small.
    room = IncompleteFreeSpaceExpansionRoom(
        IntBox(IntPoint(0, 0), IntPoint(100, 100)),
        0,
        IntBox(IntPoint(10, 10), IntPoint(20, 20)),
    )

    # Obstacle overlaps room; it's a "complete room", so ignore-shape logic applies.
    obstacle = SearchTreeObject(
        IntBox(IntPoint(40, 40), IntPoint(60, 60)),
        0,
        1,
        0,
        True,
        True,
        True,
    )
    _ = tree.insert_object(obstacle)

    # Provide an ignore shape that contains the intersection.
    ignore_shape = TileShapeBox(IntBox(IntPoint(0, 0), IntPoint(100, 100)))
    out = tree.complete_shape(
        room, net_no=1, ignore_object_id=-1, ignore_shape=ignore_shape
    )
    # FreeRouting's logic uses `continue;` at the room loop level, which drops the
    # current room when its overlap is fully inside the ignore-shape door region.
    assert_equal(len(out), 0)


def test_complete_shape_full_cuts_when_not_ignored():
    board_bb = IntBox(IntPoint(0, 0), IntPoint(100, 100))
    tree = ShapeSearchTree90Degree(board_bb)
    room = IncompleteFreeSpaceExpansionRoom(
        IntBox(IntPoint(0, 0), IntPoint(100, 100)),
        0,
        IntBox(IntPoint(10, 10), IntPoint(20, 20)),
    )
    obstacle = SearchTreeObject(
        IntBox(IntPoint(40, 40), IntPoint(60, 60)),
        0,
        1,
        0,
        True,
        True,
        False,
    )
    _ = tree.insert_object(obstacle)
    out = tree.complete_shape(
        room, net_no=1, ignore_object_id=-1, ignore_shape=TileShapeBox(IntBox.empty())
    )
    assert_true(len(out) >= 1)
    # Bounding boxes of output rooms should not overlap the obstacle.
    for r in out:
        assert_true(not r.get_shape().overlaps(obstacle.get_tree_shape_box(0)))


def test_offset_shapes_boxes_smoke():
    board_bb = IntBox(IntPoint(0, 0), IntPoint(100, 100))
    tree = ShapeSearchTree90Degree(board_bb)
    ax = List[Int]()
    ay = List[Int]()
    bx = List[Int]()
    by = List[Int]()
    ax.append(0)
    ay.append(5)
    bx.append(0)
    by.append(6)
    ax.append(0)
    ay.append(5)
    bx.append(10)
    by.append(5)
    ax.append(10)
    ay.append(5)
    bx.append(10)
    by.append(6)
    p = Polyline.from_segments(ax, ay, bx, by)
    shapes = tree.offset_shapes_boxes(p, 2, 0, 2)
    assert_equal(len(shapes), 1)
    assert_true(not shapes[0].is_empty())


def main():
    TestSuite.discover_tests[__functions_in_module()]().run()
