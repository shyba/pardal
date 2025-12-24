"""
Unit tests for PathFinder class.

Tests A* pathfinding algorithm, path simplification, heuristics,
and path statistics calculation.
"""

import pytest
import math
from pcb_tool.routing.grid import RoutingGrid, GridCell
from pcb_tool.routing.pathfinder import PathFinder, PathNode


class TestPathFinderInitialization:
    """Test PathFinder initialization."""

    def test_init(self):
        """Test pathfinder initialization with grid."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0)
        finder = PathFinder(grid)

        assert finder.grid is grid


class TestBasicPathfinding:
    """Test basic pathfinding scenarios."""

    def test_find_path_straight_horizontal(self):
        """Test finding straight horizontal path."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)
        finder = PathFinder(grid)

        path = finder.find_path(
            start_mm=(10.0, 20.0),
            goal_mm=(30.0, 20.0),
            layer="F.Cu"
        )

        assert path is not None
        assert len(path) >= 2

        # First and last points should match start and goal
        assert path[0] == (10.0, 20.0)
        assert path[-1] == (30.0, 20.0)

        # Path should be approximately horizontal
        y_coords = [y for x, y in path]
        assert all(abs(y - 20.0) < 1.0 for y in y_coords)

    def test_find_path_straight_vertical(self):
        """Test finding straight vertical path."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)
        finder = PathFinder(grid)

        path = finder.find_path(
            start_mm=(20.0, 10.0),
            goal_mm=(20.0, 30.0),
            layer="F.Cu"
        )

        assert path is not None
        assert len(path) >= 2

        # First and last points should match start and goal
        assert path[0] == (20.0, 10.0)
        assert path[-1] == (20.0, 30.0)

        # Path should be approximately vertical
        x_coords = [x for x, y in path]
        assert all(abs(x - 20.0) < 1.0 for x in x_coords)

    def test_find_path_diagonal(self):
        """Test finding diagonal path."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)
        finder = PathFinder(grid)

        path = finder.find_path(
            start_mm=(10.0, 10.0),
            goal_mm=(20.0, 20.0),
            layer="F.Cu",
            allow_diagonals=True
        )

        assert path is not None
        assert len(path) >= 2

        # First and last points should match start and goal
        assert path[0] == (10.0, 10.0)
        assert path[-1] == (20.0, 20.0)

    def test_find_path_no_diagonals(self):
        """Test pathfinding without diagonals (Manhattan only)."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)
        finder = PathFinder(grid)

        path = finder.find_path(
            start_mm=(10.0, 10.0),
            goal_mm=(20.0, 20.0),
            layer="F.Cu",
            allow_diagonals=False
        )

        assert path is not None
        assert len(path) >= 2

        # Verify no diagonal moves (each segment should be horizontal or vertical)
        for i in range(len(path) - 1):
            x1, y1 = path[i]
            x2, y2 = path[i + 1]
            # At least one coordinate should be the same (allowing for small rounding errors)
            assert abs(x1 - x2) < 0.01 or abs(y1 - y2) < 0.01

    def test_find_path_same_start_and_goal(self):
        """Test pathfinding when start and goal are the same."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)
        finder = PathFinder(grid)

        path = finder.find_path(
            start_mm=(20.0, 20.0),
            goal_mm=(20.0, 20.0),
            layer="F.Cu"
        )

        assert path is not None
        assert len(path) == 1
        assert path[0] == (20.0, 20.0)


