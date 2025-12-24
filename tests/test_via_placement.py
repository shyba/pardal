"""
Unit tests for ViaPlacement class.

Tests via clearance checking, optimal position finding,
and via count minimization algorithms.
"""

import pytest
import math
from pcb_tool.routing.grid import RoutingGrid, GridCell
from pcb_tool.routing.via_placer import ViaPlacement


class TestViaPlacementInitialization:
    """Test ViaPlacement initialization."""

    def test_init_default(self):
        """Test via placement initialization with default parameters."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0)
        via_placer = ViaPlacement(grid)

        assert via_placer.grid is grid
        assert via_placer.via_size_mm == 0.8

    def test_init_custom_size(self):
        """Test via placement initialization with custom via size."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0)
        via_placer = ViaPlacement(grid, via_size_mm=1.0)

        assert via_placer.via_size_mm == 1.0


class TestViaClearanceChecking:
    """Test via clearance validation."""

    def test_check_via_clearance_clear_area(self):
        """Test via clearance check in clear area."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.2)
        via_placer = ViaPlacement(grid, via_size_mm=0.8)

        # Check clearance in middle of empty board
        assert via_placer.check_via_clearance((50.0, 40.0))

    def test_check_via_clearance_near_obstacle(self):
        """Test via clearance check near obstacle."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.2)
        via_placer = ViaPlacement(grid, via_size_mm=0.8)

        # Place obstacle on both layers
        grid.mark_obstacle(50.0, 40.0, "both", size_mm=3.0)

        # Via too close to obstacle should fail
        assert not via_placer.check_via_clearance((50.5, 40.0))

        # Via far enough should pass
        assert via_placer.check_via_clearance((55.0, 40.0))

    def test_check_via_clearance_on_obstacle(self):
        """Test via clearance check on top of obstacle."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.2)
        via_placer = ViaPlacement(grid, via_size_mm=0.8)

        # Place obstacle
        grid.mark_obstacle(50.0, 40.0, "F.Cu", size_mm=2.0)

        # Via directly on obstacle should fail
        assert not via_placer.check_via_clearance((50.0, 40.0))

    def test_check_via_clearance_both_layers(self):
        """Test via clearance checks both F.Cu and B.Cu."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.2)
        via_placer = ViaPlacement(grid, via_size_mm=0.8)

        # Place obstacle only on B.Cu
        grid.mark_obstacle(50.0, 40.0, "B.Cu", size_mm=2.0)

        # Via should fail even though F.Cu is clear
        # (via affects both layers)
        assert not via_placer.check_via_clearance((50.0, 40.0))

    def test_check_via_clearance_out_of_bounds(self):
        """Test via clearance check outside board bounds."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.2)
        via_placer = ViaPlacement(grid, via_size_mm=0.8)

        # Position outside board
        assert not via_placer.check_via_clearance((-5.0, 40.0))
        assert not via_placer.check_via_clearance((105.0, 40.0))

    def test_check_via_clearance_custom_clearance(self):
        """Test via clearance check with custom clearance value."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.2, default_clearance_mm=0.2)
        via_placer = ViaPlacement(grid, via_size_mm=0.8)

        # Place obstacle
        grid.mark_obstacle(50.0, 40.0, "both", size_mm=2.0)

        # With larger clearance requirement, more positions should fail
        assert not via_placer.check_via_clearance((52.0, 40.0), clearance_mm=1.0)

        # With smaller clearance, position might pass
        # (depends on exact obstacle placement)


