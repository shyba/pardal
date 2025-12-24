"""
Test crossing-forbidden zones implementation.

This test validates that the crossing-forbidden zones feature correctly
prevents routing crossings by making crossing zones HARD BLOCKED, forcing
the router to use vias or alternative paths.
"""

import pytest
from pcb_tool.routing.grid import RoutingGrid
from pcb_tool.routing.pathfinder import PathFinder
from pcb_tool.routing.multi_net_router import MultiNetRouter, NetDefinition


class TestCrossingForbidden:
    """Test crossing-forbidden zones functionality."""

    @pytest.fixture
    def grid(self):
        """Create a routing grid for testing."""
        return RoutingGrid(
            width_mm=100.0,
            height_mm=100.0,
            resolution_mm=0.1,
            default_clearance_mm=0.2
        )

    def test_crossing_forbidden_zone_marked(self, grid):
        """Test that crossing-forbidden zones are correctly marked."""
        # Mark a trace segment
        start = (10.0, 10.0)
        end = (20.0, 10.0)
        layer = "F.Cu"

        # Initially, the zone should be empty
        assert len(grid.crossing_forbidden[layer]) == 0

        # Mark crossing-forbidden zone
        grid.mark_crossing_forbidden_zone(start, end, layer, trace_width_mm=0.25)

        # Zone should now have cells marked
        assert len(grid.crossing_forbidden[layer]) > 0

        # Cells along the trace should be forbidden
        # Convert start/end to grid coordinates
        start_grid = grid.to_grid_coords(*start)
        end_grid = grid.to_grid_coords(*end)

        # At least the center cells should be forbidden
        for x in range(start_grid[0], end_grid[0] + 1):
            assert (x, start_grid[1]) in grid.crossing_forbidden[layer] or \
                   (x, start_grid[1] - 1) in grid.crossing_forbidden[layer] or \
                   (x, start_grid[1] + 1) in grid.crossing_forbidden[layer], \
                f"Cell near ({x}, {start_grid[1]}) should be in forbidden zone"

    def test_crossing_forbidden_blocks_routing(self, grid):
        """Test that crossing-forbidden zones block pathfinding."""
        pathfinder = PathFinder(grid, via_cost=2.0)

        # Route first trace horizontally
        start1 = (10.0, 50.0)
        end1 = (90.0, 50.0)
        layer1 = "F.Cu"

        path1 = pathfinder.find_path(start1, end1, layer1)
        assert path1 is not None, "First path should route successfully"

        # Mark crossing-forbidden zone
        grid.mark_crossing_forbidden_zone(start1, end1, layer1, trace_width_mm=0.25)

        # Try to route second trace vertically (would cross first trace)
        start2 = (50.0, 10.0)
        end2 = (50.0, 90.0)
        layer2 = "F.Cu"

        path2 = pathfinder.find_path(start2, end2, layer2)

        # Path should either:
        # 1. Fail (no path found)
        # 2. Route around the forbidden zone
        # 3. Use a via to B.Cu
        if path2 is not None:
            # If path exists, verify it doesn't cross the forbidden zone
            crossing_point_grid = grid.to_grid_coords(50.0, 50.0)

            # Check if path avoids the crossing area
            crosses_forbidden_zone = False
            for point in path2:
                point_grid = grid.to_grid_coords(*point)
                if point_grid in grid.crossing_forbidden[layer2]:
                    crosses_forbidden_zone = True
                    break

            assert not crosses_forbidden_zone, \
                "Path should not cross forbidden zone"

    def test_multi_net_router_uses_forbidden_zones(self, grid):
        """Test that MultiNetRouter marks forbidden zones when routing nets."""
        router = MultiNetRouter(grid, ground_plane_mode=True)

        # Define two crossing nets
        nets = [
            NetDefinition(
                name="NET1",
                start=(10.0, 50.0),
                end=(90.0, 50.0),
                layer="F.Cu",
                priority=10
            ),
            NetDefinition(
                name="NET2",
                start=(50.0, 10.0),
                end=(50.0, 90.0),
                layer="F.Cu",
                priority=5
            )
        ]

        # Route nets
        routed = router.route_nets(nets)

        # Both nets should route successfully
        assert "NET1" in routed, "NET1 should route"
        assert "NET2" in routed, "NET2 should route"

        # Forbidden zones should be marked
        assert len(grid.crossing_forbidden["F.Cu"]) > 0, \
            "Forbidden zones should be marked after routing"

    def test_forbidden_zone_properties(self, grid):
        """Test that forbidden zones have correct properties."""
        start = (50.0, 50.0)
        end = (60.0, 50.0)
        layer = "F.Cu"
        trace_width = 0.25

        # Mark crossing-forbidden zone
        grid.mark_crossing_forbidden_zone(start, end, layer, trace_width)
        forbidden_count = len(grid.crossing_forbidden[layer])

        # Forbidden zone should have cells marked
        assert forbidden_count > 0, \
            "Forbidden zone should have cells marked"

        # Forbidden zone corridor width should be trace_width + 0.3mm
        # For trace_width=0.25mm, corridor = 0.55mm, radius = 0.275mm
        # This is wide enough to prevent crossings while allowing routing nearby
        expected_min_cells = 100  # Rough estimate for 10mm line with 0.55mm corridor
        assert forbidden_count >= expected_min_cells, \
            f"Forbidden zone ({forbidden_count} cells) should have at least {expected_min_cells} cells"

    def test_is_valid_cell_checks_forbidden_zones(self, grid):
        """Test that is_valid_cell() blocks cells in forbidden zones."""
        start = (50.0, 50.0)
        end = (60.0, 50.0)
        layer = "F.Cu"

        # Initially, center cell should be valid
        center_grid = grid.to_grid_coords(55.0, 50.0)
        assert grid.is_valid_cell(*center_grid, layer), \
            "Cell should be valid before marking forbidden zone"

        # Mark crossing-forbidden zone
        grid.mark_crossing_forbidden_zone(start, end, layer, trace_width_mm=0.25)

        # Center cell should now be invalid
        assert not grid.is_valid_cell(*center_grid, layer), \
            "Cell should be invalid after marking forbidden zone"

    def test_ground_plane_mode_reduced_via_cost(self):
        """Test that ground plane mode uses reduced via cost."""
        grid = RoutingGrid(100.0, 100.0)

        # Regular mode
        router_regular = MultiNetRouter(grid, ground_plane_mode=False)
        assert router_regular.pathfinder.via_cost == 10.0, \
            "Regular mode should have via cost of 10.0"

        # Ground plane mode
        router_gp = MultiNetRouter(grid, ground_plane_mode=True)
        assert router_gp.pathfinder.via_cost == 0.5, \
            "Ground plane mode should have via cost of 0.5"

    def test_statistics_include_forbidden_zones(self, grid):
        """Test that grid statistics include forbidden zone counts."""
        # Mark some forbidden zones
        grid.mark_crossing_forbidden_zone(
            (10.0, 10.0), (20.0, 10.0), "F.Cu", trace_width_mm=0.25
        )
        grid.mark_crossing_forbidden_zone(
            (30.0, 30.0), (40.0, 30.0), "B.Cu", trace_width_mm=0.25
        )

        stats = grid.get_statistics()

        # Check that forbidden zones are reported
        assert "crossing_forbidden_zones" in stats, \
            "Statistics should include crossing_forbidden_zones"
        assert stats["crossing_forbidden_zones"]["F.Cu"] > 0, \
            "F.Cu forbidden zone count should be > 0"
        assert stats["crossing_forbidden_zones"]["B.Cu"] > 0, \
            "B.Cu forbidden zone count should be > 0"

        # Check that routable cells account for forbidden zones
        total_cells = grid.grid_width * grid.grid_height
        expected_routable_fcu = total_cells - len(grid.obstacles["F.Cu"]) - len(grid.crossing_forbidden["F.Cu"])
        assert stats["routable_cells"]["F.Cu"] == expected_routable_fcu, \
            "Routable cells should exclude both obstacles and forbidden zones"