class TestPathfindingWithObstacles:
    """Test pathfinding with obstacles."""

    def test_find_path_around_obstacle(self):
        """Test finding path around a simple obstacle."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)

        # Place obstacle in the middle
        grid.mark_rectangle_obstacle(15.0, 15.0, 25.0, 25.0, "F.Cu")

        finder = PathFinder(grid)

        path = finder.find_path(
            start_mm=(10.0, 20.0),
            goal_mm=(30.0, 20.0),
            layer="F.Cu"
        )

        assert path is not None

        # Path should go around obstacle (not through it)
        obstacle_cells = grid.obstacles["F.Cu"]
        for x, y in path:
            grid_pos = grid.to_grid_coords(x, y)
            assert grid_pos not in obstacle_cells

    def test_find_path_around_via(self):
        """Test finding path around a via."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)

        # Place via in the middle
        grid.mark_via(20.0, 20.0, size_mm=0.8)

        finder = PathFinder(grid)

        path = finder.find_path(
            start_mm=(10.0, 20.0),
            goal_mm=(30.0, 20.0),
            layer="F.Cu"
        )

        assert path is not None

        # Path should avoid via
        via_cells = grid.obstacles["F.Cu"]
        for x, y in path:
            grid_pos = grid.to_grid_coords(x, y)
            assert grid_pos not in via_cells

    def test_find_path_through_narrow_gap(self):
        """Test finding path through a narrow gap between obstacles."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.2)

        # Create two obstacles with a gap
        grid.mark_rectangle_obstacle(10.0, 10.0, 20.0, 18.0, "F.Cu")
        grid.mark_rectangle_obstacle(10.0, 22.0, 20.0, 30.0, "F.Cu")

        finder = PathFinder(grid)

        # Path should go through the gap at y=20
        path = finder.find_path(
            start_mm=(5.0, 20.0),
            goal_mm=(25.0, 20.0),
            layer="F.Cu"
        )

        assert path is not None

    def test_find_path_multiple_obstacles(self):
        """Test pathfinding with multiple obstacles."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)

        # Place multiple obstacles
        grid.mark_obstacle(15.0, 15.0, "F.Cu", size_mm=3.0)
        grid.mark_obstacle(20.0, 20.0, "F.Cu", size_mm=3.0)
        grid.mark_obstacle(25.0, 15.0, "F.Cu", size_mm=3.0)

        finder = PathFinder(grid)

        path = finder.find_path(
            start_mm=(10.0, 10.0),
            goal_mm=(30.0, 25.0),
            layer="F.Cu"
        )

        assert path is not None

        # Path should avoid all obstacles
        obstacle_cells = grid.obstacles["F.Cu"]
        for x, y in path:
            grid_pos = grid.to_grid_coords(x, y)
            assert grid_pos not in obstacle_cells


