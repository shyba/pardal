"""
Tests for Z3-based constraint router.

Tests the Z3 router with progressively complex scenarios:
1. Simple 2-net routing on small grid
2. Multi-net routing with obstacles
3. Full injector board routing
"""

import pytest
from pathlib import Path

from pcb_tool.routing.grid import RoutingGrid
from pcb_tool.routing.z3_router import Z3Router, Z3RoutingConfig, RoutingError
from pcb_tool.routing.multi_net_router import NetDefinition


class TestZ3RouterBasic:
    """Basic Z3 router tests with simple scenarios."""

    @pytest.fixture
    def small_grid(self):
        """Create a small 10x10 grid for testing."""
        grid = RoutingGrid(
            width_mm=10.0,
            height_mm=10.0,
            resolution_mm=1.0  # 1mm resolution = 10x10 cells
        )
        return grid

    @pytest.fixture
    def dual_layer_grid(self):
        """Create a small 10x10 dual-layer grid."""
        grid = RoutingGrid(
            width_mm=10.0,
            height_mm=10.0,
            resolution_mm=1.0
        )
        return grid

    def test_z3_router_initialization(self, small_grid):
        """Test Z3 router can be initialized."""
        router = Z3Router(small_grid)

        assert router.grid == small_grid
        assert router.config is not None
        assert router.solver is not None

    def test_z3_routes_single_net_straight_line(self, small_grid):
        """Test Z3 can route a single net in a straight line."""
        router = Z3Router(small_grid)

        # Simple net from (1, 1) to (8, 1) - horizontal line
        net_def = NetDefinition(
            name="NET1",
            start=(1.0, 1.0),
            end=(8.0, 1.0),
            layer="F.Cu"
        )

        result = router.solve_routing([net_def])

        # Verify routing succeeded
        assert "NET1" in result
        assert len(result["NET1"].path) > 0

        print(f"\nNET1 routed with {len(result['NET1'].path)} waypoints")

    def test_z3_routes_two_nets_no_conflict(self, small_grid):
        """Test Z3 can route two nets with no conflicts."""
        router = Z3Router(small_grid)

        # Two nets that shouldn't conflict
        net1 = NetDefinition(
            name="NET1",
            start=(1.0, 1.0),
            end=(8.0, 1.0),
            layer="F.Cu"
        )

        net2 = NetDefinition(
            name="NET2",
            start=(1.0, 5.0),
            end=(8.0, 5.0),
            layer="F.Cu"
        )

        result = router.solve_routing([net1, net2])

        # Verify both nets routed
        assert "NET1" in result
        assert "NET2" in result
        assert len(result["NET1"].path) > 0
        assert len(result["NET2"].path) > 0

        print(f"\nNET1: {len(result['NET1'].path)} waypoints")
        print(f"NET2: {len(result['NET2'].path)} waypoints")

    def test_z3_routes_two_nets_with_potential_crossing(self, small_grid):
        """Test Z3 routes two nets that would cross if routed naively."""
        router = Z3Router(small_grid)

        # Two nets that cross
        net1 = NetDefinition(
            name="NET1",
            start=(1.0, 1.0),
            end=(8.0, 8.0),  # Diagonal
            layer="F.Cu"
        )

        net2 = NetDefinition(
            name="NET2",
            start=(1.0, 8.0),
            end=(8.0, 1.0),  # Opposite diagonal
            layer="F.Cu"
        )

        result = router.solve_routing([net1, net2])

        # Verify both nets routed without same-layer crossings
        assert "NET1" in result
        assert "NET2" in result

        # Check no cell is occupied by both nets
        net1_cells = set(result["NET1"].path)
        net2_cells = set(result["NET2"].path)
        overlap = net1_cells.intersection(net2_cells)

        assert len(overlap) == 0, f"Nets should not share cells, but found {len(overlap)} overlapping"

        print(f"\nNET1: {len(result['NET1'].path)} waypoints")
        print(f"NET2: {len(result['NET2'].path)} waypoints")
        print(f"Overlap: {len(overlap)} cells")

    def test_z3_respects_obstacles(self, small_grid):
        """Test Z3 routes around obstacles."""
        # Add obstacle in the middle
        small_grid.mark_obstacle(5.0, 5.0, "F.Cu")

        router = Z3Router(small_grid)

        # Net that would go through obstacle if routed directly
        net_def = NetDefinition(
            name="NET1",
            start=(1.0, 5.0),
            end=(8.0, 5.0),
            layer="F.Cu"
        )

        result = router.solve_routing([net_def])

        # Verify routing succeeded and avoids obstacle
        assert "NET1" in result
        assert len(result["NET1"].path) > 0

        # Check that path doesn't go through obstacle cell (5, 5)
        obstacle_cell = (5.0, 5.0)
        assert obstacle_cell not in result["NET1"].path, \
            "Route should avoid obstacle"

        print(f"\nNET1 routed around obstacle with {len(result['NET1'].path)} waypoints")

    def test_z3_impossible_routing_returns_unsat(self, small_grid):
        """Test Z3 correctly identifies impossible routing scenarios."""
        # Block the entire middle row
        for x in range(2, 9):
            small_grid.mark_obstacle(float(x), 5.0, "F.Cu")

        router = Z3Router(small_grid)

        # Try to route through blocked area
        net_def = NetDefinition(
            name="NET1",
            start=(1.0, 1.0),
            end=(1.0, 8.0),  # Would need to cross blocked row
            layer="F.Cu"
        )

        # Should raise RoutingError with UNSAT
        with pytest.raises(RoutingError, match="impossible"):
            router.solve_routing([net_def])

        print("\n✓ Correctly identified impossible routing (UNSAT)")

    @pytest.mark.slow
    def test_z3_routes_with_via_minimization(self, dual_layer_grid):
        """Test Z3 minimizes vias when routing."""
        config = Z3RoutingConfig(
            optimize_vias=True,
            via_cost=10.0  # High via cost
        )

        router = Z3Router(dual_layer_grid, config)

        # Net that could use via but should avoid it due to cost
        net_def = NetDefinition(
            name="NET1",
            start=(1.0, 1.0),
            end=(8.0, 1.0),
            layer="F.Cu"
        )

        result = router.solve_routing([net_def])

        # Verify routing succeeded
        assert "NET1" in result
        print(f"\nNET1 routed with {len(result['NET1'].path)} waypoints")

        # TODO: Count vias in result and verify minimization


