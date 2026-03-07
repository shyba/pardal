from testing.suite import TestSuite
from testing import assert_true

from pardal_router_mojo.fr.autoroute.incomplete_free_space_expansion_room_octagon import (
    IncompleteFreeSpaceExpansionRoomOctagon,
)
from pardal_router_mojo.fr.board.shape_search_tree_45_degree import (
    obstacle_segment_touches_inside,
    restrain_shape,
)
from pardal_router_mojo.fr.geometry.planar.int_octagon import IntOctagon


def test_obstacle_segment_touches_inside_smoke():
    room = IntOctagon.from_freerouting(0, 0, 100, 100, -100, 100, 0, 200).normalize()
    obs = IntOctagon.from_freerouting(40, 40, 60, 60, -20, 20, 80, 120).normalize()
    assert_true(obstacle_segment_touches_inside(obs, 0, room))


def test_restrain_shape_smoke_produces_pieces_or_empty():
    room_shape = IntOctagon.from_freerouting(
        0, 0, 100, 100, -100, 100, 0, 200
    ).normalize()
    contained = IntOctagon.from_freerouting(10, 10, 20, 20, -10, 10, 20, 40).normalize()
    room = IncompleteFreeSpaceExpansionRoomOctagon(
        room_shape.copy(), 0, contained.copy()
    )
    obs = IntOctagon.from_freerouting(40, 40, 60, 60, -20, 20, 80, 120).normalize()
    out = restrain_shape(room, obs)
    # Should not crash; if it returns a piece it must keep contained inside.
    for r in out:
        assert_true(r.get_contained_shape().is_contained_in(r.get_shape()))


def main():
    TestSuite.discover_tests[__functions_in_module()]().run()