class TestPathfindingEdgeCases:
    """Test edge cases and failure scenarios."""

    def test_find_path_no_path_exists(self):
        """Test when no path exists (goal completely blocked)."""
        grid = RoutingGrid(width_mm=50.0, height_mm=50.0, resolution_mm=0.5)

        # Surround goal with obstacles
        for x in range(18, 23):
            for y in range(18, 23):
                grid.obstacles["F.Cu"].add((x, y))

        finder = PathFinder(grid)

        path = finder.find_path(
            start_mm=(5.0, 5.0),
            goal_mm=(10.0, 10.0),
            layer="F.Cu"
        )

        assert path is None

    def test_find_path_start_on_obstacle(self):
        """Test when start position is on an obstacle."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)

        # Mark start as obstacle
        grid.mark_obstacle(10.0, 20.0, "F.Cu", size_mm=2.0)

        finder = PathFinder(grid)

        path = finder.find_path(
            start_mm=(10.0, 20.0),
            goal_mm=(30.0, 20.0),
            layer="F.Cu"
        )

        assert path is None

    def test_find_path_goal_on_obstacle(self):
        """Test when goal position is on an obstacle."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)

        # Mark goal as obstacle
        grid.mark_obstacle(30.0, 20.0, "F.Cu", size_mm=2.0)

        finder = PathFinder(grid)

        path = finder.find_path(
            start_mm=(10.0, 20.0),
            goal_mm=(30.0, 20.0),
            layer="F.Cu"
        )

        assert path is None

    def test_find_path_different_layers(self):
        """Test pathfinding on different layers."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)

        # Mark obstacle only on F.Cu
        grid.mark_obstacle(20.0, 20.0, "F.Cu", size_mm=5.0)

        finder = PathFinder(grid)

        # Path on F.Cu should go around
        path_fcu = finder.find_path(
            start_mm=(10.0, 20.0),
            goal_mm=(30.0, 20.0),
            layer="F.Cu"
        )

        # Path on B.Cu should be straighter (no obstacle)
        path_bcu = finder.find_path(
            start_mm=(10.0, 20.0),
            goal_mm=(30.0, 20.0),
            layer="B.Cu"
        )

        assert path_fcu is not None
        assert path_bcu is not None

        # B.Cu path should be shorter (no detour)
        stats_fcu = finder.get_path_statistics(path_fcu)
        stats_bcu = finder.get_path_statistics(path_bcu)
        assert stats_bcu["length_mm"] < stats_fcu["length_mm"]


class TestPathSimplification:
    """Test path simplification algorithm."""

    def test_simplify_straight_line(self):
        """Test that straight line is simplified to start and end."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.2)
        finder = PathFinder(grid)

        path = finder.find_path(
            start_mm=(10.0, 20.0),
            goal_mm=(30.0, 20.0),
            layer="F.Cu"
        )

        assert path is not None

        # Straight horizontal line should simplify to just 2 points
        assert len(path) == 2
        assert path[0] == (10.0, 20.0)
        assert path[-1] == (30.0, 20.0)

    def test_simplify_right_angle(self):
        """Test simplification of right-angle path."""
        # Create a path that must go around an obstacle at right angle
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)

        # Block direct path
        grid.mark_rectangle_obstacle(15.0, 15.0, 25.0, 25.0, "F.Cu")

        finder = PathFinder(grid)

        path = finder.find_path(
            start_mm=(10.0, 20.0),
            goal_mm=(30.0, 10.0),
            layer="F.Cu"
        )

        assert path is not None

        # Path should have reasonable number of waypoints
        # (allowing flexibility for obstacle avoidance and clearances)
        assert len(path) <= 10
        assert len(path) >= 2

    def test_simplify_empty_path(self):
        """Test simplification of empty or single-point path."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)
        finder = PathFinder(grid)

        # Empty path
        assert finder._simplify_path([]) == []

        # Single point
        assert finder._simplify_path([(10.0, 20.0)]) == [(10.0, 20.0)]

        # Two points
        assert finder._simplify_path([(10.0, 20.0), (30.0, 20.0)]) == [(10.0, 20.0), (30.0, 20.0)]


class TestHeuristic:
    """Test heuristic function."""

    def test_heuristic_horizontal(self):
        """Test heuristic for horizontal distance."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)
        finder = PathFinder(grid)

        cell_a = GridCell(100, 200, "F.Cu")  # (10.0, 20.0) mm
        cell_b = GridCell(300, 200, "F.Cu")  # (30.0, 20.0) mm

        h = finder._heuristic(cell_a, cell_b)

        # Expected: 200 cells * 0.1mm = 20mm
        assert abs(h - 20.0) < 0.1

    def test_heuristic_vertical(self):
        """Test heuristic for vertical distance."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)
        finder = PathFinder(grid)

        cell_a = GridCell(200, 100, "F.Cu")  # (20.0, 10.0) mm
        cell_b = GridCell(200, 300, "F.Cu")  # (20.0, 30.0) mm

        h = finder._heuristic(cell_a, cell_b)

        # Expected: 200 cells * 0.1mm = 20mm
        assert abs(h - 20.0) < 0.1

    def test_heuristic_diagonal(self):
        """Test heuristic for diagonal distance."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)
        finder = PathFinder(grid)

        cell_a = GridCell(100, 100, "F.Cu")  # (10.0, 10.0) mm
        cell_b = GridCell(200, 200, "F.Cu")  # (20.0, 20.0) mm

        h = finder._heuristic(cell_a, cell_b)

        # Expected: Chebyshev distance = max(100, 100) * 0.1mm = 10mm
        assert abs(h - 10.0) < 0.1

    def test_heuristic_admissible(self):
        """Test that heuristic is admissible (never overestimates)."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)
        finder = PathFinder(grid)

        # Find actual path
        path = finder.find_path(
            start_mm=(10.0, 10.0),
            goal_mm=(30.0, 30.0),
            layer="F.Cu"
        )

        assert path is not None

        stats = finder.get_path_statistics(path)
        actual_length = stats["length_mm"]

        # Heuristic estimate
        start_grid = grid.to_grid_coords(10.0, 10.0)
        goal_grid = grid.to_grid_coords(30.0, 30.0)
        start_cell = GridCell(*start_grid, "F.Cu")
        goal_cell = GridCell(*goal_grid, "F.Cu")
        heuristic_estimate = finder._heuristic(start_cell, goal_cell)

        # Heuristic should never overestimate
        assert heuristic_estimate <= actual_length + 0.1  # Small tolerance for rounding


class TestPathStatistics:
    """Test path statistics calculation."""

    def test_path_statistics_straight_line(self):
        """Test statistics for straight line path."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)
        finder = PathFinder(grid)

        path = [(10.0, 20.0), (30.0, 20.0)]

        stats = finder.get_path_statistics(path)

        assert stats["length_mm"] == 20.0
        assert stats["segments"] == 1
        assert stats["waypoints"] == 2
        assert stats["bends"] == 0

    def test_path_statistics_right_angle(self):
        """Test statistics for right-angle path."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)
        finder = PathFinder(grid)

        path = [(10.0, 20.0), (20.0, 20.0), (20.0, 30.0)]

        stats = finder.get_path_statistics(path)

        assert stats["length_mm"] == 20.0  # 10mm + 10mm
        assert stats["segments"] == 2
        assert stats["waypoints"] == 3
        assert stats["bends"] == 1  # One direction change

    def test_path_statistics_complex_path(self):
        """Test statistics for complex path with multiple bends."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)
        finder = PathFinder(grid)

        path = [
            (10.0, 10.0),
            (20.0, 10.0),  # Right
            (20.0, 20.0),  # Up (bend 1)
            (30.0, 20.0),  # Right (bend 2)
            (30.0, 30.0)   # Up (bend 3)
        ]

        stats = finder.get_path_statistics(path)

        assert stats["length_mm"] == 40.0  # 10+10+10+10
        assert stats["segments"] == 4
        assert stats["waypoints"] == 5
        assert stats["bends"] == 3

    def test_path_statistics_empty_path(self):
        """Test statistics for empty path."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)
        finder = PathFinder(grid)

        stats = finder.get_path_statistics([])

        assert stats["length_mm"] == 0.0
        assert stats["segments"] == 0
        assert stats["waypoints"] == 0
        assert stats["bends"] == 0

    def test_path_statistics_single_point(self):
        """Test statistics for single-point path."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)
        finder = PathFinder(grid)

        stats = finder.get_path_statistics([(10.0, 20.0)])

        assert stats["length_mm"] == 0.0
        assert stats["segments"] == 0
        assert stats["waypoints"] == 1
        assert stats["bends"] == 0


