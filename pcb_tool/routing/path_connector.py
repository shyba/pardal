"""
Path Connector Module

Connects Z3 waypoints into continuous paths using A* pathfinding.
Handles MST nets with multiple segments sharing endpoints.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple, Set, Optional
from pcb_tool.routing.pathfinder import PathFinder
from pcb_tool.routing.grid import RoutingGrid
from pcb_tool.routing.multi_net_router import RoutedNet, NetDefinition


@dataclass
class ConnectedPath:
    """Result of connecting waypoints for a net."""
    net_name: str
    path: List[Tuple[float, float]]  # Continuous path in mm
    layer: str
    success: bool


class PathConnector:
    """Connect Z3 waypoints into continuous paths using A* pathfinding."""

    def __init__(self, grid: RoutingGrid):
        """
        Initialize path connector.

        Args:
            grid: RoutingGrid instance for pathfinding
        """
        self.grid = grid
        self.pathfinder = PathFinder(grid)

    def connect_all_nets(
        self,
        z3_result: Dict[str, RoutedNet],
        net_segments: Dict[str, List[NetDefinition]],
        protected_cells: Optional[Set[Tuple[int, int]]] = None
    ) -> Dict[str, ConnectedPath]:
        """
        Connect all nets from Z3 waypoints to continuous paths.

        SEQUENTIAL approach to avoid crossings:
        1. Route first net with A*, add its FULL PATH to obstacles
        2. Route second net avoiding first net's path
        3. Continue for all nets

        This ensures each net's A* path avoids all previously routed nets.

        Args:
            z3_result: Dictionary of net_name -> RoutedNet from Z3 solver
            net_segments: Dictionary of net_name -> list of NetDefinition segments
            protected_cells: Optional set of grid cells to never block (e.g., all net endpoints)

        Returns:
            Dictionary of net_name -> ConnectedPath with continuous paths
        """
        connected_paths = {}

        # Collect all endpoint cells and their neighborhoods that must remain routable
        if protected_cells is None:
            protected_cells = set()
            for segments in net_segments.values():
                for seg in segments:
                    for point in [seg.start, seg.end]:
                        center = self.grid.to_grid_coords(*point)
                        # Protect center and adjacent cells (3x3 neighborhood)
                        for dx in [-1, 0, 1]:
                            for dy in [-1, 0, 1]:
                                protected_cells.add((center[0] + dx, center[1] + dy))

        # Store original obstacles to restore later
        original_obstacles = {}
        for layer in ["F.Cu", "B.Cu"]:
            original_obstacles[layer] = self.grid.obstacles[layer].copy()

        # Track cells used by already-routed nets
        # These become obstacles for subsequent nets
        routed_cells = set()  # Set of ((x, y), layer) tuples

        try:
            # Route nets sequentially, adding each path to obstacles

            for net_name, segments in net_segments.items():
                if net_name not in z3_result:
                    # Net not in Z3 result, mark as failed
                    connected_paths[net_name] = ConnectedPath(
                        net_name=net_name,
                        path=[],
                        layer="F.Cu",
                        success=False
                    )
                    continue

                # Add all previously routed cells as obstacles (except protected endpoints)
                for cell, layer in routed_cells:
                    if cell not in protected_cells:
                        self.grid.obstacles[layer].add(cell)

                # Clear neighbor cache after modifying obstacles
                self.grid._neighbor_cache.clear()

                # Connect segments for this net
                try:
                    layer = segments[0].layer if segments else "F.Cu"
                    path = self._connect_segments(segments, net_name, layer)

                    connected_paths[net_name] = ConnectedPath(
                        net_name=net_name,
                        path=path,
                        layer=layer,
                        success=len(path) > 0
                    )

                    # Add this net's A* path cells to routed_cells for future nets
                    if path:
                        path_cells = self._path_to_cells(path, layer)
                        routed_cells.update(path_cells)

                except Exception:
                    # Connection failed
                    connected_paths[net_name] = ConnectedPath(
                        net_name=net_name,
                        path=[],
                        layer=segments[0].layer if segments else "F.Cu",
                        success=False
                    )

        finally:
            # Restore original obstacles
            for layer in ["F.Cu", "B.Cu"]:
                self.grid.obstacles[layer] = original_obstacles[layer]

            # Clear neighbor cache after restoring
            self.grid._neighbor_cache.clear()

        return connected_paths

    def _connect_segments(
        self,
        segments: List[NetDefinition],
        net_name: str,
        layer: str
    ) -> List[Tuple[float, float]]:
        """
        Connect multiple segments of a net into a continuous path.

        For MST nets with multiple segments sharing endpoints,
        we need to connect them all together.

        Args:
            segments: List of NetDefinition segments for this net
            net_name: Net name
            layer: Layer to route on

        Returns:
            Continuous path as list of (x, y) points in mm
        """
        if not segments:
            return []

        if len(segments) == 1:
            # Single segment - simple path from start to end
            seg = segments[0]
            # Try single-layer first
            path = self.pathfinder.find_path(
                start_mm=seg.start,
                goal_mm=seg.end,
                layer=layer,
                force_single_layer=True,
                net_name=net_name
            )
            if path:
                return path
            # Fallback: try multi-layer routing (F.Cu → via → B.Cu → via → F.Cu)
            # Both start and end are on F.Cu (pads), but allow vias in between
            path = self.pathfinder.find_path(
                start_mm=seg.start,
                goal_mm=seg.end,
                layer=layer,
                target_layer=layer,  # Same layer for start/end
                force_single_layer=False,  # Allow vias
                net_name=net_name
            )
            return path if path else []

        # Multiple segments - connect them
        # Strategy: Connect segments sequentially
        all_points = []

        for segment in segments:
            # Try single-layer first
            path = self.pathfinder.find_path(
                start_mm=segment.start,
                goal_mm=segment.end,
                layer=layer,
                force_single_layer=True,
                net_name=net_name
            )
            if not path:
                # Fallback: try multi-layer routing with escape vias
                path = self.pathfinder.find_path(
                    start_mm=segment.start,
                    goal_mm=segment.end,
                    layer=layer,
                    target_layer=layer,  # Same layer for start/end
                    force_single_layer=False,  # Allow vias
                    net_name=net_name
                )

            if path:
                all_points.extend(path)
            else:
                # Failed to connect segment
                return []

        # Remove duplicate consecutive points
        if not all_points:
            return []

        deduplicated = [all_points[0]]
        for point in all_points[1:]:
            if point != deduplicated[-1]:
                deduplicated.append(point)

        return deduplicated

    def _path_to_cells(
        self,
        path: List[Tuple[float, float]],
        layer: str,
        clearance_cells: int = 1
    ) -> Set[Tuple[Tuple[int, int], str]]:
        """
        Convert a path in mm to a set of grid cells using line interpolation.

        Uses Bresenham-style line interpolation between consecutive waypoints.
        Adds a clearance buffer around the path to prevent adjacent crossings.

        Args:
            path: List of (x, y) points in mm
            layer: Layer name
            clearance_cells: Number of cells to buffer around path (default 1)

        Returns:
            Set of ((grid_x, grid_y), layer) tuples
        """
        cells = set()
        core_cells = set()

        for i in range(len(path) - 1):
            start = path[i]
            end = path[i + 1]

            # Convert to grid coordinates
            start_grid = self.grid.to_grid_coords(*start)
            end_grid = self.grid.to_grid_coords(*end)

            # Get cells along line using Bresenham
            line_cells = self._bresenham_line(start_grid, end_grid)

            for cell in line_cells:
                core_cells.add(cell)

        # Add clearance buffer around core cells
        for cell in core_cells:
            for dx in range(-clearance_cells, clearance_cells + 1):
                for dy in range(-clearance_cells, clearance_cells + 1):
                    buffered = (cell[0] + dx, cell[1] + dy)
                    if 0 <= buffered[0] < self.grid.grid_width and 0 <= buffered[1] < self.grid.grid_height:
                        cells.add((buffered, layer))

        return cells

    def _bresenham_line(
        self,
        start: Tuple[int, int],
        end: Tuple[int, int]
    ) -> List[Tuple[int, int]]:
        """
        Bresenham's line algorithm for grid line interpolation.

        Args:
            start: Start grid coordinates (x, y)
            end: End grid coordinates (x, y)

        Returns:
            List of (x, y) grid cells along the line
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
