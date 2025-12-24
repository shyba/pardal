"""
Tests for net rip-up and re-route functionality.

Tests the ability to remove a net's routing and forbidden zones,
allowing re-routing with different parameters.
"""

import pytest
from pcb_tool.routing.grid import RoutingGrid
from pcb_tool.routing.multi_net_router import MultiNetRouter, NetDefinition


def test_remove_net_clears_forbidden_zones():
    """Test that removing a net clears its forbidden zones.

    After routing a net and then removing it, the forbidden zones
    should be cleared from the grid.
    """
    grid = RoutingGrid(width_mm=50, height_mm=50, resolution_mm=0.5)
    router = MultiNetRouter(grid)

    # Route a net
    net_def = NetDefinition(name="NET1", start=(10, 25), end=(40, 25), layer="F.Cu")
    routed = router.route_nets([net_def])

    # Verify net was routed
    assert "NET1" in routed

    # Verify forbidden zones were created
    initial_forbidden_count = len(grid.crossing_forbidden["F.Cu"])
    assert initial_forbidden_count > 0

    # Verify net is tracked in forbidden_zones_by_net
    assert "NET1" in grid.forbidden_zones_by_net
    assert len(grid.forbidden_zones_by_net["NET1"]) > 0

    # Remove the net's routing
    router.remove_net_routing("NET1")

    # Verify forbidden zones were removed
    final_forbidden_count = len(grid.crossing_forbidden["F.Cu"])
    assert final_forbidden_count < initial_forbidden_count

    # Verify net is no longer tracked
    assert "NET1" not in grid.forbidden_zones_by_net


def test_rip_up_and_reroute_different_order():
    """Test rip-up clears forbidden zones, allowing different routing.

    Route A then B in order 1. In a fresh grid, route B then A in order 2.
    Both orders should succeed, demonstrating that removal works.
    """
    # Order 1: Route A then B
    grid1 = RoutingGrid(width_mm=50, height_mm=50, resolution_mm=0.5)
    router1 = MultiNetRouter(grid1)

    net_a = NetDefinition(name="A", start=(10, 20), end=(40, 20), layer="F.Cu")
    net_b = NetDefinition(name="B", start=(10, 30), end=(40, 30), layer="F.Cu")

    routed1 = router1.route_nets([net_a, net_b])
    assert "A" in routed1
    assert "B" in routed1

    # Order 2: Route B then A (with rip-up)
    grid2 = RoutingGrid(width_mm=50, height_mm=50, resolution_mm=0.5)
    router2 = MultiNetRouter(grid2)

    # Route both B and A
    routed2 = router2.route_nets([net_b, net_a])
    assert "B" in routed2
    assert "A" in routed2

    # Test rip-up clears zones: remove B, verify its zones gone
    assert "B" in grid2.forbidden_zones_by_net
    router2.remove_net_routing("B")
    assert "B" not in grid2.forbidden_zones_by_net
    # A's zones should still exist
    assert "A" in grid2.forbidden_zones_by_net


def test_remove_multiple_nets():
    """Test removing multiple nets independently.

    Route several nets, remove some, verify others remain.
    """
    grid = RoutingGrid(width_mm=50, height_mm=50, resolution_mm=0.5)
    router = MultiNetRouter(grid)

    # Route three nets
    net1 = NetDefinition(name="NET1", start=(10, 10), end=(40, 10), layer="F.Cu")
    net2 = NetDefinition(name="NET2", start=(10, 25), end=(40, 25), layer="F.Cu")
    net3 = NetDefinition(name="NET3", start=(10, 40), end=(40, 40), layer="F.Cu")

    routed = router.route_nets([net1, net2, net3])

    # All three should route
    assert "NET1" in routed
    assert "NET2" in routed
    assert "NET3" in routed

    # All three should be tracked in routed_nets
    assert "NET1" in router.routed_nets
    assert "NET2" in router.routed_nets
    assert "NET3" in router.routed_nets

    # All three should have forbidden zones
    assert "NET1" in grid.forbidden_zones_by_net
    assert "NET2" in grid.forbidden_zones_by_net
    assert "NET3" in grid.forbidden_zones_by_net

    # Remove NET2
    router.remove_net_routing("NET2")

    # NET2 should be removed
    assert "NET2" not in router.routed_nets
    assert "NET2" not in grid.forbidden_zones_by_net

    # NET1 and NET3 should remain
    assert "NET1" in router.routed_nets
    assert "NET3" in router.routed_nets
    assert "NET1" in grid.forbidden_zones_by_net
    assert "NET3" in grid.forbidden_zones_by_net

    # Remove NET1
    router.remove_net_routing("NET1")

    # Only NET3 should remain
    assert "NET1" not in router.routed_nets
    assert "NET3" in router.routed_nets
    assert "NET1" not in grid.forbidden_zones_by_net
    assert "NET3" in grid.forbidden_zones_by_net
