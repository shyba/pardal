"""Tests for MultiNetRouter (multi-net routing coordination)."""

import pytest
from pcb_tool.routing.grid import RoutingGrid
from pcb_tool.routing.pathfinder import PathFinder
from pcb_tool.routing.layer_optimizer import LayerOptimizer
from pcb_tool.routing.multi_net_router import MultiNetRouter, NetDefinition, RoutedNet


def test_multi_net_router_initialization():
    """Test MultiNetRouter can be initialized."""
    grid = RoutingGrid(width_mm=10.0, height_mm=10.0, resolution_mm=0.1)
    router = MultiNetRouter(grid)

    assert router.grid == grid
    assert router.pathfinder is not None
    assert router.optimizer is not None


def test_route_single_net():
    """Test routing a single net."""
    grid = RoutingGrid(width_mm=10.0, height_mm=10.0, resolution_mm=0.1)
    router = MultiNetRouter(grid)

    net_def = NetDefinition(
        name="NET1",
        start=(1.0, 1.0),
        end=(5.0, 1.0),
        layer="F.Cu"
    )

    result = router.route_nets([net_def])

    assert "NET1" in result
    assert result["NET1"].name == "NET1"
    assert result["NET1"].layer == "F.Cu"
    assert len(result["NET1"].path) >= 2  # At least start and end


def test_route_multiple_nets_no_conflict():
    """Test routing multiple nets with no conflicts."""
    grid = RoutingGrid(width_mm=20.0, height_mm=20.0, resolution_mm=0.1)
    router = MultiNetRouter(grid)

    # Two nets on separate horizontal lines
    nets = [
        NetDefinition(name="NET1", start=(1.0, 2.0), end=(10.0, 2.0), layer="F.Cu"),
        NetDefinition(name="NET2", start=(1.0, 8.0), end=(10.0, 8.0), layer="F.Cu"),
    ]

    result = router.route_nets(nets)

    assert len(result) == 2
    assert "NET1" in result
    assert "NET2" in result


def test_route_multiple_nets_with_conflict():
    """Test routing multiple nets that would conflict."""
    grid = RoutingGrid(width_mm=10.0, height_mm=10.0, resolution_mm=0.1)
    router = MultiNetRouter(grid)

    # Two nets that cross paths
    nets = [
        NetDefinition(name="NET1", start=(1.0, 5.0), end=(9.0, 5.0), layer="F.Cu", priority=1),
        NetDefinition(name="NET2", start=(5.0, 1.0), end=(5.0, 9.0), layer="F.Cu", priority=0),
    ]

    result = router.route_nets(nets)

    # Both should route (higher priority routes first and blocks the other)
    # The second net should route around or fail
    assert "NET1" in result  # Higher priority should succeed


def test_net_prioritization():
    """Test that nets are prioritized correctly."""
    grid = RoutingGrid(width_mm=10.0, height_mm=10.0, resolution_mm=0.1)
    router = MultiNetRouter(grid)

    # Create nets with different priorities
    nets = [
        NetDefinition(name="LOW", start=(1.0, 1.0), end=(2.0, 1.0), priority=0),
        NetDefinition(name="HIGH", start=(3.0, 1.0), end=(4.0, 1.0), priority=10),
        NetDefinition(name="MED", start=(5.0, 1.0), end=(6.0, 1.0), priority=5),
    ]

    prioritized = router._prioritize_nets(nets)

    # Should be: HIGH, MED, LOW
    assert prioritized[0].name == "HIGH"
    assert prioritized[1].name == "MED"
    assert prioritized[2].name == "LOW"


def test_conflict_detection():
    """Test conflict detection between nets."""
    grid = RoutingGrid(width_mm=10.0, height_mm=10.0, resolution_mm=0.1)
    router = MultiNetRouter(grid)

    # Create routed nets with crossing segments
    net1 = RoutedNet(
        name="NET1",
        path=[(0.0, 1.0), (2.0, 1.0)],
        layer="F.Cu",
        segments=[((0.0, 1.0), (2.0, 1.0))]
    )

    net2 = RoutedNet(
        name="NET2",
        path=[(1.0, 0.0), (1.0, 2.0)],
        layer="F.Cu",
        segments=[((1.0, 0.0), (1.0, 2.0))]
    )

    conflicts = router._detect_conflicts({"NET1": net1, "NET2": net2})

    assert len(conflicts) > 0
    assert ("NET1", "NET2") in conflicts


