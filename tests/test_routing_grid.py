"""
Unit tests for RoutingGrid class.

Tests grid initialization, obstacle management, coordinate conversion,
and neighbor generation for pathfinding.
"""

import pytest
import math
from pcb_tool.routing.grid import RoutingGrid, GridCell


class TestRoutingGridInitialization:
    """Test RoutingGrid initialization and basic properties."""

    def test_init_default_parameters(self):
        """Test grid initialization with default parameters."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0)

        assert grid.width_mm == 100.0
        assert grid.height_mm == 80.0
        assert grid.resolution_mm == 0.1
        assert grid.default_clearance_mm == 0.2
        assert grid.grid_width == 1000
        assert grid.grid_height == 800

    def test_init_custom_resolution(self):
        """Test grid initialization with custom resolution."""
        grid = RoutingGrid(width_mm=50.0, height_mm=40.0, resolution_mm=0.05)

        assert grid.resolution_mm == 0.05
        assert grid.grid_width == 1000  # 50.0 / 0.05
        assert grid.grid_height == 800   # 40.0 / 0.05

    def test_init_empty_obstacles(self):
        """Test that obstacles are initially empty."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0)

        assert len(grid.obstacles["F.Cu"]) == 0
        assert len(grid.obstacles["B.Cu"]) == 0
        assert len(grid.clearance_zones["F.Cu"]) == 0
        assert len(grid.clearance_zones["B.Cu"]) == 0
        assert len(grid.vias) == 0


class TestCoordinateConversion:
    """Test coordinate conversion between mm and grid indices."""

    def test_to_grid_coords(self):
        """Test millimeter to grid coordinate conversion."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)

        # Test various positions
        assert grid.to_grid_coords(0.0, 0.0) == (0, 0)
        assert grid.to_grid_coords(10.0, 20.0) == (100, 200)
        assert grid.to_grid_coords(5.5, 7.5) == (55, 75)
        assert grid.to_grid_coords(0.06, 0.06) == (1, 1)  # Rounding

    def test_to_mm_coords(self):
        """Test grid to millimeter coordinate conversion."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)

        # Test various positions
        assert grid.to_mm_coords(0, 0) == (0.0, 0.0)
        assert grid.to_mm_coords(100, 200) == (10.0, 20.0)
        assert grid.to_mm_coords(55, 75) == (5.5, 7.5)

    def test_coordinate_round_trip(self):
        """Test that coordinate conversion is reversible."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)

        test_positions = [(10.0, 20.0), (5.5, 7.5), (0.0, 0.0), (99.9, 79.9)]

        for x_mm, y_mm in test_positions:
            grid_x, grid_y = grid.to_grid_coords(x_mm, y_mm)
            x_back, y_back = grid.to_mm_coords(grid_x, grid_y)

            # Should be within resolution tolerance
            assert abs(x_back - x_mm) < grid.resolution_mm
            assert abs(y_back - y_mm) < grid.resolution_mm


class TestBoundsChecking:
    """Test boundary checking for grid cells."""

    def test_is_within_bounds_valid(self):
        """Test valid positions within bounds."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)

        assert grid.is_within_bounds(0, 0) is True
        assert grid.is_within_bounds(500, 400) is True
        assert grid.is_within_bounds(999, 799) is True

    def test_is_within_bounds_invalid(self):
        """Test invalid positions outside bounds."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)

        assert grid.is_within_bounds(-1, 0) is False
        assert grid.is_within_bounds(0, -1) is False
        assert grid.is_within_bounds(1000, 400) is False
        assert grid.is_within_bounds(500, 800) is False
        assert grid.is_within_bounds(1000, 800) is False


class TestObstacleMarking:
    """Test marking obstacles on the grid."""

    def test_mark_obstacle_single_layer(self):
        """Test marking obstacle on a single layer."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)

        grid.mark_obstacle(10.0, 20.0, "F.Cu", size_mm=2.0)

        # Check that obstacle was marked on F.Cu
        assert len(grid.obstacles["F.Cu"]) > 0
        # Check that B.Cu is still empty
        assert len(grid.obstacles["B.Cu"]) == 0

    def test_mark_obstacle_both_layers(self):
        """Test marking obstacle on both layers."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)

        grid.mark_obstacle(10.0, 20.0, "both", size_mm=2.0)

        # Check that obstacle was marked on both layers
        assert len(grid.obstacles["F.Cu"]) > 0
        assert len(grid.obstacles["B.Cu"]) > 0

    def test_mark_obstacle_clearance_zones(self):
        """Test that clearance zones are created around obstacles."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)

        grid.mark_obstacle(50.0, 50.0, "F.Cu", clearance_mm=0.5, size_mm=1.0)

        # Check that both obstacles and clearance zones were created
        assert len(grid.obstacles["F.Cu"]) > 0
        assert len(grid.clearance_zones["F.Cu"]) > 0

    def test_mark_rectangle_obstacle(self):
        """Test marking rectangular obstacle."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)

        grid.mark_rectangle_obstacle(10.0, 20.0, 15.0, 25.0, "F.Cu")

        # Convert to grid coords
        gx_min, gy_min = grid.to_grid_coords(10.0, 20.0)
        gx_max, gy_max = grid.to_grid_coords(15.0, 25.0)

        # Check that all cells in rectangle are marked
        for gx in range(gx_min, gx_max + 1):
            for gy in range(gy_min, gy_max + 1):
                assert (gx, gy) in grid.obstacles["F.Cu"]

    def test_mark_trace_segment(self):
        """Test marking trace segment as obstacle."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)

        grid.mark_trace_segment(
            start_mm=(10.0, 10.0),
            end_mm=(20.0, 10.0),
            layer="F.Cu",
            width_mm=0.5
        )

        # Check that obstacles were created along the trace
        assert len(grid.obstacles["F.Cu"]) > 0

        # Check that start and end points are marked
        start_grid = grid.to_grid_coords(10.0, 10.0)
        end_grid = grid.to_grid_coords(20.0, 10.0)
        assert start_grid in grid.obstacles["F.Cu"]
        assert end_grid in grid.obstacles["F.Cu"]


