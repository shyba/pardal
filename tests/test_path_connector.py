"""
Tests for Path Connector Module

Tests connecting Z3 waypoints using A* pathfinding.
"""

import pytest
from pcb_tool.routing.path_connector import PathConnector, ConnectedPath
from pcb_tool.routing.grid import RoutingGrid
from pcb_tool.routing.multi_net_router import NetDefinition, RoutedNet


def test_connect_simple_two_nets():
    """Test connecting two simple nets without conflicts."""
    # Create grid
    grid = RoutingGrid(width_mm=10.0, height_mm=10.0, resolution_mm=1.0)

    # Create Z3 result with two non-overlapping nets
    z3_result = {
        "net1": RoutedNet(
            name="net1",
            path=[(1.0, 1.0), (2.0, 1.0), (3.0, 1.0)],
            layer="F.Cu",
            segments=[((1.0, 1.0), (2.0, 1.0)), ((2.0, 1.0), (3.0, 1.0))]
        ),
        "net2": RoutedNet(
            name="net2",
            path=[(1.0, 5.0), (2.0, 5.0), (3.0, 5.0)],
            layer="F.Cu",
            segments=[((1.0, 5.0), (2.0, 5.0)), ((2.0, 5.0), (3.0, 5.0))]
        )
    }

    # Create net segments
    net_segments = {
        "net1": [NetDefinition(name="net1", start=(1.0, 1.0), end=(3.0, 1.0), layer="F.Cu")],
        "net2": [NetDefinition(name="net2", start=(1.0, 5.0), end=(3.0, 5.0), layer="F.Cu")]
    }

    # Connect paths
    connector = PathConnector(grid)
    result = connector.connect_all_nets(z3_result, net_segments)

    # Verify both nets connected successfully
    assert "net1" in result
    assert "net2" in result
    assert result["net1"].success
    assert result["net2"].success
    assert len(result["net1"].path) > 0
    assert len(result["net2"].path) > 0


def test_connect_mst_net_with_three_segments():
    """Test MST net with 3 segments sharing a point."""
    # Create grid
    grid = RoutingGrid(width_mm=20.0, height_mm=20.0, resolution_mm=1.0)

    # MST net: three segments meeting at center point (10, 10)
    # Segment 1: (5, 10) -> (10, 10)
    # Segment 2: (10, 10) -> (15, 10)
    # Segment 3: (10, 10) -> (10, 15)
    z3_result = {
        "mst_net": RoutedNet(
            name="mst_net",
            path=[(5.0, 10.0), (10.0, 10.0), (15.0, 10.0), (10.0, 15.0)],
            layer="F.Cu",
            segments=[
                ((5.0, 10.0), (10.0, 10.0)),
                ((10.0, 10.0), (15.0, 10.0)),
                ((10.0, 10.0), (10.0, 15.0))
            ]
        )
    }

    net_segments = {
        "mst_net": [
            NetDefinition(name="mst_net", start=(5.0, 10.0), end=(10.0, 10.0), layer="F.Cu"),
            NetDefinition(name="mst_net", start=(10.0, 10.0), end=(15.0, 10.0), layer="F.Cu"),
            NetDefinition(name="mst_net", start=(10.0, 10.0), end=(10.0, 15.0), layer="F.Cu")
        ]
    }

    # Connect paths
    connector = PathConnector(grid)
    result = connector.connect_all_nets(z3_result, net_segments)

    # Verify MST net connected successfully
    assert "mst_net" in result
    assert result["mst_net"].success
    assert len(result["mst_net"].path) > 0
    # Should have waypoints covering all three branches
    assert (10.0, 10.0) in result["mst_net"].path  # Center point


def test_paths_avoid_other_nets_cells():
    """Test that paths avoid other nets' cells."""
    # Create grid
    grid = RoutingGrid(width_mm=10.0, height_mm=10.0, resolution_mm=1.0)

    # Net1 at y=3 (does not block net2)
    # Net2 at y=7 (does not block net1)
    # Both should route successfully without conflicts
    z3_result = {
        "net1": RoutedNet(
            name="net1",
            path=[(1.0, 3.0), (5.0, 3.0), (9.0, 3.0)],
            layer="F.Cu",
            segments=[((1.0, 3.0), (5.0, 3.0)), ((5.0, 3.0), (9.0, 3.0))]
        ),
        "net2": RoutedNet(
            name="net2",
            path=[(1.0, 7.0), (5.0, 7.0), (9.0, 7.0)],
            layer="F.Cu",
            segments=[((1.0, 7.0), (5.0, 7.0)), ((5.0, 7.0), (9.0, 7.0))]
        )
    }

    net_segments = {
        "net1": [NetDefinition(name="net1", start=(1.0, 3.0), end=(9.0, 3.0), layer="F.Cu")],
        "net2": [NetDefinition(name="net2", start=(1.0, 7.0), end=(9.0, 7.0), layer="F.Cu")]
    }

    # Connect paths
    connector = PathConnector(grid)
    result = connector.connect_all_nets(z3_result, net_segments)

    # Both nets should connect successfully (no obstacles blocking each other)
    assert result["net1"].success
    assert result["net2"].success

    # Verify both have valid paths
    assert len(result["net1"].path) > 0
    assert len(result["net2"].path) > 0

    # Verify paths don't overlap (since they're on different y-coordinates)
    net1_cells = connector._path_to_cells(result["net1"].path, "F.Cu")
    net2_cells = connector._path_to_cells(result["net2"].path, "F.Cu")

    # Extract just the grid coordinates (without layer)
    net1_coords = {cell for cell, layer in net1_cells}
    net2_coords = {cell for cell, layer in net2_cells}

    # Should have no overlap since nets are on different y-coordinates
    assert len(net1_coords & net2_coords) == 0
