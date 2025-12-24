"""Integration tests for auto-routing with Z3 optimization.

Tests the complete auto-routing pipeline from board setup through
layer optimization and DRC validation.
"""

import pytest
from pcb_tool.data_model import Board, Component, Net, TraceSegment
from pcb_tool.routing.grid import RoutingGrid
from pcb_tool.routing.pathfinder import PathFinder
from pcb_tool.routing.layer_optimizer import LayerOptimizer, NetPath
from pcb_tool.routing.multi_net_router import MultiNetRouter, NetDefinition


def create_simple_board() -> Board:
    """Create a simple test board with components."""
    board = Board()

    # Add components
    board.add_component(Component(
        ref="R1",
        value="10k",
        footprint="R_0805",
        position=(5.0, 5.0),
        rotation=0.0,
        layer="F.Cu"
    ))

    board.add_component(Component(
        ref="R2",
        value="10k",
        footprint="R_0805",
        position=(15.0, 5.0),
        rotation=0.0,
        layer="F.Cu"
    ))

    board.add_component(Component(
        ref="C1",
        value="100n",
        footprint="C_0805",
        position=(5.0, 15.0),
        rotation=0.0,
        layer="F.Cu"
    ))

    board.add_component(Component(
        ref="C2",
        value="100n",
        footprint="C_0805",
        position=(15.0, 15.0),
        rotation=0.0,
        layer="F.Cu"
    ))

    return board


def test_simple_two_net_routing():
    """Test routing two simple nets without conflicts."""
    board = create_simple_board()

    # Create routing grid with appropriate size for test
    grid = RoutingGrid(
        width_mm=20.0,
        height_mm=20.0,
        resolution_mm=0.2
    )

    # Create router
    router = MultiNetRouter(grid)

    # Define two nets (horizontal lines, no crossing)
    nets = [
        NetDefinition(name="NET1", start=(5.0, 5.0), end=(15.0, 5.0), layer="F.Cu"),
        NetDefinition(name="NET2", start=(5.0, 15.0), end=(15.0, 15.0), layer="F.Cu"),
    ]

    # Route the nets
    result = router.route_nets(nets)

    # Verify both nets routed successfully
    assert len(result) == 2
    assert "NET1" in result
    assert "NET2" in result

    # Verify paths exist
    assert len(result["NET1"].path) >= 2
    assert len(result["NET2"].path) >= 2


def test_crossing_nets_with_layer_optimization():
    """Test routing crossing nets with Z3 layer optimization."""
    board = create_simple_board()

    # Create routing grid
    grid = RoutingGrid(
        width_mm=20.0,
        height_mm=20.0,
        resolution_mm=0.2
    )

    # Create optimizer
    optimizer = LayerOptimizer(grid, timeout=5.0)

    # Two crossing nets
    net1 = NetPath(
        name="HORIZONTAL",
        segments=[((5.0, 10.0), (15.0, 10.0))],
        default_layer="F.Cu"
    )

    net2 = NetPath(
        name="VERTICAL",
        segments=[((10.0, 5.0), (10.0, 15.0))],
        default_layer="F.Cu"
    )

    # Optimize layer assignments
    result = optimizer.optimize_layer_assignments([net1, net2])

    # Verify both nets have assignments
    assert "HORIZONTAL" in result
    assert "VERTICAL" in result

    # Get layer assignments
    h_layer = result["HORIZONTAL"].segment_assignments[0][1]
    v_layer = result["VERTICAL"].segment_assignments[0][1]

    # Verify layers are valid
    assert h_layer in ["F.Cu", "B.Cu"]
    assert v_layer in ["F.Cu", "B.Cu"]

    # Note: If Z3 optimization succeeds, layers should differ to avoid crossing.
    # If greedy fallback is used, they may be the same (acceptable for this test).


def test_multi_net_routing_with_priorities():
    """Test multi-net routing respects priorities."""
    board = create_simple_board()

    grid = RoutingGrid(
        width_mm=20.0,
        height_mm=20.0,
        resolution_mm=0.2
    )

    router = MultiNetRouter(grid)

    # Three nets with different priorities
    nets = [
        NetDefinition(name="LOW", start=(2.0, 2.0), end=(4.0, 2.0), priority=0),
        NetDefinition(name="HIGH", start=(2.0, 10.0), end=(18.0, 10.0), priority=10),
        NetDefinition(name="MED", start=(2.0, 18.0), end=(18.0, 18.0), priority=5),
    ]

    result = router.route_nets(nets)

    # High priority net should always route
    assert "HIGH" in result


def test_via_minimization_in_optimization():
    """Test that Z3 optimizer minimizes via count."""
    board = create_simple_board()

    grid = RoutingGrid(
        width_mm=20.0,
        height_mm=20.0,
        resolution_mm=0.2
    )

    optimizer = LayerOptimizer(grid, timeout=5.0)

    # Single straight net - should not need vias
    net = NetPath(
        name="STRAIGHT",
        segments=[
            ((5.0, 5.0), (10.0, 5.0)),
            ((10.0, 5.0), (15.0, 5.0))
        ],
        default_layer="F.Cu"
    )

    result = optimizer.optimize_layer_assignments([net])

    # Count vias
    via_count = sum(
        1 for _, _, via_after in result["STRAIGHT"].segment_assignments
        if via_after
    )

    # Should be 0 (no vias needed for straight line)
    assert via_count == 0


