"""
Routing Grid Module

Provides a discretized representation of the PCB board for pathfinding algorithms.
The grid divides the board into cells at a configurable resolution (default 0.1mm)
and tracks obstacles, clearances, and costs for routing on each layer.
"""

from typing import Set, Tuple, List, Optional
from dataclasses import dataclass, field
import math


@dataclass
class GridCell:
    """Represents a single cell in the routing grid."""
    x: int  # Grid x-coordinate
    y: int  # Grid y-coordinate
    layer: str  # Layer name (e.g., "F.Cu", "In1.Cu", "B.Cu")

    def __hash__(self):
        return hash((self.x, self.y, self.layer))

    def __eq__(self, other):
        return (self.x, self.y, self.layer) == (other.x, other.y, other.layer)


class RoutingGrid:
    """
    Discretized PCB board representation for routing algorithms.

    The grid divides the board into cells at a specified resolution (default 0.1mm).
    Each cell can be:
    - Free: Available for routing
    - Obstacle: Blocked by component, pad, or existing trace
    - Clearance: Within clearance distance of an obstacle

    Supports multi-layer routing with configurable layer stack.
    """

    def __init__(
        self,
        width_mm: float,
        height_mm: float,
        resolution_mm: float = 0.1,
        default_clearance_mm: float = 0.2,
        layers: Optional[List[str]] = None
    ):
        """
        Initialize the routing grid.

        Args:
            width_mm: Board width in millimeters
            height_mm: Board height in millimeters
            resolution_mm: Grid cell size in millimeters (default 0.1mm)
            default_clearance_mm: Default clearance around obstacles (default 0.2mm)
            layers: List of copper layer names in stack order (default: ["F.Cu", "B.Cu"])
        """
        self.width_mm = width_mm
        self.height_mm = height_mm
        self.resolution_mm = resolution_mm
        self.default_clearance_mm = default_clearance_mm

        # Store layer configuration
        self.layers = layers if layers is not None else ["F.Cu", "B.Cu"]

        # Calculate grid dimensions
        self.grid_width = int(math.ceil(width_mm / resolution_mm))
        self.grid_height = int(math.ceil(height_mm / resolution_mm))

        # Track obstacles per layer (dynamically created for all layers)
        self.obstacles: dict[str, Set[Tuple[int, int]]] = {
            layer: set() for layer in self.layers
        }

        # Track cells within clearance zones (different from hard obstacles)
        self.clearance_zones: dict[str, Set[Tuple[int, int]]] = {
            layer: set() for layer in self.layers
        }

        # Track crossing-forbidden zones (HARD BLOCK - prevents routing crossings)
        # These zones are wider than clearance zones and represent areas where
        # routing would create a crossing with an existing trace
        self.crossing_forbidden: dict[str, Set[Tuple[int, int]]] = {
            layer: set() for layer in self.layers
        }

        # Track forbidden zones by net (for removal during rip-up)
        self.forbidden_zones_by_net: dict[str, Set[Tuple[int, int, str]]] = {}

        # Cost map for preferential routing (lower cost = preferred)
        # Base cost is 1.0, obstacles have infinite cost
        self.cost_map: dict[str, dict[Tuple[int, int], float]] = {
            layer: {} for layer in self.layers
        }

        # Track via locations (x, y) in grid coordinates
        self.vias: Set[Tuple[int, int]] = set()

        # Performance optimization: Cache neighbor lookups
        # Key: (grid_x, grid_y, layer, allow_diagonals)
        # Value: List of (neighbor_cell, cost) tuples
        # Cleared when obstacles change via mark_obstacle/mark_via/mark_trace_segment
        self._neighbor_cache: dict[Tuple[int, int, str, bool], List[Tuple[GridCell, float]]] = {}

    @property
    def layer_count(self) -> int:
        """Get the number of routing layers."""
        return len(self.layers)

    def is_valid_layer(self, layer: str) -> bool:
        """Check if a layer name is valid for this grid.

        Args:
            layer: Layer name to check

        Returns:
            True if the layer is in the grid's layer list
        """
        return layer in self.layers

    def get_layer_index(self, layer: str) -> int:
        """Get the index of a layer in the stack (0 = top).

        Args:
            layer: Layer name

        Returns:
            Index of the layer

        Raises:
            ValueError: If layer not in grid's layer list
        """
        try:
            return self.layers.index(layer)
        except ValueError:
            raise ValueError(f"Layer {layer} not in grid's layer list: {self.layers}")

    def get_adjacent_layers(self, layer: str) -> List[str]:
        """Get layers adjacent to the given layer (for via transitions).

        Args:
            layer: Layer name

        Returns:
            List of adjacent layer names (up to 2: above and below)
        """
        idx = self.get_layer_index(layer)
        adjacent = []
        if idx > 0:
            adjacent.append(self.layers[idx - 1])
        if idx < len(self.layers) - 1:
            adjacent.append(self.layers[idx + 1])
        return adjacent

    def get_inner_layers(self) -> List[str]:
        """Get all inner copper layers (not F.Cu or B.Cu).

        Returns:
            List of inner layer names
        """
        return [layer for layer in self.layers if layer not in ("F.Cu", "B.Cu")]

    def get_layers_between(self, from_layer: str, to_layer: str) -> List[str]:
        """Get all layers between two layers (inclusive).

        Args:
            from_layer: Starting layer
            to_layer: Ending layer

        Returns:
            List of layer names from from_layer to to_layer
        """
        from_idx = self.get_layer_index(from_layer)
        to_idx = self.get_layer_index(to_layer)
        start, end = min(from_idx, to_idx), max(from_idx, to_idx)
        return self.layers[start:end + 1]

    def to_grid_coords(self, x_mm: float, y_mm: float) -> Tuple[int, int]:
        """
        Convert millimeter coordinates to grid indices.

        Args:
            x_mm: X-coordinate in millimeters
            y_mm: Y-coordinate in millimeters

        Returns:
            Tuple of (grid_x, grid_y) indices
        """
        grid_x = int(round(x_mm / self.resolution_mm))
        grid_y = int(round(y_mm / self.resolution_mm))
        return (grid_x, grid_y)

    def to_mm_coords(self, grid_x: int, grid_y: int) -> Tuple[float, float]:
        """
        Convert grid indices to millimeter coordinates.

        Args:
            grid_x: Grid x-coordinate
            grid_y: Grid y-coordinate

        Returns:
            Tuple of (x_mm, y_mm) coordinates
        """
        x_mm = grid_x * self.resolution_mm
        y_mm = grid_y * self.resolution_mm
        return (x_mm, y_mm)

    def is_within_bounds(self, grid_x: int, grid_y: int) -> bool:
        """
        Check if grid coordinates are within board boundaries.

        Args:
            grid_x: Grid x-coordinate
            grid_y: Grid y-coordinate

        Returns:
            True if within bounds, False otherwise
        """
        return (0 <= grid_x < self.grid_width and
                0 <= grid_y < self.grid_height)

    def mark_obstacle(
        self,
        x_mm: float,
        y_mm: float,
        layer: str,
        clearance_mm: Optional[float] = None,
        size_mm: float = 0.0
    ):
        """
        Mark a cell as an obstacle with clearance inflation.

        Args:
            x_mm: X-coordinate in millimeters
            y_mm: Y-coordinate in millimeters
            layer: Layer name ("F.Cu", "B.Cu", or "both")
            clearance_mm: Clearance distance (uses default if None)
            size_mm: Size of the obstacle (e.g., pad diameter)
        """
        clearance = clearance_mm if clearance_mm is not None else self.default_clearance_mm
        grid_x, grid_y = self.to_grid_coords(x_mm, y_mm)

        # Calculate clearance radius in grid cells
        obstacle_radius = int(math.ceil(size_mm / (2 * self.resolution_mm)))
        clearance_radius = int(math.ceil((size_mm / 2 + clearance) / self.resolution_mm))

        layers = ["F.Cu", "B.Cu"] if layer == "both" else [layer]

        for lyr in layers:
            # Mark obstacle cells
            for dx in range(-obstacle_radius, obstacle_radius + 1):
                for dy in range(-obstacle_radius, obstacle_radius + 1):
                    gx, gy = grid_x + dx, grid_y + dy
                    if self.is_within_bounds(gx, gy):
                        dist = math.sqrt(dx*dx + dy*dy) * self.resolution_mm
                        if dist <= size_mm / 2:
                            self.obstacles[lyr].add((gx, gy))

            # Mark clearance zone cells
            for dx in range(-clearance_radius, clearance_radius + 1):
                for dy in range(-clearance_radius, clearance_radius + 1):
                    gx, gy = grid_x + dx, grid_y + dy
                    if self.is_within_bounds(gx, gy):
                        dist = math.sqrt(dx*dx + dy*dy) * self.resolution_mm
                        if size_mm / 2 < dist <= (size_mm / 2 + clearance):
                            self.clearance_zones[lyr].add((gx, gy))

        # Clear neighbor cache when obstacles change
        self._neighbor_cache.clear()

    def mark_rectangle_obstacle(
        self,
        x_min_mm: float,
        y_min_mm: float,
        x_max_mm: float,
        y_max_mm: float,
        layer: str,
        clearance_mm: Optional[float] = None
    ):
        """
        Mark a rectangular area as an obstacle.

        Args:
            x_min_mm: Minimum X-coordinate in millimeters
            y_min_mm: Minimum Y-coordinate in millimeters
            x_max_mm: Maximum X-coordinate in millimeters
            y_max_mm: Maximum Y-coordinate in millimeters
            layer: Layer name ("F.Cu", "B.Cu", or "both")
            clearance_mm: Clearance distance around rectangle
        """
        clearance = clearance_mm if clearance_mm is not None else self.default_clearance_mm
        clearance_cells = int(math.ceil(clearance / self.resolution_mm))

        gx_min, gy_min = self.to_grid_coords(x_min_mm, y_min_mm)
        gx_max, gy_max = self.to_grid_coords(x_max_mm, y_max_mm)

        layers = ["F.Cu", "B.Cu"] if layer == "both" else [layer]

        for lyr in layers:
            # Mark obstacle cells
            for gx in range(gx_min, gx_max + 1):
                for gy in range(gy_min, gy_max + 1):
                    if self.is_within_bounds(gx, gy):
                        self.obstacles[lyr].add((gx, gy))

            # Mark clearance zone cells
            for gx in range(gx_min - clearance_cells, gx_max + clearance_cells + 1):
                for gy in range(gy_min - clearance_cells, gy_max + clearance_cells + 1):
                    if self.is_within_bounds(gx, gy):
                        # Only mark if not already an obstacle and outside the obstacle rectangle
                        if ((gx, gy) not in self.obstacles[lyr] and
                            not (gx_min <= gx <= gx_max and gy_min <= gy <= gy_max)):
                            self.clearance_zones[lyr].add((gx, gy))

        # Clear neighbor cache when obstacles change
        self._neighbor_cache.clear()

    def mark_trace_segment(
        self,
        start_mm: Tuple[float, float],
        end_mm: Tuple[float, float],
        layer: str,
        width_mm: float,
        clearance_mm: Optional[float] = None
    ):
        """
        Mark a trace segment as an obstacle using line rasterization.

        Args:
            start_mm: Start point (x, y) in millimeters
            end_mm: End point (x, y) in millimeters
            layer: Layer name ("F.Cu" or "B.Cu")
            width_mm: Trace width in millimeters
            clearance_mm: Clearance distance around trace
        """
        clearance = clearance_mm if clearance_mm is not None else self.default_clearance_mm

        start_grid = self.to_grid_coords(*start_mm)
        end_grid = self.to_grid_coords(*end_mm)

        # Bresenham's line algorithm to get cells along the trace
        cells = self._bresenham_line(start_grid, end_grid)

        # Calculate trace radius in grid cells
        trace_radius = int(math.ceil(width_mm / (2 * self.resolution_mm)))
        clearance_radius = int(math.ceil((width_mm / 2 + clearance) / self.resolution_mm))

        # Mark obstacles and clearances around each cell in the trace
        for cx, cy in cells:
            # Mark obstacle cells (trace itself)
            for dx in range(-trace_radius, trace_radius + 1):
                for dy in range(-trace_radius, trace_radius + 1):
                    gx, gy = cx + dx, cy + dy
                    if self.is_within_bounds(gx, gy):
                        dist = math.sqrt(dx*dx + dy*dy) * self.resolution_mm
                        if dist <= width_mm / 2:
                            self.obstacles[layer].add((gx, gy))

            # Mark clearance zone cells
            for dx in range(-clearance_radius, clearance_radius + 1):
                for dy in range(-clearance_radius, clearance_radius + 1):
                    gx, gy = cx + dx, cy + dy
                    if self.is_within_bounds(gx, gy):
                        dist = math.sqrt(dx*dx + dy*dy) * self.resolution_mm
                        if width_mm / 2 < dist <= (width_mm / 2 + clearance):
                            self.clearance_zones[layer].add((gx, gy))

        # Clear neighbor cache when obstacles change
        self._neighbor_cache.clear()

    def mark_crossing_forbidden_zone(
        self,
        start_mm: Tuple[float, float],
        end_mm: Tuple[float, float],
        layer: str,
        trace_width_mm: float = 0.25,
        net_name: Optional[str] = None
    ):
        """
        Mark a zone around a trace where crossing would occur (HARD BLOCK).

        This zone is WIDER than the clearance zone to prevent any routing
        that would create crossings. When a subsequent net encounters this
        zone, it MUST use a via to route around it.

        Args:
            start_mm: Start point (x, y) in millimeters
            end_mm: End point (x, y) in millimeters
            layer: Layer name ("F.Cu" or "B.Cu")
            trace_width_mm: Trace width in millimeters (default 0.25mm)
            net_name: Optional net name for tracking (enables removal via remove_net_forbidden_zones)
        """
        start_grid = self.to_grid_coords(*start_mm)
        end_grid = self.to_grid_coords(*end_mm)

        # Bresenham's line algorithm to get cells along the trace
        cells = self._bresenham_line(start_grid, end_grid)

        # Calculate crossing-forbidden radius (wider than clearance)
        # This corridor is wide enough to prevent any routing that would cross
        corridor_width = trace_width_mm + 0.3  # 0.3mm wider than trace
        forbidden_radius = int(math.ceil(corridor_width / (2 * self.resolution_mm)))

        # Mark forbidden zone around each cell in the trace
        for cx, cy in cells:
            for dx in range(-forbidden_radius, forbidden_radius + 1):
                for dy in range(-forbidden_radius, forbidden_radius + 1):
                    gx, gy = cx + dx, cy + dy
                    if self.is_within_bounds(gx, gy):
                        dist = math.sqrt(dx*dx + dy*dy) * self.resolution_mm
                        if dist <= corridor_width / 2:
                            self.crossing_forbidden[layer].add((gx, gy))

                            # Track by net if specified (for rip-up)
                            if net_name:
                                if net_name not in self.forbidden_zones_by_net:
                                    self.forbidden_zones_by_net[net_name] = set()
                                self.forbidden_zones_by_net[net_name].add((gx, gy, layer))

        # Clear neighbor cache when crossing zones change
        self._neighbor_cache.clear()

    def remove_net_forbidden_zones(self, net_name: str) -> None:
        """
        Remove all forbidden zones for a specific net.

        Allows rip-up and re-route by clearing zones marked for this net.

        Args:
            net_name: Net name whose forbidden zones should be removed
        """
        if net_name not in self.forbidden_zones_by_net:
            return  # No zones tracked for this net

        # Get all zones for this net
        zones_to_remove = self.forbidden_zones_by_net[net_name]

        # Remove from crossing_forbidden
        for gx, gy, layer in zones_to_remove:
            if (gx, gy) in self.crossing_forbidden.get(layer, set()):
                self.crossing_forbidden[layer].discard((gx, gy))

        # Remove from tracking dict
        del self.forbidden_zones_by_net[net_name]

        # Clear neighbor cache
        self._neighbor_cache.clear()

    def _bresenham_line(
        self,
        start: Tuple[int, int],
        end: Tuple[int, int]
    ) -> List[Tuple[int, int]]:
        """
        Bresenham's line algorithm to rasterize a line on the grid.

        Args:
            start: Start grid coordinates (x, y)
            end: End grid coordinates (x, y)

        Returns:
            List of grid cells along the line
        """
        x0, y0 = start
        x1, y1 = end

        cells = []
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy

        x, y = x0, y0

        while True:
            cells.append((x, y))

            if x == x1 and y == y1:
                break

            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy

        return cells

    def mark_via(
        self,
        x_mm: float,
        y_mm: float,
        size_mm: float = 0.8,
        via_layers: Optional[Tuple[str, ...]] = None
    ):
        """
        Mark a via location (obstacle on specified layers).

        Supports multi-layer boards with blind and buried vias:
        - If via_layers is None, marks all layers (through-hole)
        - If via_layers is specified, only marks those layers

        Args:
            x_mm: X-coordinate in millimeters
            y_mm: Y-coordinate in millimeters
            size_mm: Via diameter in millimeters
            via_layers: Tuple of layer names the via spans (None = all layers)
        """
        grid_x, grid_y = self.to_grid_coords(x_mm, y_mm)
        self.vias.add((grid_x, grid_y))

        # Determine which layers to mark
        if via_layers is None:
            # Through-hole via: mark all layers
            layers_to_mark = self.layers
        else:
            # Blind/buried via: mark only specified layers
            layers_to_mark = [l for l in via_layers if l in self.layers]

        # Mark via as obstacle on specified layers
        for layer in layers_to_mark:
            self.mark_obstacle(x_mm, y_mm, layer, size_mm=size_mm)

        # Cache is cleared by mark_obstacle() call above

    def is_valid_cell(self, grid_x: int, grid_y: int, layer: str, current_net: Optional[str] = None) -> bool:
        """
        Check if a cell is valid for routing (not obstacle, within bounds).

        Args:
            grid_x: Grid x-coordinate
            grid_y: Grid y-coordinate
            layer: Layer name ("F.Cu" or "B.Cu")
            current_net: Optional net name being routed (allows routing through own forbidden zones)

        Returns:
            True if cell is routable, False otherwise
        """
        if not self.is_within_bounds(grid_x, grid_y):
            return False

        if (grid_x, grid_y) in self.obstacles.get(layer, set()):
            return False

        # HARD BLOCK: Crossing-forbidden zones cannot be routed through
        # EXCEPT: Allow routing through zones created by the same net (for multi-point MST routing)
        if (grid_x, grid_y) in self.crossing_forbidden.get(layer, set()):
            # Check if this forbidden zone belongs to the current net
            if current_net and current_net in self.forbidden_zones_by_net:
                zone_key = (grid_x, grid_y, layer)
                if zone_key in self.forbidden_zones_by_net[current_net]:
                    # This zone belongs to current net, allow routing through
                    return True
            # Zone belongs to different net or no current net specified, block it
            return False

        return True

    def get_cell_cost(self, grid_x: int, grid_y: int, layer: str) -> float:
        """
        Get the routing cost for a cell.

        Args:
            grid_x: Grid x-coordinate
            grid_y: Grid y-coordinate
            layer: Layer name ("F.Cu" or "B.Cu")

        Returns:
            Routing cost (1.0 = base, higher = less preferred, inf = obstacle)
        """
        if not self.is_valid_cell(grid_x, grid_y, layer):
            return float('inf')

        # Check if in clearance zone (higher cost but still routable)
        if (grid_x, grid_y) in self.clearance_zones.get(layer, set()):
            return 2.0  # Double cost for clearance zones

        # Check custom cost map
        if (grid_x, grid_y) in self.cost_map.get(layer, {}):
            return self.cost_map[layer][(grid_x, grid_y)]

        return 1.0  # Base cost

    def get_neighbors(
        self,
        grid_x: int,
        grid_y: int,
        layer: str,
        allow_diagonals: bool = True,
        current_net: Optional[str] = None
    ) -> List[Tuple[GridCell, float]]:
        """
        Get valid neighboring cells for A* expansion.

        Uses per-instance caching to avoid redundant neighbor calculations.
        Cache is cleared when obstacles change (mark_obstacle, mark_via, etc.)

        Args:
            grid_x: Current grid x-coordinate
            grid_y: Current grid y-coordinate
            layer: Current layer ("F.Cu" or "B.Cu")
            allow_diagonals: Allow diagonal moves (default True)
            current_net: Optional net name (allows routing through own forbidden zones)

        Returns:
            List of (neighbor_cell, cost) tuples
        """
        # Check cache first (include current_net in key for MST routing)
        cache_key = (grid_x, grid_y, layer, allow_diagonals, current_net)
        if cache_key in self._neighbor_cache:
            return self._neighbor_cache[cache_key]

        # Calculate neighbors
        neighbors = []

        # Orthogonal neighbors (cost = resolution_mm)
        orthogonal = [(0, 1), (1, 0), (0, -1), (-1, 0)]
        for dx, dy in orthogonal:
            nx, ny = grid_x + dx, grid_y + dy
            if self.is_valid_cell(nx, ny, layer, current_net=current_net):
                cost = self.get_cell_cost(nx, ny, layer) * self.resolution_mm
                neighbors.append((GridCell(nx, ny, layer), cost))

        # Diagonal neighbors (cost = resolution_mm * sqrt(2))
        if allow_diagonals:
            diagonal = [(1, 1), (1, -1), (-1, 1), (-1, -1)]
            for dx, dy in diagonal:
                nx, ny = grid_x + dx, grid_y + dy
                if self.is_valid_cell(nx, ny, layer, current_net=current_net):
                    cost = self.get_cell_cost(nx, ny, layer) * self.resolution_mm * math.sqrt(2)
                    neighbors.append((GridCell(nx, ny, layer), cost))

        # Store in cache and return
        self._neighbor_cache[cache_key] = neighbors
        return neighbors

    def get_statistics(self) -> dict:
        """
        Get grid statistics for debugging and visualization.

        Returns:
            Dictionary with grid statistics
        """
        return {
            "dimensions": {
                "width_mm": self.width_mm,
                "height_mm": self.height_mm,
                "grid_width": self.grid_width,
                "grid_height": self.grid_height,
                "resolution_mm": self.resolution_mm,
                "total_cells": self.grid_width * self.grid_height
            },
            "obstacles": {
                "F.Cu": len(self.obstacles["F.Cu"]),
                "B.Cu": len(self.obstacles["B.Cu"]),
                "vias": len(self.vias)
            },
            "clearance_zones": {
                "F.Cu": len(self.clearance_zones["F.Cu"]),
                "B.Cu": len(self.clearance_zones["B.Cu"])
            },
            "crossing_forbidden_zones": {
                "F.Cu": len(self.crossing_forbidden["F.Cu"]),
                "B.Cu": len(self.crossing_forbidden["B.Cu"])
            },
            "routable_cells": {
                "F.Cu": self.grid_width * self.grid_height - len(self.obstacles["F.Cu"]) - len(self.crossing_forbidden["F.Cu"]),
                "B.Cu": self.grid_width * self.grid_height - len(self.obstacles["B.Cu"]) - len(self.crossing_forbidden["B.Cu"])
            }
        }
