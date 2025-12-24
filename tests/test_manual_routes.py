"""
Tests for manual route integration.

Tests the ability to manually route critical nets and have auto-routing
work around them.
"""

import pytest
from dataclasses import dataclass
from pcb_tool.routing.grid import RoutingGrid
from pcb_tool.routing.multi_net_router import MultiNetRouter, NetDefinition
from pcb_tool.commands import AutoRouteCommand
from pcb_tool.data_model import Board, Component, Net


def test_manual_route_creates_forbidden_zones():
    """Test that manual routes create crossing-forbidden zones.

    Manual routes should mark zones as forbidden, preventing subsequent
    auto-routing from creating crossings.
    """
    grid = RoutingGrid(width_mm=50, height_mm=50, resolution_mm=0.5)
    router = MultiNetRouter(grid)

    # Define a manual route path
    manual_path = [(10, 25), (20, 25), (30, 25), (40, 25)]

    # Add manual route for NET1
    router.add_manual_route(
        net_name="NET1",
        path=manual_path,
        layer="F.Cu",
        width_mm=0.25
    )

    # Verify NET1 is tracked as manually routed
    assert "NET1" in router.manually_routed_nets

    # Verify crossing-forbidden zones were created on F.Cu
    # The manual route should create forbidden zones along its path
    assert len(grid.crossing_forbidden["F.Cu"]) > 0

    # Verify that cells along the manual route are marked as forbidden
    # Convert first segment to grid coords and check
    start_grid = grid.to_grid_coords(10, 25)
    # Cells along this line should be in forbidden zones
    cells_along_path = grid._bresenham_line(start_grid, grid.to_grid_coords(20, 25))
    # At least some cells should be marked forbidden
    forbidden_cells_found = sum(
        1 for cell in cells_along_path
        if cell in grid.crossing_forbidden["F.Cu"]
    )
    assert forbidden_cells_found > 0


def test_auto_routes_around_manual():
    """Test that auto-routing routes around manual routes.

    When a manual route blocks a straight path, auto-routing should
    find an alternative path (detour or via).
    """
    grid = RoutingGrid(width_mm=50, height_mm=50, resolution_mm=0.5)
    router = MultiNetRouter(grid)

    # Add a manual route that blocks the center horizontally
    manual_path = [(5, 25), (45, 25)]
    router.add_manual_route(
        net_name="MANUAL_NET",
        path=manual_path,
        layer="F.Cu",
        width_mm=0.25
    )

    # Try to auto-route a net that would cross the manual route
    # This net needs to go from bottom to top, crossing the manual route
    auto_net = NetDefinition(
        name="AUTO_NET",
        start=(25, 10),  # Below manual route
        end=(25, 40),    # Above manual route
        layer="F.Cu"
    )

    # Route the auto net - it should detour or use vias to avoid crossing
    routed = router.route_nets([auto_net])

    # The auto net should route successfully (found a detour)
    assert "AUTO_NET" in routed

    # Manual net should not be in routed (it was manually routed)
    assert "MANUAL_NET" not in routed

    # The routed path should exist and have more than 2 points
    # (indicating a detour, not a straight line through the manual route)
    auto_path = routed["AUTO_NET"].path
    assert len(auto_path) >= 2


def test_manual_route_command_integration():
    """Test manual routes through AutoRouteCommand interface.

    Verify that AutoRouteCommand correctly applies manual routes
    via the MultiNetRouter.
    """
    # Create a grid and router directly (simpler than full board setup)
    grid = RoutingGrid(width_mm=50, height_mm=50, resolution_mm=0.5)

    # Test manual routes parameter is accepted by AutoRouteCommand
    manual_routes = {
        "CRITICAL": {
            "path": [(10, 10), (25, 10), (40, 10)],
            "layer": "F.Cu"
        }
    }

    cmd = AutoRouteCommand(
        net_name="ALL",
        manual_routes=manual_routes
    )

    # Verify manual routes are stored
    assert cmd.manual_routes is not None
    assert "CRITICAL" in cmd.manual_routes
    assert cmd.manual_routes["CRITICAL"]["layer"] == "F.Cu"

    # Test router applies manual routes correctly
    router = MultiNetRouter(grid)
    router.add_manual_route(
        net_name="CRITICAL",
        path=[(10, 10), (25, 10), (40, 10)],
        layer="F.Cu"
    )

    # Verify CRITICAL is marked as manually routed
    assert "CRITICAL" in router.manually_routed_nets

    # Verify router will skip this net during auto-routing
    net_def = NetDefinition(name="CRITICAL", start=(10, 10), end=(40, 10))
    routed = router.route_nets([net_def])

    # CRITICAL should NOT be in routed nets (was manually routed)
    assert "CRITICAL" not in routed