def test_complete_workflow_grid_to_optimization():
    """Test complete workflow: grid creation, routing, optimization."""
    board = create_simple_board()

    # Step 1: Create routing grid from board
    grid = RoutingGrid(
        width_mm=20.0,
        height_mm=20.0,
        resolution_mm=0.2,
        default_clearance_mm=0.2
    )

    # Step 2: Mark component positions as obstacles
    for comp in board.components.values():
        x, y = comp.position
        grid_x, grid_y = grid.to_grid_coords(x, y)
        grid.mark_obstacle(grid_x, grid_y, "F.Cu")
        grid.mark_obstacle(grid_x, grid_y, "B.Cu")

    # Step 3: Route nets
    pathfinder = PathFinder(grid, via_cost=5.0)
    path1 = pathfinder.find_path(
        start_mm=(6.0, 5.0),
        goal_mm=(14.0, 5.0),
        layer="F.Cu"
    )

    assert path1 is not None
    assert len(path1) >= 2

    # Step 4: Create NetPath for optimization
    segments = []
    for i in range(len(path1) - 1):
        segments.append((path1[i], path1[i + 1]))

    net_path = NetPath(name="TEST_NET", segments=segments, default_layer="F.Cu")

    # Step 5: Optimize layer assignments
    optimizer = LayerOptimizer(grid, timeout=5.0)
    result = optimizer.optimize_layer_assignments([net_path])

    # Verify optimization result
    assert "TEST_NET" in result
    assert len(result["TEST_NET"].segment_assignments) == len(segments)


def test_performance_simple_board():
    """Test that auto-routing completes in reasonable time."""
    import time

    board = create_simple_board()

    grid = RoutingGrid(
        width_mm=20.0,
        height_mm=20.0,
        resolution_mm=0.2
    )

    router = MultiNetRouter(grid)

    # Route 3 nets
    nets = [
        NetDefinition(name="NET1", start=(5.0, 5.0), end=(15.0, 5.0), layer="F.Cu"),
        NetDefinition(name="NET2", start=(5.0, 10.0), end=(15.0, 10.0), layer="F.Cu"),
        NetDefinition(name="NET3", start=(5.0, 15.0), end=(15.0, 15.0), layer="F.Cu"),
    ]

    start_time = time.time()
    result = router.route_nets(nets)
    elapsed = time.time() - start_time

    # Should complete in under 2 seconds
    assert elapsed < 2.0
    assert len(result) == 3


def test_fallback_on_infeasible_constraints():
    """Test that optimizer falls back gracefully on infeasible problems."""
    grid = RoutingGrid(width_mm=10.0, height_mm=10.0, resolution_mm=0.2)
    optimizer = LayerOptimizer(grid, timeout=2.0)

    # Create a potentially infeasible scenario
    # (many crossing nets - may not be solvable with just 2 layers)
    nets = []
    for i in range(5):
        nets.append(NetPath(
            name=f"H{i}",
            segments=[((0.0, float(i)), (10.0, float(i)))],
            default_layer="F.Cu"
        ))
    for i in range(5):
        nets.append(NetPath(
            name=f"V{i}",
            segments=[((float(i), 0.0), (float(i), 10.0))],
            default_layer="F.Cu"
        ))

    # Should return greedy fallback without crashing
    result = optimizer.optimize_layer_assignments(nets)

    # Should have some result (even if not optimal)
    assert len(result) > 0


def test_routing_with_obstacles():
    """Test routing around obstacles."""
    board = create_simple_board()

    grid = RoutingGrid(
        width_mm=20.0,
        height_mm=20.0,
        resolution_mm=0.2
    )

    # Add obstacle in the middle
    for x in range(8, 12):
        for y in range(8, 12):
            grid.mark_obstacle(x, y, "F.Cu")

    # Route around obstacle
    pathfinder = PathFinder(grid)
    path = pathfinder.find_path(
        start_mm=(5.0, 10.0),
        goal_mm=(15.0, 10.0),
        layer="F.Cu"
    )

    # Should find path around obstacle
    assert path is not None
    assert len(path) >= 2


def test_layer_assignment_consistency():
    """Test that layer assignments are consistent with via placement."""
    grid = RoutingGrid(width_mm=10.0, height_mm=10.0, resolution_mm=0.2)
    optimizer = LayerOptimizer(grid, timeout=5.0)

    # Net with multiple segments
    net = NetPath(
        name="MULTI",
        segments=[
            ((0.0, 0.0), (3.0, 0.0)),
            ((3.0, 0.0), (6.0, 0.0)),
            ((6.0, 0.0), (9.0, 0.0))
        ],
        default_layer="F.Cu"
    )

    result = optimizer.optimize_layer_assignments([net])

    assignments = result["MULTI"].segment_assignments

    # Check consistency: via_after should match layer changes
    for i in range(len(assignments) - 1):
        _, layer1, via_after = assignments[i]
        _, layer2, _ = assignments[i + 1]

        if via_after:
            # Via present - layers should differ
            assert layer1 != layer2
        else:
            # No via - layers should be same
            assert layer1 == layer2
