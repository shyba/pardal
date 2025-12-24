"""
Crossing Detector Module

Detects crossing traces between different nets on the same layer.
Used for iterative refinement in hybrid Z3 + A* router.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple, Set, Optional


@dataclass
class Crossing:
    """Represents a crossing between two nets."""
    net1: str
    net2: str
    cell: Tuple[int, int]  # Grid coordinates
    layer: str


class CrossingDetector:
    """Detect crossing traces between different nets."""

    def __init__(self, resolution_mm: float = 1.0):
        """
        Initialize crossing detector.

        Args:
            resolution_mm: Grid resolution in millimeters (default 1.0mm)
        """
        self.resolution_mm = resolution_mm

    def detect_crossings(
        self,
        net_paths: Dict[str, List[Tuple[float, float]]],
        layer: str = "F.Cu"
    ) -> List[Crossing]:
        """
        Find all crossing points between different nets.

        Uses TWO methods:
        1. Grid cell overlap detection (catches obvious overlaps)
        2. Line segment intersection (catches diagonal crossings)

        Args:
            net_paths: Dict of net_name -> path (list of mm points)
            layer: PCB layer (default "F.Cu")

        Returns:
            List of Crossing objects where nets cross
        """
        crossings = []
        seen_pairs = set()  # Track (net1, net2) pairs already reported

        # Method 1: Grid cell overlap (fast, catches obvious overlaps)
        cell_occupation: Dict[Tuple[int, int], Set[str]] = {}

        for net_name, path in net_paths.items():
            cells = self._path_to_cells(path)
            for cell in cells:
                if cell not in cell_occupation:
                    cell_occupation[cell] = set()
                cell_occupation[cell].add(net_name)

        for cell, nets in cell_occupation.items():
            if len(nets) > 1:
                nets_list = sorted(list(nets))
                for i in range(len(nets_list)):
                    for j in range(i + 1, len(nets_list)):
                        pair = (nets_list[i], nets_list[j])
                        if pair not in seen_pairs:
                            seen_pairs.add(pair)
                            crossings.append(Crossing(
                                net1=nets_list[i],
                                net2=nets_list[j],
                                cell=cell,
                                layer=layer
                            ))

        # Method 2: Line segment intersection (catches diagonal crossings)
        net_names = list(net_paths.keys())
        for i in range(len(net_names)):
            for j in range(i + 1, len(net_names)):
                net1, net2 = net_names[i], net_names[j]
                pair = tuple(sorted([net1, net2]))

                if pair in seen_pairs:
                    continue

                path1 = net_paths[net1]
                path2 = net_paths[net2]

                intersection = self._find_segment_intersection(path1, path2)
                if intersection:
                    seen_pairs.add(pair)
                    cell = self._mm_to_grid(intersection)
                    crossings.append(Crossing(
                        net1=pair[0],
                        net2=pair[1],
                        cell=cell,
                        layer=layer
                    ))

        return crossings

    def _find_segment_intersection(
        self,
        path1: List[Tuple[float, float]],
        path2: List[Tuple[float, float]]
    ) -> Optional[Tuple[float, float]]:
        """
        Find first intersection between two paths (line segment pairs).

        Args:
            path1: First path as list of points
            path2: Second path as list of points

        Returns:
            Intersection point (x, y) or None if no intersection
        """
        for i in range(len(path1) - 1):
            p1, p2 = path1[i], path1[i + 1]
            for j in range(len(path2) - 1):
                p3, p4 = path2[j], path2[j + 1]
                intersection = self._segments_intersect(p1, p2, p3, p4)
                if intersection:
                    return intersection
        return None

    def _segments_intersect(
        self,
        p1: Tuple[float, float],
        p2: Tuple[float, float],
        p3: Tuple[float, float],
        p4: Tuple[float, float]
    ) -> Optional[Tuple[float, float]]:
        """
        Check if line segments (p1,p2) and (p3,p4) intersect.

        Uses parametric line intersection formula.

        Returns:
            Intersection point (x, y) or None if no intersection
        """
        x1, y1 = p1
        x2, y2 = p2
        x3, y3 = p3
        x4, y4 = p4

        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)

        if abs(denom) < 1e-10:
            return None  # Parallel or coincident

        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
        u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom

        # Check if intersection is within both segments (not at endpoints)
        eps = 0.01
        if eps < t < 1 - eps and eps < u < 1 - eps:
            x = x1 + t * (x2 - x1)
            y = y1 + t * (y2 - y1)
            return (x, y)

        return None

    def _path_to_cells(
        self,
        path: List[Tuple[float, float]]
    ) -> Set[Tuple[int, int]]:
        """
        Convert a path in mm to a set of grid cells.

        Uses line interpolation (Bresenham-style) between consecutive waypoints.

        Args:
            path: List of (x, y) points in mm

        Returns:
            Set of (grid_x, grid_y) tuples
        """
        cells = set()

        if not path:
            return cells

        # Add first point
        cells.add(self._mm_to_grid(path[0]))

        # Interpolate between consecutive points
        for i in range(len(path) - 1):
            start = path[i]
            end = path[i + 1]

            start_grid = self._mm_to_grid(start)
            end_grid = self._mm_to_grid(end)

            # Get cells along line
            line_cells = self._bresenham_line(start_grid, end_grid)
            cells.update(line_cells)

        return cells

    def _mm_to_grid(self, point: Tuple[float, float]) -> Tuple[int, int]:
        """
        Convert mm coordinates to grid coordinates.

        Args:
            point: (x, y) in mm

        Returns:
            (grid_x, grid_y) tuple
        """
        x, y = point
        grid_x = int(round(x / self.resolution_mm))
        grid_y = int(round(y / self.resolution_mm))
        return (grid_x, grid_y)

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