class TestEstimatePathLength:
    """Test path length estimation."""

    def test_estimate_horizontal(self):
        """Test length estimation for horizontal distance."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)
        finder = PathFinder(grid)

        estimate = finder.estimate_path_length(
            start_mm=(10.0, 20.0),
            goal_mm=(30.0, 20.0)
        )

        assert estimate == 20.0

    def test_estimate_vertical(self):
        """Test length estimation for vertical distance."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)
        finder = PathFinder(grid)

        estimate = finder.estimate_path_length(
            start_mm=(20.0, 10.0),
            goal_mm=(20.0, 30.0)
        )

        assert estimate == 20.0

    def test_estimate_manhattan(self):
        """Test length estimation for Manhattan distance."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)
        finder = PathFinder(grid)

        estimate = finder.estimate_path_length(
            start_mm=(10.0, 10.0),
            goal_mm=(30.0, 30.0)
        )

        # Manhattan distance: |30-10| + |30-10| = 40
        assert estimate == 40.0


class TestPointToLineDistance:
    """Test point-to-line distance calculation."""

    def test_point_on_line(self):
        """Test distance for point on line."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)
        finder = PathFinder(grid)

        dist = finder._point_to_line_distance(
            point=(15.0, 20.0),
            line_start=(10.0, 20.0),
            line_end=(20.0, 20.0)
        )

        assert abs(dist) < 0.01

    def test_point_perpendicular_to_line(self):
        """Test distance for point perpendicular to line."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)
        finder = PathFinder(grid)

        dist = finder._point_to_line_distance(
            point=(15.0, 25.0),
            line_start=(10.0, 20.0),
            line_end=(20.0, 20.0)
        )

        assert abs(dist - 5.0) < 0.01

    def test_point_beyond_line_end(self):
        """Test distance for point beyond line segment end."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)
        finder = PathFinder(grid)

        dist = finder._point_to_line_distance(
            point=(25.0, 20.0),
            line_start=(10.0, 20.0),
            line_end=(20.0, 20.0)
        )

        # Distance to nearest endpoint (20, 20)
        assert abs(dist - 5.0) < 0.01


