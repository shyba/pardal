from testing.suite import TestSuite
from testing import assert_equal, assert_true

from pardal_router_mojo.fr.autoroute.incomplete_free_space_expansion_room_octagon import (
    IncompleteFreeSpaceExpansionRoomOctagon,
)
from pardal_router_mojo.fr.geometry.planar.int_octagon import IntOctagon


def test_incomplete_room_octagon_getters_copy():
    shape = IntOctagon(0, 10, 0, 10, -10, 10, 0, 20).normalize()
    assert_true(not shape.is_empty())
    room = IncompleteFreeSpaceExpansionRoomOctagon(shape.copy(), 1, shape.copy())
    s = room.get_shape()
    assert_equal(s.leftX, 0)
    assert_equal(room.get_layer(), 1)
    c = room.get_contained_shape()
    assert_equal(c.topY, shape.topY)


def main():
    TestSuite.discover_tests[__functions_in_module()]().run()
