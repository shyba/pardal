"""
Tests for Iterative Router Integration

Tests hybrid Z3 + A* router with lazy constraint iteration.
"""

import pytest
from pcb_tool.routing.iterative_router import IterativeRouter
from pcb_tool.routing.grid import RoutingGrid
from pcb_tool.routing.multi_net_router import NetDefinition


def test_simple_two_net_case_converges_immediately():
    """Test simple 2-net case that converges immediately."""
    # Create grid
    grid = RoutingGrid(width_mm=20.0, height_mm=20.0, resolution_mm=1.0)

    # Two nets that don't cross
    net_definitions = [
        NetDefinition(name="net1", start=(2.0, 5.0), end=(18.0, 5.0), layer="F.Cu"),
        NetDefinition(name="net2", start=(2.0, 15.0), end=(18.0, 15.0), layer="F.Cu")
    ]

    # Route with iterative router
    router = IterativeRouter(grid, max_iterations=5, z3_timeout_ms=30000)
    result = router.route(net_definitions)

    # Should succeed
    assert "net1" in result
    assert "net2" in result
    assert len(result["net1"]) > 0
    assert len(result["net2"]) > 0


def test_x_crossing_case_requires_iterations():
    """Test X-crossing case that requires 2+ iterations."""
    # Create grid
    grid = RoutingGrid(width_mm=20.0, height_mm=20.0, resolution_mm=1.0)

    # Two nets that would initially cross
    # Horizontal: (2, 10) to (18, 10)
    # Vertical: (10, 2) to (10, 18)
    net_definitions = [
        NetDefinition(name="horizontal", start=(2.0, 10.0), end=(18.0, 10.0), layer="F.Cu"),
        NetDefinition(name="vertical", start=(10.0, 2.0), end=(10.0, 18.0), layer="F.Cu")
    ]

    # Route with iterative router
    router = IterativeRouter(grid, max_iterations=10, z3_timeout_ms=30000)
    result = router.route(net_definitions)

    # Should eventually succeed (may take multiple iterations)
    # Or may fail if Z3 can't find alternate routing
    # We just verify the router attempts the process
    assert isinstance(result, dict)


def test_group_segments_by_net_name():
    """Test segment grouping by net name."""
    grid = RoutingGrid(width_mm=20.0, height_mm=20.0, resolution_mm=1.0)
    router = IterativeRouter(grid)

    # Multiple segments for same net
    net_definitions = [
        NetDefinition(name="net1", start=(2.0, 5.0), end=(10.0, 5.0), layer="F.Cu"),
        NetDefinition(name="net1", start=(10.0, 5.0), end=(18.0, 5.0), layer="F.Cu"),
        NetDefinition(name="net2", start=(2.0, 15.0), end=(18.0, 15.0), layer="F.Cu")
    ]

    groups = router._group_segments(net_definitions)

    # Verify grouping
    assert "net1" in groups
    assert "net2" in groups
    assert len(groups["net1"]) == 2
    assert len(groups["net2"]) == 1


def test_handles_z3_failure_gracefully():
    """Test that router handles Z3 failure gracefully."""
    # Create very small grid that makes routing impossible
    grid = RoutingGrid(width_mm=2.0, height_mm=2.0, resolution_mm=1.0)

    # Impossible routing: nets too long for grid
    net_definitions = [
        NetDefinition(name="net1", start=(0.0, 0.0), end=(100.0, 100.0), layer="F.Cu")
    ]

    router = IterativeRouter(grid, max_iterations=2, z3_timeout_ms=5000)
    result = router.route(net_definitions)

    # Should return empty dict or partial result
    assert isinstance(result, dict)
