from testing import assert_equal, assert_true
from testing.suite import TestSuite

from pardal_router_mojo.astar import AStarWorkspace, idx_to_coords, route_a_star
from pardal_router_mojo.grid import Grid


def test_astar_finds_straight_path():
    var g = Grid(1, 5, 5)
    var ws = AStarWorkspace(g.layers * g.width * g.height)
    var start = g.idx(0, 0, 0)
    var goal = g.idx(0, 4, 0)
    var path = route_a_star(
        ws,
        g,
        start,
        goal,
        UInt32(1),
        UInt64(0),
        False,
        UInt32(0),
        UInt32(0),
        UInt32(0),
        UInt32(0),
        0,
        UInt32(100),
        False,
        False,
        False,
        UInt32(0),
        UInt16(0),
        UInt32(0),
        UInt32(0),
        False,
        List[UInt32](),
        List[UInt32](),
        False,
        UInt32(0),
    )
    assert_true(len(path) >= 2)
    var a = idx_to_coords(path[0], g.width, g.height)
    var b = idx_to_coords(path[len(path) - 1], g.width, g.height)
    assert_equal(a.x, 0)
    assert_equal(b.x, 4)


def test_astar_avoids_blocked_circle():
    var g = Grid(1, 7, 7)
    var ws = AStarWorkspace(g.layers * g.width * g.height)
    g.stamp_circle_base(0, 3, 3, 2, UInt32(2))

    var start = g.idx(0, 0, 3)
    var goal = g.idx(0, 6, 3)
    # Need some margin to route around the obstacle.
    var path = route_a_star(
        ws,
        g,
        start,
        goal,
        UInt32(1),
        UInt64(0),
        False,
        UInt32(0),
        UInt32(0),
        UInt32(0),
        UInt32(0),
        3,
        UInt32(100),
        False,
        False,
        False,
        UInt32(0),
        UInt16(0),
        UInt32(0),
        UInt32(0),
        False,
        List[UInt32](),
        List[UInt32](),
        False,
        UInt32(0),
    )
    assert_true(len(path) > 0)
    # No point should go through the blocked circle's center.
    var hit = False
    for idx in path:
        var p = idx_to_coords(idx, g.width, g.height)
        if p.x == 3 and p.y == 3:
            hit = True
            break
    assert_true(not hit)


def test_astar_can_use_via_transition():
    var g = Grid(2, 3, 3)
    var ws = AStarWorkspace(g.layers * g.width * g.height)
    var start = g.idx(0, 1, 1)
    var goal = g.idx(1, 1, 1)
    var path = route_a_star(
        ws,
        g,
        start,
        goal,
        UInt32(1),
        UInt64(0),
        False,
        UInt32(5),
        UInt32(0),
        UInt32(0),
        UInt32(0),
        0,
        UInt32(100),
        False,
        False,
        False,
        UInt32(0),
        UInt16(0),
        UInt32(0),
        UInt32(0),
        False,
        List[UInt32](),
        List[UInt32](),
        False,
        UInt32(0),
    )
    assert_true(len(path) >= 2)
    var a = idx_to_coords(path[0], g.width, g.height)
    var b = idx_to_coords(path[len(path) - 1], g.width, g.height)
    assert_equal(a.layer, 0)
    assert_equal(b.layer, 1)


def main():
    TestSuite.discover_tests[__functions_in_module()]().run()