class TestViaMarking:
    """Test marking vias on the grid."""

    def test_mark_via(self):
        """Test marking via at position."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)

        grid.mark_via(15.0, 25.0, size_mm=0.8)

        # Check that via position is recorded
        via_grid = grid.to_grid_coords(15.0, 25.0)
        assert via_grid in grid.vias

        # Check that via is marked as obstacle on both layers
        assert len(grid.obstacles["F.Cu"]) > 0
        assert len(grid.obstacles["B.Cu"]) > 0


class TestCellValidation:
    """Test cell validation and cost calculation."""

    def test_is_valid_cell_empty_grid(self):
        """Test that cells are valid on empty grid."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)

        assert grid.is_valid_cell(100, 200, "F.Cu") is True
        assert grid.is_valid_cell(500, 400, "B.Cu") is True

    def test_is_valid_cell_with_obstacle(self):
        """Test that cells with obstacles are invalid."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)

        # Mark obstacle
        grid.mark_obstacle(10.0, 20.0, "F.Cu", size_mm=2.0)
        obstacle_grid = grid.to_grid_coords(10.0, 20.0)

        # Cell with obstacle should be invalid
        assert grid.is_valid_cell(*obstacle_grid, "F.Cu") is False

        # Same cell on other layer should be valid (if not marked)
        assert grid.is_valid_cell(*obstacle_grid, "B.Cu") is True

    def test_is_valid_cell_out_of_bounds(self):
        """Test that out-of-bounds cells are invalid."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)

        assert grid.is_valid_cell(-1, 0, "F.Cu") is False
        assert grid.is_valid_cell(0, -1, "F.Cu") is False
        assert grid.is_valid_cell(1000, 400, "F.Cu") is False
        assert grid.is_valid_cell(500, 800, "F.Cu") is False

    def test_get_cell_cost_free_cell(self):
        """Test cost of free cells."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)

        assert grid.get_cell_cost(100, 200, "F.Cu") == 1.0

    def test_get_cell_cost_clearance_zone(self):
        """Test that clearance zones have higher cost."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)

        grid.mark_obstacle(50.0, 50.0, "F.Cu", clearance_mm=1.0, size_mm=1.0)

        # Find a cell in clearance zone
        center_grid = grid.to_grid_coords(50.0, 50.0)
        cx, cy = center_grid

        # Check cells around obstacle (should be in clearance zone)
        clearance_cells = int(math.ceil(1.5 / grid.resolution_mm))
        found_clearance = False

        for dx in range(-clearance_cells, clearance_cells + 1):
            for dy in range(-clearance_cells, clearance_cells + 1):
                gx, gy = cx + dx, cy + dy
                if (gx, gy) in grid.clearance_zones["F.Cu"]:
                    cost = grid.get_cell_cost(gx, gy, "F.Cu")
                    assert cost == 2.0  # Double cost for clearance zones
                    found_clearance = True
                    break
            if found_clearance:
                break

        assert found_clearance, "No clearance zone cells found"

    def test_get_cell_cost_obstacle(self):
        """Test that obstacles have infinite cost."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)

        grid.mark_obstacle(10.0, 20.0, "F.Cu", size_mm=2.0)
        obstacle_grid = grid.to_grid_coords(10.0, 20.0)

        assert grid.get_cell_cost(*obstacle_grid, "F.Cu") == float('inf')


class TestNeighborGeneration:
    """Test neighbor generation for pathfinding."""

    def test_get_neighbors_orthogonal_only(self):
        """Test getting orthogonal neighbors (no diagonals)."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)

        neighbors = grid.get_neighbors(100, 200, "F.Cu", allow_diagonals=False)

        # Should have 4 orthogonal neighbors
        assert len(neighbors) == 4

        # Check that all neighbors are orthogonal (Manhattan distance = 1)
        for cell, cost in neighbors:
            dx = abs(cell.x - 100)
            dy = abs(cell.y - 200)
            assert dx + dy == 1

    def test_get_neighbors_with_diagonals(self):
        """Test getting neighbors with diagonals."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)

        neighbors = grid.get_neighbors(100, 200, "F.Cu", allow_diagonals=True)

        # Should have 8 neighbors (4 orthogonal + 4 diagonal)
        assert len(neighbors) == 8

    def test_get_neighbors_near_boundary(self):
        """Test neighbor generation near boundaries."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)

        # Corner position
        neighbors = grid.get_neighbors(0, 0, "F.Cu", allow_diagonals=True)

        # Should have only 3 neighbors (right, up, diagonal up-right)
        assert len(neighbors) == 3

        # Check all neighbors are valid
        for cell, cost in neighbors:
            assert grid.is_valid_cell(cell.x, cell.y, cell.layer)

    def test_get_neighbors_with_obstacles(self):
        """Test that obstacle cells are excluded from neighbors."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)

        # Mark obstacle to the right
        grid.obstacles["F.Cu"].add((101, 200))

        neighbors = grid.get_neighbors(100, 200, "F.Cu", allow_diagonals=False)

        # Should have 3 neighbors (obstacle blocks one direction)
        assert len(neighbors) == 3

        # Check that obstacle cell is not in neighbors
        neighbor_cells = [cell for cell, cost in neighbors]
        assert not any(cell.x == 101 and cell.y == 200 for cell in neighbor_cells)

    def test_neighbor_costs(self):
        """Test that neighbor costs are correct."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)

        neighbors = grid.get_neighbors(100, 200, "F.Cu", allow_diagonals=True)

        for cell, cost in neighbors:
            dx = abs(cell.x - 100)
            dy = abs(cell.y - 200)

            # Orthogonal: cost = resolution_mm
            if dx + dy == 1:
                assert abs(cost - grid.resolution_mm) < 1e-6

            # Diagonal: cost = resolution_mm * sqrt(2)
            elif dx == 1 and dy == 1:
                expected_cost = grid.resolution_mm * math.sqrt(2)
                assert abs(cost - expected_cost) < 1e-6