class TestOptimalViaPosition:
    """Test optimal via position finding."""

    def test_find_optimal_via_position_clear_area(self):
        """Test finding via position in clear area."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)
        via_placer = ViaPlacement(grid, via_size_mm=0.8)

        # Find via position near center of board
        position = via_placer.find_optimal_via_position(
            region_center=(50.0, 40.0),
            search_radius_mm=5.0,
            layer_from="F.Cu",
            layer_to="B.Cu"
        )

        assert position is not None
        # Should be close to target center
        dist = math.sqrt((position[0] - 50.0)**2 + (position[1] - 40.0)**2)
        assert dist <= 5.0

    def test_find_optimal_via_position_with_obstacles(self):
        """Test finding via position avoiding obstacles."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)
        via_placer = ViaPlacement(grid, via_size_mm=0.8)

        # Place obstacle at target center
        grid.mark_obstacle(50.0, 40.0, "both", size_mm=3.0)

        # Should find position near but not on obstacle
        position = via_placer.find_optimal_via_position(
            region_center=(50.0, 40.0),
            search_radius_mm=5.0,
            layer_from="F.Cu",
            layer_to="B.Cu"
        )

        assert position is not None
        # Should not be on the obstacle
        grid_pos = grid.to_grid_coords(*position)
        assert grid_pos not in grid.obstacles["F.Cu"]
        assert grid_pos not in grid.obstacles["B.Cu"]

    def test_find_optimal_via_position_no_valid_position(self):
        """Test finding via position when no valid position exists."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)
        via_placer = ViaPlacement(grid, via_size_mm=0.8)

        # Fill search area completely with obstacles using grid coordinates
        center_x, center_y = grid.to_grid_coords(50.0, 40.0)
        search_radius_cells = int(math.ceil(2.0 / 0.5))

        for dx in range(-search_radius_cells-2, search_radius_cells+3):
            for dy in range(-search_radius_cells-2, search_radius_cells+3):
                gx, gy = center_x + dx, center_y + dy
                if grid.is_within_bounds(gx, gy):
                    grid.obstacles["F.Cu"].add((gx, gy))
                    grid.obstacles["B.Cu"].add((gx, gy))

        # Should return None (no valid position)
        position = via_placer.find_optimal_via_position(
            region_center=(50.0, 40.0),
            search_radius_mm=2.0,
            layer_from="F.Cu",
            layer_to="B.Cu"
        )

        assert position is None

    def test_find_optimal_via_position_prefers_clear_areas(self):
        """Test that optimal position finder prefers clear areas."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)
        via_placer = ViaPlacement(grid, via_size_mm=0.8)

        # Place obstacle on one side
        grid.mark_rectangle_obstacle(48.0, 38.0, 50.0, 42.0, "both")

        # Find optimal position
        position = via_placer.find_optimal_via_position(
            region_center=(50.0, 40.0),
            search_radius_mm=5.0,
            layer_from="F.Cu",
            layer_to="B.Cu"
        )

        assert position is not None
        # Should prefer the side away from obstacle
        assert position[0] > 50.0  # Should be on the clear side


