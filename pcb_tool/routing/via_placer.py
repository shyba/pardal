"""
Via Placement Module

Utilities for via placement optimization and constraint validation.
Provides methods to check via clearances, find optimal via positions,
and minimize via count in routing paths.

Supports multi-layer boards with:
- Through-hole vias (span all layers)
- Blind vias (outer to inner layer)
- Buried vias (inner to inner layer)
"""

from typing import Tuple, List, Optional
from pcb_tool.routing.grid import RoutingGrid, GridCell
import math


class ViaPlacement:
    """Utilities for via placement and optimization."""

    def __init__(self, grid: RoutingGrid, via_size_mm: float = 0.8):
        """
        Initialize via placement utilities.

        Args:
            grid: RoutingGrid instance
            via_size_mm: Via diameter in millimeters (default 0.8mm)
        """
        self.grid = grid
        self.via_size_mm = via_size_mm

    def get_via_layers(
        self,
        from_layer: str,
        to_layer: str,
        via_type: str = "through"
    ) -> Tuple[str, ...]:
        """
        Get the layers a via spans based on type.

        Args:
            from_layer: Source layer
            to_layer: Destination layer
            via_type: "through", "blind", or "buried"

        Returns:
            Tuple of layer names the via spans
        """
        if via_type == "through":
            # Through-hole via spans all layers
            return tuple(self.grid.layers)
        else:
            # Blind/buried: only layers between from and to
            return tuple(self.grid.get_layers_between(from_layer, to_layer))

    def determine_via_type(self, layers: Tuple[str, ...]) -> str:
        """
        Determine the via type based on layers it spans.

        Args:
            layers: Tuple of layer names the via spans

        Returns:
            "through", "blind", or "buried"
        """
        has_fcu = "F.Cu" in layers
        has_bcu = "B.Cu" in layers

        if has_fcu and has_bcu:
            return "through"
        elif has_fcu or has_bcu:
            return "blind"
        else:
            return "buried"

    def check_via_clearance(
        self,
        position: Tuple[float, float],
        clearance_mm: Optional[float] = None,
        via_layers: Optional[Tuple[str, ...]] = None
    ) -> bool:
        """
        Check if a via can be placed at position with required clearance.

        Args:
            position: (x, y) position in millimeters
            clearance_mm: Required clearance (uses grid default if None)
            via_layers: Layers the via spans (uses all grid layers if None)

        Returns:
            True if via placement is valid, False if violates clearances
        """
        if clearance_mm is None:
            clearance_mm = self.grid.default_clearance_mm

        # Default to all layers (through-hole via)
        if via_layers is None:
            via_layers = tuple(self.grid.layers)

        # Convert position to grid coordinates
        grid_x, grid_y = self.grid.to_grid_coords(*position)

        # Check if position is within board bounds
        if not self.grid.is_within_bounds(grid_x, grid_y):
            return False

        # Calculate clearance radius in grid cells
        via_radius = int(math.ceil(self.via_size_mm / (2 * self.grid.resolution_mm)))
        clearance_radius = int(math.ceil((self.via_size_mm / 2 + clearance_mm) / self.grid.resolution_mm))

        # Check clearance on all layers the via spans
        for layer in via_layers:
            # Skip layers not in grid (shouldn't happen, but be safe)
            if layer not in self.grid.obstacles:
                continue

            # Check area around via position
            for dx in range(-clearance_radius, clearance_radius + 1):
                for dy in range(-clearance_radius, clearance_radius + 1):
                    check_x, check_y = grid_x + dx, grid_y + dy

                    if not self.grid.is_within_bounds(check_x, check_y):
                        continue

                    # Calculate distance from via center
                    dist = math.sqrt(dx*dx + dy*dy) * self.grid.resolution_mm

                    # Check if within via body
                    if dist <= self.via_size_mm / 2:
                        # Must not be an obstacle
                        if (check_x, check_y) in self.grid.obstacles[layer]:
                            return False
                    # Check if within clearance zone
                    elif dist <= (self.via_size_mm / 2 + clearance_mm):
                        # Should avoid obstacles (via clearance requirement)
                        if (check_x, check_y) in self.grid.obstacles[layer]:
                            return False

        return True

    def find_optimal_via_position(
        self,
        region_center: Tuple[float, float],
        search_radius_mm: float,
        layer_from: str,
        layer_to: str,
        via_type: str = "through"
    ) -> Optional[Tuple[float, float]]:
        """
        Find optimal via position near a target location.

        Searches in region around center for best via placement based on:
        - Clearance from obstacles
        - Distance from target center
        - Alignment with trace directions (prefer straight sections)

        Args:
            region_center: Target center position (x, y) in mm
            search_radius_mm: Search radius in mm
            layer_from: Source layer
            layer_to: Destination layer
            via_type: "through", "blind", or "buried"

        Returns:
            Optimal position (x, y) or None if no valid position found
        """
        # Determine which layers the via will span
        via_layers = self.get_via_layers(layer_from, layer_to, via_type)

        # Convert to grid coordinates
        center_x, center_y = self.grid.to_grid_coords(*region_center)
        search_radius_cells = int(math.ceil(search_radius_mm / self.grid.resolution_mm))

        best_position = None
        best_score = float('inf')

        # Search grid cells in radius
        for dx in range(-search_radius_cells, search_radius_cells + 1):
            for dy in range(-search_radius_cells, search_radius_cells + 1):
                check_x, check_y = center_x + dx, center_y + dy

                # Check if within bounds
                if not self.grid.is_within_bounds(check_x, check_y):
                    continue

                # Calculate distance from center
                dist_from_center = math.sqrt(dx*dx + dy*dy) * self.grid.resolution_mm

                # Skip if outside search radius
                if dist_from_center > search_radius_mm:
                    continue

                # Convert to mm coordinates
                pos_mm = self.grid.to_mm_coords(check_x, check_y)

                # Check if via can be placed here (check only affected layers)
                if not self.check_via_clearance(pos_mm, via_layers=via_layers):
                    continue

                # Score this position
                context = {
                    'target_pos': region_center,
                    'layer_from': layer_from,
                    'layer_to': layer_to,
                    'via_type': via_type,
                    'via_layers': via_layers
                }
                score = self.score_via_position(pos_mm, context)

                # Update best if better score
                if score < best_score:
                    best_score = score
                    best_position = pos_mm

        return best_position

    def minimize_via_count(
        self,
        path_segments: List[Tuple[GridCell, GridCell]]
    ) -> List[Tuple[GridCell, GridCell]]:
        """
        Optimize path to minimize via count.

        Analyzes path segments and attempts to reduce layer transitions by:
        - Merging consecutive segments on same layer
        - Eliminating redundant layer transitions (A->B->A becomes A->A)
        - Adjusting via positions to align with trace geometry

        Args:
            path_segments: List of (start_cell, end_cell) path segments

        Returns:
            Optimized path segments with fewer vias
        """
        if len(path_segments) <= 1:
            return path_segments

        optimized = []
        i = 0

        while i < len(path_segments):
            current_seg = path_segments[i]
            start_cell, end_cell = current_seg

            # Look ahead for optimization opportunities
            if i + 2 < len(path_segments):
                next_seg = path_segments[i + 1]
                next_next_seg = path_segments[i + 2]

                # Check for A->B->A pattern (redundant layer transition)
                if (start_cell.layer != next_seg[0].layer and
                    next_seg[1].layer != next_next_seg[0].layer and
                    start_cell.layer == next_next_seg[1].layer):
                    # Can eliminate middle transition
                    # Merge: start -> next_next_end (skip middle segment)
                    merged_seg = (start_cell, next_next_seg[1])
                    optimized.append(merged_seg)
                    i += 3  # Skip all three segments
                    continue

            # Check if we can merge with next segment (same layer)
            if i + 1 < len(path_segments):
                next_seg = path_segments[i + 1]
                if end_cell.layer == next_seg[0].layer and end_cell.layer == next_seg[1].layer:
                    # Same layer, can potentially merge
                    merged_seg = (start_cell, next_seg[1])
                    optimized.append(merged_seg)
                    i += 2  # Skip both segments
                    continue

            # No optimization possible, keep segment as-is
            optimized.append(current_seg)
            i += 1

        return optimized

    def score_via_position(
        self,
        position: Tuple[float, float],
        context: dict
    ) -> float:
        """
        Score a via position based on routing quality heuristics.

        Lower score = better position. Considers:
        - Distance from obstacles (prefer clear areas)
        - Alignment with trace directions (prefer straight sections)
        - Distance from target (minimize deviation)

        Args:
            position: Position to score (x, y) in mm
            context: Dict with trace_direction, target_pos, via_layers, etc.

        Returns:
            Score value (lower is better)
        """
        score = 0.0

        # Convert to grid coordinates
        grid_x, grid_y = self.grid.to_grid_coords(*position)

        # Determine which layers to check (use via_layers from context or all grid layers)
        layers_to_check = context.get('via_layers', tuple(self.grid.layers))

        # Score component 1: Clearance from obstacles (prefer clear areas)
        # Check minimum distance to obstacles on affected layers
        min_obstacle_dist = float('inf')
        check_radius = int(math.ceil(2.0 / self.grid.resolution_mm))  # Check 2mm radius

        for layer in layers_to_check:
            if layer not in self.grid.obstacles:
                continue

            for dx in range(-check_radius, check_radius + 1):
                for dy in range(-check_radius, check_radius + 1):
                    check_x, check_y = grid_x + dx, grid_y + dy

                    if not self.grid.is_within_bounds(check_x, check_y):
                        continue

                    if (check_x, check_y) in self.grid.obstacles[layer]:
                        dist = math.sqrt(dx*dx + dy*dy) * self.grid.resolution_mm
                        min_obstacle_dist = min(min_obstacle_dist, dist)

        # Penalize positions close to obstacles
        if min_obstacle_dist < 1.0:  # Within 1mm of obstacle
            score += (1.0 - min_obstacle_dist) * 10.0  # Heavy penalty

        # Score component 2: Distance from target (minimize deviation)
        if 'target_pos' in context:
            target = context['target_pos']
            dist_from_target = math.sqrt(
                (position[0] - target[0])**2 + (position[1] - target[1])**2
            )
            score += dist_from_target * 0.5  # Light penalty for distance

        # Score component 3: Prefer positions with good routing cost on affected layers
        for layer in layers_to_check:
            cell_cost = self.grid.get_cell_cost(grid_x, grid_y, layer)
            if cell_cost > 1.0:
                score += (cell_cost - 1.0) * 2.0  # Penalty for high-cost cells

        # Score component 4: Prefer blind/buried vias over through-hole when possible
        # (Through-hole vias affect more layers and may cause routing congestion)
        via_type = context.get('via_type', 'through')
        if via_type == 'through':
            score += 0.5  # Slight penalty for through-hole (encourages blind/buried when available)

        return score