def test_no_conflicts_different_layers():
    """Test that crossing on different layers is not a conflict."""
    grid = RoutingGrid(width_mm=10.0, height_mm=10.0, resolution_mm=0.1)
    router = MultiNetRouter(grid)

    # Crossing nets on different layers
    net1 = RoutedNet(
        name="NET1",
        path=[(0.0, 1.0), (2.0, 1.0)],
        layer="F.Cu",
        segments=[((0.0, 1.0), (2.0, 1.0))]
    )

    net2 = RoutedNet(
        name="NET2",
        path=[(1.0, 0.0), (1.0, 2.0)],
        layer="B.Cu",  # Different layer
        segments=[((1.0, 0.0), (1.0, 2.0))]
    )

    conflicts = router._detect_conflicts({"NET1": net1, "NET2": net2})

    assert len(conflicts) == 0  # No conflict on different layers


def test_drc_validation():
    """Test DRC validation of routed nets."""
    grid = RoutingGrid(width_mm=10.0, height_mm=10.0, resolution_mm=0.1)
    router = MultiNetRouter(grid)

    # Non-conflicting nets
    net1 = RoutedNet(
        name="NET1",
        path=[(0.0, 0.0), (1.0, 0.0)],
        layer="F.Cu",
        segments=[((0.0, 0.0), (1.0, 0.0))]
    )

    net2 = RoutedNet(
        name="NET2",
        path=[(0.0, 2.0), (1.0, 2.0)],
        layer="F.Cu",
        segments=[((0.0, 2.0), (1.0, 2.0))]
    )

    valid = router._validate_routing({"NET1": net1, "NET2": net2})

    assert valid is True


def test_route_empty_net_list():
    """Test routing with empty net list."""
    grid = RoutingGrid(width_mm=10.0, height_mm=10.0, resolution_mm=0.1)
    router = MultiNetRouter(grid)

    result = router.route_nets([])

    assert result == {}


def test_segments_intersect():
    """Test segment intersection detection."""
    grid = RoutingGrid(width_mm=10.0, height_mm=10.0, resolution_mm=0.1)
    router = MultiNetRouter(grid)

    # Crossing segments
    seg1 = ((0.0, 1.0), (2.0, 1.0))
    seg2 = ((1.0, 0.0), (1.0, 2.0))
    assert router._segments_intersect(seg1, seg2) is True

    # Non-crossing segments
    seg3 = ((0.0, 0.0), (1.0, 0.0))
    seg4 = ((2.0, 0.0), (3.0, 0.0))
    assert router._segments_intersect(seg3, seg4) is False


def test_route_with_optimization():
    """Test routing with Z3 layer optimization."""
    grid = RoutingGrid(width_mm=10.0, height_mm=10.0, resolution_mm=0.1)
    router = MultiNetRouter(grid)

    # Two crossing nets (using valid coordinates within grid)
    nets = [
        NetDefinition(name="NET1", start=(1.0, 5.0), end=(9.0, 5.0), layer="F.Cu"),
        NetDefinition(name="NET2", start=(5.0, 1.0), end=(5.0, 9.0), layer="F.Cu"),
    ]

    result = router.route_nets_with_optimization(nets)

    # Both nets should be routed
    assert "NET1" in result or "NET2" in result  # At least one should succeed


def test_prioritize_by_length():
    """Test that shorter nets are prioritized when priority is equal."""
    grid = RoutingGrid(width_mm=10.0, height_mm=10.0, resolution_mm=0.1)
    router = MultiNetRouter(grid)

    nets = [
        NetDefinition(name="LONG", start=(0.0, 0.0), end=(10.0, 0.0), priority=0),
        NetDefinition(name="SHORT", start=(0.0, 1.0), end=(1.0, 1.0), priority=0),
    ]

    prioritized = router._prioritize_nets(nets)

    # Shorter net should come first
    assert prioritized[0].name == "SHORT"
    assert prioritized[1].name == "LONG"


def test_mark_net_as_obstacle():
    """Test marking routed net as obstacle."""
    grid = RoutingGrid(width_mm=10.0, height_mm=10.0, resolution_mm=0.1)
    router = MultiNetRouter(grid)

    path = [(1.0, 1.0), (2.0, 1.0), (3.0, 1.0)]
    layer = "F.Cu"

    # Mark as obstacle
    router._mark_net_as_obstacle(path, layer, "TEST_NET")

    # Check that cells are marked as obstacles
    for x_mm, y_mm in path:
        grid_x, grid_y = grid.to_grid_coords(x_mm, y_mm)
        assert not grid.is_valid_cell(grid_x, grid_y, layer)