class TestViaCountMinimization:
    """Test via count minimization."""

    def test_minimize_via_count_no_optimization(self):
        """Test minimize via count with no optimization possible."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)
        via_placer = ViaPlacement(grid, via_size_mm=0.8)

        # Simple path segments with necessary layer change
        segments = [
            (GridCell(10, 20, "F.Cu"), GridCell(20, 20, "F.Cu")),
            (GridCell(20, 20, "B.Cu"), GridCell(30, 20, "B.Cu"))
        ]

        optimized = via_placer.minimize_via_count(segments)

        # Should return segments unchanged (optimization not possible)
        assert len(optimized) == len(segments)

    def test_minimize_via_count_merge_same_layer(self):
        """Test merging consecutive same-layer segments."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)
        via_placer = ViaPlacement(grid, via_size_mm=0.8)

        # Consecutive segments on same layer
        segments = [
            (GridCell(10, 20, "F.Cu"), GridCell(20, 20, "F.Cu")),
            (GridCell(20, 20, "F.Cu"), GridCell(30, 20, "F.Cu"))
        ]

        optimized = via_placer.minimize_via_count(segments)

        # Should merge into single segment
        assert len(optimized) < len(segments)

    def test_minimize_via_count_eliminate_redundant_transition(self):
        """Test eliminating redundant layer transitions (A->B->A)."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)
        via_placer = ViaPlacement(grid, via_size_mm=0.8)

        # Pattern: F.Cu -> B.Cu -> F.Cu (redundant)
        segments = [
            (GridCell(10, 20, "F.Cu"), GridCell(15, 20, "F.Cu")),
            (GridCell(15, 20, "B.Cu"), GridCell(20, 20, "B.Cu")),
            (GridCell(20, 20, "F.Cu"), GridCell(30, 20, "F.Cu"))
        ]

        optimized = via_placer.minimize_via_count(segments)

        # Should eliminate middle transition
        assert len(optimized) < len(segments)

    def test_minimize_via_count_empty_input(self):
        """Test minimize via count with empty input."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)
        via_placer = ViaPlacement(grid, via_size_mm=0.8)

        optimized = via_placer.minimize_via_count([])

        assert len(optimized) == 0

    def test_minimize_via_count_single_segment(self):
        """Test minimize via count with single segment."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)
        via_placer = ViaPlacement(grid, via_size_mm=0.8)

        segments = [
            (GridCell(10, 20, "F.Cu"), GridCell(30, 20, "F.Cu"))
        ]

        optimized = via_placer.minimize_via_count(segments)

        assert len(optimized) == 1


class TestViaPositionScoring:
    """Test via position scoring heuristics."""

    def test_score_via_position_clear_area(self):
        """Test scoring via position in clear area."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)
        via_placer = ViaPlacement(grid, via_size_mm=0.8)

        context = {
            'target_pos': (50.0, 40.0),
            'layer_from': "F.Cu",
            'layer_to': "B.Cu"
        }

        # Score position near target in clear area
        score = via_placer.score_via_position((50.0, 40.0), context)

        assert score >= 0.0
        assert score < 100.0  # Should have reasonable score

    def test_score_via_position_near_obstacle(self):
        """Test that positions near obstacles get worse scores."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)
        via_placer = ViaPlacement(grid, via_size_mm=0.8)

        # Place obstacle
        grid.mark_obstacle(50.0, 40.0, "both", size_mm=2.0)

        context = {
            'target_pos': (50.0, 40.0),
            'layer_from': "F.Cu",
            'layer_to': "B.Cu"
        }

        # Score position near obstacle
        score_near = via_placer.score_via_position((51.5, 40.0), context)

        # Score position far from obstacle
        score_far = via_placer.score_via_position((60.0, 40.0), context)

        # Position near obstacle should have worse (higher) score
        assert score_near > score_far

    def test_score_via_position_far_from_target(self):
        """Test that positions far from target get worse scores."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)
        via_placer = ViaPlacement(grid, via_size_mm=0.8)

        context = {
            'target_pos': (50.0, 40.0),
            'layer_from': "F.Cu",
            'layer_to': "B.Cu"
        }

        # Score position close to target
        score_close = via_placer.score_via_position((50.0, 40.0), context)

        # Score position far from target
        score_far = via_placer.score_via_position((70.0, 60.0), context)

        # Position far from target should have worse (higher) score
        assert score_far > score_close

    def test_score_via_position_lower_is_better(self):
        """Test that scoring follows lower-is-better convention."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, resolution_mm=0.5)
        via_placer = ViaPlacement(grid, via_size_mm=0.8)

        context = {
            'target_pos': (50.0, 40.0),
            'layer_from': "F.Cu",
            'layer_to': "B.Cu"
        }

        # Clear area, close to target = best position
        best_score = via_placer.score_via_position((50.0, 40.0), context)

        # Add obstacles to make area less desirable
        grid.mark_obstacle(48.0, 40.0, "both", size_mm=2.0)
        grid.mark_obstacle(52.0, 40.0, "both", size_mm=2.0)

        # Same position should now have worse (higher) score
        worse_score = via_placer.score_via_position((50.0, 40.0), context)

        # With obstacles nearby, score should be higher (worse)
        assert worse_score >= best_score


class TestMultiLayerViaPlacement:
    """Test multi-layer via placement functionality."""

    def test_get_via_layers_through_2layer(self):
        """Test get_via_layers returns all layers for through-hole via on 2-layer board."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0, layers=["F.Cu", "B.Cu"])
        via_placer = ViaPlacement(grid)

        layers = via_placer.get_via_layers("F.Cu", "B.Cu", via_type="through")
        assert layers == ("F.Cu", "B.Cu")

    def test_get_via_layers_through_4layer(self):
        """Test get_via_layers returns all layers for through-hole via on 4-layer board."""
        grid = RoutingGrid(
            width_mm=100.0, height_mm=80.0,
            layers=["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        )
        via_placer = ViaPlacement(grid)

        layers = via_placer.get_via_layers("F.Cu", "B.Cu", via_type="through")
        assert layers == ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu")

    def test_get_via_layers_blind_top(self):
        """Test get_via_layers for blind via from top layer."""
        grid = RoutingGrid(
            width_mm=100.0, height_mm=80.0,
            layers=["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        )
        via_placer = ViaPlacement(grid)

        layers = via_placer.get_via_layers("F.Cu", "In1.Cu", via_type="blind")
        assert layers == ("F.Cu", "In1.Cu")

    def test_get_via_layers_blind_bottom(self):
        """Test get_via_layers for blind via from bottom layer."""
        grid = RoutingGrid(
            width_mm=100.0, height_mm=80.0,
            layers=["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        )
        via_placer = ViaPlacement(grid)

        layers = via_placer.get_via_layers("In2.Cu", "B.Cu", via_type="blind")
        assert layers == ("In2.Cu", "B.Cu")

    def test_get_via_layers_buried(self):
        """Test get_via_layers for buried via between inner layers."""
        grid = RoutingGrid(
            width_mm=100.0, height_mm=80.0,
            layers=["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        )
        via_placer = ViaPlacement(grid)

        layers = via_placer.get_via_layers("In1.Cu", "In2.Cu", via_type="buried")
        assert layers == ("In1.Cu", "In2.Cu")

    def test_get_via_layers_blind_spans_multiple_inner(self):
        """Test get_via_layers for blind via spanning multiple inner layers."""
        grid = RoutingGrid(
            width_mm=100.0, height_mm=80.0,
            layers=["F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "B.Cu"]
        )
        via_placer = ViaPlacement(grid)

        layers = via_placer.get_via_layers("F.Cu", "In2.Cu", via_type="blind")
        assert layers == ("F.Cu", "In1.Cu", "In2.Cu")

    def test_determine_via_type_through(self):
        """Test determine_via_type correctly identifies through-hole vias."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0)
        via_placer = ViaPlacement(grid)

        via_type = via_placer.determine_via_type(("F.Cu", "B.Cu"))
        assert via_type == "through"

        via_type = via_placer.determine_via_type(("F.Cu", "In1.Cu", "In2.Cu", "B.Cu"))
        assert via_type == "through"

    def test_determine_via_type_blind(self):
        """Test determine_via_type correctly identifies blind vias."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0)
        via_placer = ViaPlacement(grid)

        # Blind from top
        via_type = via_placer.determine_via_type(("F.Cu", "In1.Cu"))
        assert via_type == "blind"

        # Blind from bottom
        via_type = via_placer.determine_via_type(("In2.Cu", "B.Cu"))
        assert via_type == "blind"

    def test_determine_via_type_buried(self):
        """Test determine_via_type correctly identifies buried vias."""
        grid = RoutingGrid(width_mm=100.0, height_mm=80.0)
        via_placer = ViaPlacement(grid)

        via_type = via_placer.determine_via_type(("In1.Cu", "In2.Cu"))
        assert via_type == "buried"

    def test_check_via_clearance_4layer_through(self):
        """Test via clearance on 4-layer board for through-hole via."""
        grid = RoutingGrid(
            width_mm=100.0, height_mm=80.0, resolution_mm=0.2,
            layers=["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        )
        via_placer = ViaPlacement(grid, via_size_mm=0.8)

        # Clear area should pass
        assert via_placer.check_via_clearance((50.0, 40.0))

        # Place obstacle on inner layer only
        grid.mark_obstacle(50.0, 40.0, "In1.Cu", size_mm=2.0)

        # Through-hole via should fail (spans all layers)
        assert not via_placer.check_via_clearance((50.0, 40.0))

    def test_check_via_clearance_4layer_blind(self):
        """Test via clearance on 4-layer board for blind via."""
        grid = RoutingGrid(
            width_mm=100.0, height_mm=80.0, resolution_mm=0.2,
            layers=["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        )
        via_placer = ViaPlacement(grid, via_size_mm=0.8)

        # Place obstacle on In2.Cu
        grid.mark_obstacle(50.0, 40.0, "In2.Cu", size_mm=2.0)

        # Blind via F.Cu->In1.Cu should pass (doesn't reach In2.Cu)
        assert via_placer.check_via_clearance(
            (50.0, 40.0),
            via_layers=("F.Cu", "In1.Cu")
        )

        # Through-hole via should fail
        assert not via_placer.check_via_clearance(
            (50.0, 40.0),
            via_layers=("F.Cu", "In1.Cu", "In2.Cu", "B.Cu")
        )

    def test_check_via_clearance_4layer_buried(self):
        """Test via clearance on 4-layer board for buried via."""
        grid = RoutingGrid(
            width_mm=100.0, height_mm=80.0, resolution_mm=0.2,
            layers=["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        )
        via_placer = ViaPlacement(grid, via_size_mm=0.8)

        # Place obstacle on F.Cu
        grid.mark_obstacle(50.0, 40.0, "F.Cu", size_mm=2.0)

        # Buried via In1.Cu->In2.Cu should pass (doesn't touch F.Cu)
        assert via_placer.check_via_clearance(
            (50.0, 40.0),
            via_layers=("In1.Cu", "In2.Cu")
        )

        # Through-hole via should fail
        assert not via_placer.check_via_clearance(
            (50.0, 40.0),
            via_layers=("F.Cu", "In1.Cu", "In2.Cu", "B.Cu")
        )

    def test_find_optimal_via_position_with_via_type(self):
        """Test find_optimal_via_position uses via_type parameter."""
        grid = RoutingGrid(
            width_mm=100.0, height_mm=80.0, resolution_mm=0.5,
            layers=["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        )
        via_placer = ViaPlacement(grid, via_size_mm=0.8)

        # Place obstacle on B.Cu at center
        grid.mark_obstacle(50.0, 40.0, "B.Cu", size_mm=3.0)

        # Through-hole via should avoid this position
        through_pos = via_placer.find_optimal_via_position(
            region_center=(50.0, 40.0),
            search_radius_mm=5.0,
            layer_from="F.Cu",
            layer_to="B.Cu",
            via_type="through"
        )

        # Blind via F.Cu->In1.Cu should be able to use center
        blind_pos = via_placer.find_optimal_via_position(
            region_center=(50.0, 40.0),
            search_radius_mm=5.0,
            layer_from="F.Cu",
            layer_to="In1.Cu",
            via_type="blind"
        )

        # Blind via should be closer to target
        if through_pos is not None and blind_pos is not None:
            through_dist = math.sqrt(
                (through_pos[0] - 50.0)**2 + (through_pos[1] - 40.0)**2
            )
            blind_dist = math.sqrt(
                (blind_pos[0] - 50.0)**2 + (blind_pos[1] - 40.0)**2
            )
            assert blind_dist <= through_dist

    def test_score_via_position_via_type_penalty(self):
        """Test that through-hole vias get slight penalty vs blind/buried."""
        grid = RoutingGrid(
            width_mm=100.0, height_mm=80.0, resolution_mm=0.5,
            layers=["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        )
        via_placer = ViaPlacement(grid, via_size_mm=0.8)

        context_through = {
            'target_pos': (50.0, 40.0),
            'layer_from': "F.Cu",
            'layer_to': "B.Cu",
            'via_type': "through",
            'via_layers': ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu")
        }

        context_blind = {
            'target_pos': (50.0, 40.0),
            'layer_from': "F.Cu",
            'layer_to': "In1.Cu",
            'via_type': "blind",
            'via_layers': ("F.Cu", "In1.Cu")
        }

        score_through = via_placer.score_via_position((50.0, 40.0), context_through)
        score_blind = via_placer.score_via_position((50.0, 40.0), context_blind)

        # Through-hole should have slightly higher (worse) score
        assert score_through > score_blind