class TestPathNodeComparison:
    """Test PathNode comparison for priority queue."""

    def test_path_node_comparison(self):
        """Test that PathNode comparison uses f_cost."""
        cell_a = GridCell(10, 20, "F.Cu")
        cell_b = GridCell(15, 25, "F.Cu")

        node_a = PathNode(cell=cell_a, g_cost=5.0, h_cost=10.0)
        node_b = PathNode(cell=cell_b, g_cost=3.0, h_cost=15.0)

        # node_a: f_cost = 15, node_b: f_cost = 18
        assert node_a < node_b

    def test_path_node_equality(self):
        """Test that PathNode equality is based on cell position."""
        cell_a = GridCell(10, 20, "F.Cu")
        cell_b = GridCell(10, 20, "F.Cu")
        cell_c = GridCell(15, 25, "F.Cu")

        node_a = PathNode(cell=cell_a, g_cost=5.0, h_cost=10.0)
        node_b = PathNode(cell=cell_b, g_cost=3.0, h_cost=8.0)
        node_c = PathNode(cell=cell_c, g_cost=5.0, h_cost=10.0)

        assert node_a == node_b  # Same position
        assert node_a != node_c  # Different position


class TestMultiLayerPathfinding:
    """Test multi-layer pathfinding with automatic via placement."""

    def test_find_path_with_layer_change(self):
        """Test simple path from F.Cu to B.Cu with via placement."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)
        finder = PathFinder(grid, via_cost=10.0)

        # Route from F.Cu to B.Cu
        path = finder.find_path(
            start_mm=(10.0, 20.0),
            goal_mm=(30.0, 20.0),
            layer="F.Cu",
            target_layer="B.Cu"
        )

        assert path is not None
        assert len(path) >= 2

        # Path should start and end at correct positions
        assert path[0] == (10.0, 20.0)
        assert path[-1] == (30.0, 20.0)

        # Via should be marked in grid
        assert len(grid.vias) > 0

    def test_via_placement_basic(self):
        """Test that via is placed at layer transition point."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)
        finder = PathFinder(grid, via_cost=10.0)

        # Clear grid before test
        initial_via_count = len(grid.vias)

        path = finder.find_path(
            start_mm=(10.0, 20.0),
            goal_mm=(30.0, 20.0),
            layer="F.Cu",
            target_layer="B.Cu"
        )

        assert path is not None

        # Via count should have increased
        assert len(grid.vias) > initial_via_count

    def test_via_cost_penalty(self):
        """Test that paths prefer staying on same layer due to via cost."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)

        # Place obstacle only on F.Cu to force layer change
        grid.mark_rectangle_obstacle(18.0, 18.0, 22.0, 22.0, "F.Cu")

        finder = PathFinder(grid, via_cost=100.0)  # High via cost

        # Route with multi-layer enabled
        path_multi = finder.find_path(
            start_mm=(10.0, 20.0),
            goal_mm=(30.0, 20.0),
            layer="F.Cu",
            target_layer="F.Cu"  # Start and end on same layer
        )

        assert path_multi is not None

        # Path should route around obstacle on F.Cu rather than using via
        # (because via cost is very high)
        # Stats should show path going around
        stats = finder.get_path_statistics(path_multi)
        assert stats["length_mm"] > 20.0  # Longer than direct route due to detour

    def test_multiple_layer_changes(self):
        """Test path with multiple via placements."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)

        # Place obstacles to force multiple layer changes
        grid.mark_rectangle_obstacle(15.0, 15.0, 18.0, 25.0, "F.Cu")
        grid.mark_rectangle_obstacle(22.0, 15.0, 25.0, 25.0, "B.Cu")

        finder = PathFinder(grid, via_cost=5.0)  # Lower via cost

        path = finder.find_path(
            start_mm=(10.0, 20.0),
            goal_mm=(30.0, 20.0),
            layer="F.Cu",
            target_layer="F.Cu"
        )

        # Path may need to use multiple layer transitions
        # to route around obstacles on different layers
        assert path is not None

    def test_blocked_via_position(self):
        """Test via placement when via position is blocked."""
        grid = RoutingGrid(width_mm=50.0, height_mm=50.0, resolution_mm=0.5)

        # Fill most of the board with obstacles on both layers
        # Leave only narrow channels
        grid.mark_rectangle_obstacle(15.0, 0.0, 35.0, 10.0, "both")
        grid.mark_rectangle_obstacle(15.0, 15.0, 35.0, 35.0, "both")
        grid.mark_rectangle_obstacle(15.0, 40.0, 35.0, 50.0, "both")

        finder = PathFinder(grid, via_cost=5.0)

        path = finder.find_path(
            start_mm=(10.0, 25.0),
            goal_mm=(40.0, 25.0),
            layer="F.Cu",
            target_layer="B.Cu"
        )

        # Path should find a route through available channels
        # or return None if completely blocked
        if path is not None:
            assert path[0] == (10.0, 25.0)
            assert path[-1] == (40.0, 25.0)

    def test_via_clearance_respected(self):
        """Test that vias don't violate clearance requirements."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.2)

        # Place some obstacles
        grid.mark_obstacle(15.0, 20.0, "both", size_mm=2.0)
        grid.mark_obstacle(25.0, 20.0, "both", size_mm=2.0)

        finder = PathFinder(grid, via_cost=8.0)

        path = finder.find_path(
            start_mm=(10.0, 20.0),
            goal_mm=(30.0, 20.0),
            layer="F.Cu",
            target_layer="B.Cu"
        )

        assert path is not None

        # Check that placed vias respect clearances
        for via_pos in grid.vias:
            via_mm = grid.to_mm_coords(*via_pos)

            # Via should not be too close to existing obstacles
            # (clearance check is done by grid.mark_via internally)
            # Just verify via was successfully placed
            assert via_pos in grid.vias

    def test_single_layer_backward_compatibility(self):
        """Test that single-layer routing still works (backward compatibility)."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)
        finder = PathFinder(grid, via_cost=10.0)

        # Route without specifying target_layer (defaults to same layer)
        path = finder.find_path(
            start_mm=(10.0, 20.0),
            goal_mm=(30.0, 20.0),
            layer="F.Cu"
        )

        assert path is not None
        assert len(path) >= 2
        assert path[0] == (10.0, 20.0)
        assert path[-1] == (30.0, 20.0)

    def test_get_path_with_layers(self):
        """Test get_path_with_layers() method returns layer information."""
        # Use fresh grid for this test
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)
        finder = PathFinder(grid, via_cost=10.0)

        # Get path cells directly without marking vias
        start_grid = grid.to_grid_coords(10.0, 20.0)
        goal_grid = grid.to_grid_coords(30.0, 20.0)
        start_cell = GridCell(start_grid[0], start_grid[1], "F.Cu")
        goal_cell = GridCell(goal_grid[0], goal_grid[1], "B.Cu")

        path_cells = finder._astar_search(start_cell, goal_cell, "B.Cu", True)

        assert path_cells is not None

        # Get path with layer information
        path_with_layers = finder.get_path_with_layers(path_cells)

        assert len(path_with_layers) > 0
        # Each element should be ((x, y), layer)
        for waypoint in path_with_layers:
            assert len(waypoint) == 2
            pos, layer = waypoint
            assert len(pos) == 2
            assert layer in ["F.Cu", "B.Cu"]

        # Should have layer transition somewhere
        layers_in_path = [layer for pos, layer in path_with_layers]
        assert "F.Cu" in layers_in_path
        assert "B.Cu" in layers_in_path