class TestBresenhamLine:
    """Test Bresenham line rasterization."""

    def test_bresenham_horizontal(self):
        """Test horizontal line rasterization."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)

        cells = grid._bresenham_line((10, 20), (20, 20))

        # Should include start and end
        assert (10, 20) in cells
        assert (20, 20) in cells

        # Should have expected number of cells
        assert len(cells) == 11  # 10 to 20 inclusive

        # All y-coordinates should be 20
        assert all(y == 20 for x, y in cells)

    def test_bresenham_vertical(self):
        """Test vertical line rasterization."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)

        cells = grid._bresenham_line((10, 20), (10, 30))

        # Should include start and end
        assert (10, 20) in cells
        assert (10, 30) in cells

        # Should have expected number of cells
        assert len(cells) == 11  # 20 to 30 inclusive

        # All x-coordinates should be 10
        assert all(x == 10 for x, y in cells)

    def test_bresenham_diagonal(self):
        """Test diagonal line rasterization."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)

        cells = grid._bresenham_line((10, 20), (20, 30))

        # Should include start and end
        assert (10, 20) in cells
        assert (20, 30) in cells

        # Should be continuous (no gaps)
        assert len(cells) >= 11


class TestGridStatistics:
    """Test grid statistics reporting."""

    def test_get_statistics_empty_grid(self):
        """Test statistics for empty grid."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)

        stats = grid.get_statistics()

        assert stats["dimensions"]["width_mm"] == 100.0
        assert stats["dimensions"]["height_mm"] == 80.0
        assert stats["dimensions"]["grid_width"] == 1000
        assert stats["dimensions"]["grid_height"] == 800
        assert stats["obstacles"]["F.Cu"] == 0
        assert stats["obstacles"]["B.Cu"] == 0
        assert stats["obstacles"]["vias"] == 0

    def test_get_statistics_with_obstacles(self):
        """Test statistics with obstacles."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.1)

        grid.mark_obstacle(10.0, 20.0, "F.Cu", size_mm=2.0)
        grid.mark_via(15.0, 25.0, size_mm=0.8)

        stats = grid.get_statistics()

        assert stats["obstacles"]["F.Cu"] > 0
        assert stats["obstacles"]["B.Cu"] > 0  # Via on both layers
        assert stats["obstacles"]["vias"] == 1
        assert stats["clearance_zones"]["F.Cu"] > 0