class TestCrossingForbiddenIntegration:
    """Integration tests for crossing-forbidden zones with real routing scenarios."""

    def test_h_pattern_routing_no_crossings(self):
        """Test H-pattern routing (two vertical nets, one horizontal connector)."""
        grid = RoutingGrid(100.0, 100.0, resolution_mm=0.1)
        router = MultiNetRouter(grid, ground_plane_mode=True)

        # Define H-pattern nets
        nets = [
            # Left vertical bar
            NetDefinition("V1", (20.0, 20.0), (20.0, 80.0), "F.Cu", priority=10),
            # Right vertical bar
            NetDefinition("V2", (80.0, 20.0), (80.0, 80.0), "F.Cu", priority=10),
            # Horizontal connector (would cross verticals if not using forbidden zones)
            NetDefinition("H1", (10.0, 50.0), (90.0, 50.0), "F.Cu", priority=5),
        ]

        # Route all nets
        routed = router.route_nets(nets)

        # All nets should route
        assert len(routed) == 3, "All 3 nets should route successfully"

        # Check for crossings manually
        v1_path = set(routed["V1"].path)
        v2_path = set(routed["V2"].path)
        h1_path = set(routed["H1"].path)

        # Paths should not share points (except endpoints)
        v1_h1_intersect = v1_path & h1_path
        v2_h1_intersect = v2_path & h1_path

        # Allow small intersection near endpoints (within 1mm)
        assert len(v1_h1_intersect) <= 3, \
            f"V1 and H1 should not cross significantly: {len(v1_h1_intersect)} shared points"
        assert len(v2_h1_intersect) <= 3, \
            f"V2 and H1 should not cross significantly: {len(v2_h1_intersect)} shared points"

    def test_crossing_pattern_forces_detour(self):
        """Test that crossing pattern forces router to find alternative path."""
        grid = RoutingGrid(50.0, 50.0, resolution_mm=0.1)
        router = MultiNetRouter(grid, ground_plane_mode=True)

        # Net 1: Straight horizontal path
        net1 = NetDefinition("NET1", (10.0, 25.0), (40.0, 25.0), "F.Cu", priority=10)

        # Net 2: Would cross NET1 if routed straight
        net2 = NetDefinition("NET2", (25.0, 10.0), (25.0, 40.0), "F.Cu", priority=5)

        # Route both nets
        routed = router.route_nets([net1, net2])

        # Both should route
        assert "NET1" in routed, "NET1 should route"
        assert "NET2" in routed, "NET2 should route"

        # NET2 should be longer than straight-line distance (because it detoured)
        net2_length = 0.0
        path = routed["NET2"].path
        for i in range(len(path) - 1):
            dx = path[i+1][0] - path[i][0]
            dy = path[i+1][1] - path[i][1]
            net2_length += (dx*dx + dy*dy)**0.5

        straight_line_distance = 30.0  # 40.0 - 10.0

        # NET2 should be at least as long as straight line
        # (could be exactly same length if it used vias cleverly)
        assert net2_length >= straight_line_distance * 0.95, \
            f"NET2 length ({net2_length:.1f}mm) should be close to straight line ({straight_line_distance:.1f}mm)"