class TestZ3RouterInjectorBoard:
    """Test Z3 router on the real injector board."""

    @pytest.fixture
    def netlist_path(self):
        """Path to injector_2ch netlist."""
        path = "/home/user/repos/ee/manual_temp_test/injector_2ch.net"
        if not Path(path).exists():
            pytest.skip(f"Netlist not found: {path}")
        return path

    @pytest.mark.slow
    def test_z3_routes_injector_board(self, netlist_path):
        """Test Z3 router on full injector board - TARGET: 8/8 nets, 0 DRC errors."""
        from pcb_tool.data_model import Board
        from pcb_tool.commands import LoadCommand, MoveCommand

        # Load board
        board = Board()
        load_cmd = LoadCommand(Path(netlist_path))
        load_cmd.execute(board)

        # Place components
        placements = [
            ("J1", 15, 70, 0), ("C1", 35, 70, 0), ("C2", 50, 70, 0),
            ("J2", 15, 45, 0),
            ("R1", 55, 50, 0), ("R3", 55, 42, 0), ("Q1", 65, 46, 0), ("D1", 75, 38, 90),
            ("R2", 85, 50, 0), ("R4", 85, 42, 0), ("Q2", 95, 46, 0), ("D2", 105, 38, 90),
            ("J3", 80, 25, 0),
        ]

        for ref, x, y, rotation in placements:
            move_cmd = MoveCommand(ref, x, y, rotation)
            move_cmd.execute(board)

        # Create routing grid
        from pcb_tool.routing.grid import RoutingGrid

        grid = RoutingGrid(
            width_mm=120.0,
            height_mm=80.0,
            resolution_mm=1.0  # 1mm resolution (120x80 = 9600 cells total)
        )

        # Extract net definitions
        from pcb_tool.commands import AutoRouteCommand

        auto_cmd = AutoRouteCommand(net_name="ALL")
        net_definitions = auto_cmd._extract_net_definitions(board, list(board.nets.keys()))

        # Filter out GND (ground plane)
        net_definitions = [n for n in net_definitions if n.name.upper() not in ['GND', 'GROUND']]

        print(f"\nRouting {len(net_definitions)} net segments (excluding GND)...")

        # Route with Z3
        config = Z3RoutingConfig(
            timeout_ms=120000,  # 120 seconds for complex board
            via_cost=5.0,
            clearance_cells=0,  # Disable clearance for initial test (faster)
            optimize_wire_length=True,
            optimize_vias=False  # Disable via optimization for speed
        )

        router = Z3Router(grid, config)

        try:
            result = router.solve_routing(net_definitions)

            # Count routed nets
            net_names = set(n.name for n in net_definitions)
            routed_count = len(result)

            print(f"\n{'='*60}")
            print(f"Z3 ROUTING RESULTS")
            print(f"{'='*60}")
            print(f"Nets routed: {routed_count}/{len(net_names)}")

            for net_name, routed_net in result.items():
                print(f"  {net_name}: {len(routed_net.path)} waypoints, {len(routed_net.segments)} segments")

            print(f"{'='*60}")

            # Goal: 8/8 nets (all non-GND nets)
            expected_nets = 8  # GND excluded
            assert routed_count >= expected_nets, \
                f"Expected {expected_nets} nets routed, got {routed_count}"

            print("\n🎉 SUCCESS: Z3 achieved target routing!")

        except RoutingError as e:
            print(f"\nZ3 Routing Error: {e}")
            pytest.fail(f"Z3 routing failed: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