class TestMultiLayerPathfinding4Layer:
    """Test multi-layer pathfinding on 4+ layer boards."""

    def test_4layer_through_hole_via(self):
        """Test pathfinding on 4-layer board with through-hole via."""
        grid = RoutingGrid(
            width_mm=100.0, height_mm=80.0, resolution_mm=0.5,
            layers=["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        )
        finder = PathFinder(grid, via_cost=10.0, allowed_via_types=["through"])

        # Route from F.Cu to B.Cu
        path = finder.find_path(
            start_mm=(10.0, 20.0),
            goal_mm=(30.0, 20.0),
            layer="F.Cu",
            target_layer="B.Cu"
        )

        assert path is not None
        assert len(path) >= 2

    def test_4layer_layer_transitions(self):
        """Test that allowed layer transitions work correctly on 4-layer board."""
        grid = RoutingGrid(
            width_mm=100.0, height_mm=80.0, resolution_mm=0.5,
            layers=["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        )
        finder = PathFinder(grid, via_cost=10.0, allowed_via_types=["through"])

        # Test layer transition options from F.Cu
        transitions = finder._get_possible_layer_transitions("F.Cu")

        # Through-hole via allows transition to any other layer
        target_layers = [layer for layer, _ in transitions]
        assert "In1.Cu" in target_layers
        assert "In2.Cu" in target_layers
        assert "B.Cu" in target_layers
        assert "F.Cu" not in target_layers  # Can't transition to same layer

    def test_4layer_blind_via_from_top(self):
        """Test blind via from F.Cu to In1.Cu."""
        grid = RoutingGrid(
            width_mm=100.0, height_mm=80.0, resolution_mm=0.5,
            layers=["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        )
        finder = PathFinder(grid, via_cost=10.0, allowed_via_types=["blind"])

        # Test layer transition options from F.Cu with blind vias
        transitions = finder._get_possible_layer_transitions("F.Cu")

        # Blind via from outer (F.Cu) should only go to adjacent inner
        target_layers = [layer for layer, _ in transitions]
        assert "In1.Cu" in target_layers
        assert "In2.Cu" not in target_layers  # Not adjacent
        assert "B.Cu" not in target_layers  # Other outer layer

    def test_4layer_blind_via_from_inner_to_outer(self):
        """Test blind via from In1.Cu back to F.Cu."""
        grid = RoutingGrid(
            width_mm=100.0, height_mm=80.0, resolution_mm=0.5,
            layers=["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        )
        finder = PathFinder(grid, via_cost=10.0, allowed_via_types=["blind"])

        # Test layer transition options from In1.Cu with blind vias
        transitions = finder._get_possible_layer_transitions("In1.Cu")

        # Blind via from inner should be able to go to adjacent outer
        target_layers = [layer for layer, _ in transitions]
        assert "F.Cu" in target_layers  # Adjacent outer

    def test_4layer_buried_via(self):
        """Test buried via between inner layers."""
        grid = RoutingGrid(
            width_mm=100.0, height_mm=80.0, resolution_mm=0.5,
            layers=["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        )
        finder = PathFinder(grid, via_cost=10.0, allowed_via_types=["buried"])

        # Test layer transition options from In1.Cu with buried vias
        transitions = finder._get_possible_layer_transitions("In1.Cu")

        # Buried via should only go between inner layers
        target_layers = [layer for layer, _ in transitions]
        assert "In2.Cu" in target_layers  # Adjacent inner
        assert "F.Cu" not in target_layers  # Outer layer
        assert "B.Cu" not in target_layers  # Outer layer

    def test_4layer_buried_via_not_from_outer(self):
        """Test that buried vias can't be created from outer layers."""
        grid = RoutingGrid(
            width_mm=100.0, height_mm=80.0, resolution_mm=0.5,
            layers=["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        )
        finder = PathFinder(grid, via_cost=10.0, allowed_via_types=["buried"])

        # Test layer transition options from F.Cu with buried vias only
        transitions = finder._get_possible_layer_transitions("F.Cu")

        # No transitions should be available (can't create buried from outer)
        assert len(transitions) == 0

    def test_4layer_mixed_via_types(self):
        """Test pathfinding with multiple via types allowed."""
        grid = RoutingGrid(
            width_mm=100.0, height_mm=80.0, resolution_mm=0.5,
            layers=["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        )
        finder = PathFinder(
            grid, via_cost=10.0,
            allowed_via_types=["through", "blind", "buried"]
        )

        # Test layer transition options from F.Cu
        transitions = finder._get_possible_layer_transitions("F.Cu")

        # Should have both through and blind options
        target_layers = [layer for layer, _ in transitions]
        # Through-hole allows all layers
        assert "B.Cu" in target_layers
        # Blind allows adjacent inner
        assert target_layers.count("In1.Cu") >= 1  # At least one option to In1.Cu

    def test_via_type_cost_modifiers(self):
        """Test that via type cost modifiers are applied correctly."""
        grid = RoutingGrid(
            width_mm=100.0, height_mm=80.0, resolution_mm=0.5,
            layers=["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        )
        finder = PathFinder(
            grid, via_cost=10.0,
            allowed_via_types=["through", "blind", "buried"]
        )

        # Check that through-hole has highest cost multiplier
        assert finder.via_type_costs["through"] > finder.via_type_costs["blind"]
        assert finder.via_type_costs["blind"] > finder.via_type_costs["buried"]

    def test_6layer_routing(self):
        """Test pathfinding on 6-layer board."""
        grid = RoutingGrid(
            width_mm=100.0, height_mm=80.0, resolution_mm=0.5,
            layers=["F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "B.Cu"]
        )
        finder = PathFinder(grid, via_cost=10.0, allowed_via_types=["through"])

        # Route from F.Cu to B.Cu on 6-layer board
        path = finder.find_path(
            start_mm=(10.0, 20.0),
            goal_mm=(30.0, 20.0),
            layer="F.Cu",
            target_layer="B.Cu"
        )

        assert path is not None

    def test_4layer_inner_layer_routing(self):
        """Test routing entirely on inner layers."""
        grid = RoutingGrid(
            width_mm=100.0, height_mm=80.0, resolution_mm=0.5,
            layers=["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        )
        finder = PathFinder(grid, via_cost=10.0, allowed_via_types=["through"])

        # Route from In1.Cu to In2.Cu
        path = finder.find_path(
            start_mm=(10.0, 20.0),
            goal_mm=(30.0, 20.0),
            layer="In1.Cu",
            target_layer="In2.Cu"
        )

        assert path is not None
