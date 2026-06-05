"""
Path Finding Module

Implements A* pathfinding algorithm for PCB trace routing on a discretized grid.
Finds optimal paths that minimize trace length while avoiding obstacles and
maintaining clearances.

Supports multi-layer boards with:
- Through-hole vias (transition to any layer)
- Blind vias (outer to inner layer)
- Buried vias (inner to inner layer)
"""

from typing import List, Tuple, Optional, Dict, Set
from dataclasses import dataclass
import heapq
import math
import os
from array import array

from pardal.routing.grid import RoutingGrid, GridCell

try:
    from pardal.fastpath import astar_path as fast_astar_path
    from pardal.fastpath import astar_path_3d as fast_astar_path_3d
except Exception:
    fast_astar_path = None
    fast_astar_path_3d = None


@dataclass
class PathNode:
    """
    Node in the A* search tree.

    Represents a position in the search space with associated costs.
    """

    cell: GridCell
    g_cost: float  # Cost from start to this node
    h_cost: float  # Heuristic cost from this node to goal
    parent: Optional["PathNode"] = None

    @property
    def f_cost(self) -> float:
        """Total cost (g + h) for priority queue ordering."""
        return self.g_cost + self.h_cost

    def __lt__(self, other):
        """Comparison for priority queue (lower f_cost = higher priority)."""
        return self.f_cost < other.f_cost

    def __hash__(self):
        return hash((self.cell.x, self.cell.y, self.cell.layer))

    def __eq__(self, other):
        return (self.cell.x, self.cell.y, self.cell.layer) == (
            other.cell.x,
            other.cell.y,
            other.cell.layer,
        )


class PathFinder:
    """
    A* pathfinding algorithm for PCB trace routing.

    Finds optimal paths on a RoutingGrid that minimize trace length while
    avoiding obstacles and maintaining clearances.

    Supports multi-layer boards with configurable via types:
    - "through": Transition to any layer (default, most restrictive)
    - "blind": Transition from outer to adjacent inner layer
    - "buried": Transition between inner layers only
    """

    def __init__(
        self,
        grid: RoutingGrid,
        via_cost: float = 10.0,
        allowed_via_types: Optional[List[str]] = None,
        use_fastpath: Optional[bool] = None,
        enforce_via_keepout: bool = False,
    ):
        """
        Initialize the path finder.

        Args:
            grid: RoutingGrid instance with obstacle information
            via_cost: Cost penalty for layer transitions in mm equivalent (default 10.0)
            allowed_via_types: List of allowed via types ("through", "blind", "buried")
                              Defaults to ["through"] for standard routing
        """
        self.grid = grid
        self.via_cost = via_cost
        self.allowed_via_types = allowed_via_types or ["through"]
        if use_fastpath is None:
            env = os.getenv("PARDAL_FASTPATH")
            if env is None or env == "":
                use_fastpath = True
            else:
                use_fastpath = env.lower() in ("1", "true", "yes", "on")
        self.use_fastpath = bool(use_fastpath)
        self.enforce_via_keepout = bool(enforce_via_keepout)
        legacy_max_cells = os.getenv("PARDAL_FASTPATH_MAX_CELLS")
        if legacy_max_cells is not None and legacy_max_cells != "":
            legacy_max_cells_i = int(legacy_max_cells)
            self.max_fastpath_cells = legacy_max_cells_i
            self.max_fastpath_cells_2d = legacy_max_cells_i
            self.max_fastpath_cells_3d = legacy_max_cells_i
        else:
            # The 2D fastpath currently builds a nested Python list grid, so keep
            # a conservative default limit. The 3D fastpath uses contiguous
            # memoryviews, so it can safely handle somewhat larger searches.
            self.max_fastpath_cells_2d = int(
                os.getenv("PARDAL_FASTPATH_MAX_CELLS_2D", "2000000")
            )
            self.max_fastpath_cells_3d = int(
                os.getenv("PARDAL_FASTPATH_MAX_CELLS_3D", "5000000")
            )
            self.max_fastpath_cells = max(
                self.max_fastpath_cells_2d, self.max_fastpath_cells_3d
            )
        self.last_backend: Optional[str] = None

        # Via cost multipliers for different via types
        # Blind/buried vias are slightly preferred (less routing congestion)
        self.via_type_costs = {"through": 1.0, "blind": 0.9, "buried": 0.85}
        self.via_size_mm = 0.8

        # Track via locations from last find_path call
        # Format: [(x_mm, y_mm, from_layer, to_layer), ...]
        self.last_via_locations: List[Tuple[float, float, str, str]] = []

        # Track path cells with layer info from last find_path call
        # This allows callers to get layer info for segments
        self.last_path_cells: Optional[List[GridCell]] = None

    def find_path(
        self,
        start_mm: Tuple[float, float],
        goal_mm: Tuple[float, float],
        layer: str,
        target_layer: Optional[str] = None,
        allow_diagonals: bool = True,
        force_single_layer: bool = False,
        via_cost: Optional[float] = None,
        net_name: Optional[str] = None,
    ) -> Optional[List[Tuple[float, float]]]:
        """
        Find a path from start to goal using A*.

        Supports both single-layer and multi-layer routing. If target_layer is
        specified and different from start layer, enables multi-layer routing
        with automatic via placement.

        Args:
            start_mm: Start position (x, y) in millimeters
            goal_mm: Goal position (x, y) in millimeters
            layer: Start layer to route on ("F.Cu" or "B.Cu")
            target_layer: Target layer for goal (enables multi-layer if different)
            allow_diagonals: Allow diagonal moves (default True)
            force_single_layer: Force routing on single layer only (no vias)
            via_cost: Optional via cost override (defaults to self.via_cost)
            net_name: Optional net name (allows routing through own forbidden zones for MST)

        Returns:
            List of waypoints (x, y) in millimeters, or None if no path found
        """
        # Store net_name and layer for use in neighbor generation and path simplification
        self.current_net = net_name
        self._current_layer = layer

        # Default to single-layer routing
        if target_layer is None:
            target_layer = layer

        # Force both layers to be the same if single-layer mode
        if force_single_layer:
            target_layer = layer

        # Convert to grid coordinates
        start_grid = self.grid.to_grid_coords(*start_mm)
        goal_grid = self.grid.to_grid_coords(*goal_mm)

        # Check if start and goal are within bounds
        # NOTE: Don't check for obstacles - start/goal are typically at pads,
        # which are marked as obstacles to prevent other nets from crossing them,
        # but the current net must be able to start/end at its own pads
        if not self.grid.is_within_bounds(*start_grid):
            return None
        if not self.grid.is_within_bounds(*goal_grid):
            return None

        # Check if start/goal are in forbidden zones of other nets
        # (but allow routing through own net's forbidden zones for MST)
        if start_grid in self.grid.crossing_forbidden.get(layer, set()):
            if not (net_name and net_name in self.grid.forbidden_zones_by_net):
                return None
            zone_key = (*start_grid, layer)
            if zone_key not in self.grid.forbidden_zones_by_net.get(net_name, set()):
                return None

        if goal_grid in self.grid.crossing_forbidden.get(target_layer, set()):
            if not (net_name and net_name in self.grid.forbidden_zones_by_net):
                return None
            zone_key = (*goal_grid, target_layer)
            if zone_key not in self.grid.forbidden_zones_by_net.get(net_name, set()):
                return None

        # Fast-fail when the goal cell is not routable. We intentionally do NOT
        # apply this to the start cell because routes must be able to start on
        # pads (which are often marked as obstacles).
        if not self.grid.is_valid_cell(
            goal_grid[0], goal_grid[1], target_layer, current_net=net_name
        ):
            return None

        # Create start and goal cells
        start_cell = GridCell(start_grid[0], start_grid[1], layer)
        goal_cell = GridCell(goal_grid[0], goal_grid[1], target_layer)

        # Use provided via_cost or default to instance via_cost
        effective_via_cost = via_cost if via_cost is not None else self.via_cost

        # Fastpath for forced single-layer routing if enabled
        if (
            self.use_fastpath
            and fast_astar_path is not None
            and target_layer == layer
            and force_single_layer
        ):
            fast_path = self._fastpath_search(
                start_cell, goal_cell, layer, allow_diagonals, net_name
            )
            if fast_path is not None:
                return fast_path

        # Fastpath for via-enabled routing (3D A*) when using through-vias
        if (
            self.use_fastpath
            and fast_astar_path_3d is not None
            and not force_single_layer
            and self.grid.layer_count >= 2
            and self.allowed_via_types == ["through"]
        ):
            fast_path = self._fastpath_search_3d(
                start_cell,
                goal_cell,
                allow_diagonals,
                net_name,
                effective_via_cost,
            )
            if fast_path is not None:
                return fast_path

        # A* search with multi-layer support
        path_cells = self._astar_search(
            start_cell,
            goal_cell,
            target_layer,
            allow_diagonals,
            force_single_layer,
            effective_via_cost,
        )

        if path_cells is None:
            self.last_path_cells = None
            self.last_via_locations = []
            self.last_backend = None
            return None

        path_cells = self._nudge_via_transitions_off_pads(path_cells)

        # Store path cells for layer info access
        self.last_path_cells = path_cells
        self.last_backend = "python"

        # Mark vias at layer transitions and record via locations
        self._mark_vias_in_path(path_cells)

        return self._cells_to_mm_waypoints_layer_aware(path_cells)

    def find_path_result(
        self,
        start_mm: Tuple[float, float],
        goal_mm: Tuple[float, float],
        layer: str,
        target_layer: Optional[str] = None,
        allow_diagonals: bool = True,
        force_single_layer: bool = False,
        via_cost: Optional[float] = None,
        net_name: Optional[str] = None,
    ) -> "PathResult":
        """Find a path and return a structured result for programmatic use."""
        from pardal.routing.results import PathResult

        waypoints = self.find_path(
            start_mm=start_mm,
            goal_mm=goal_mm,
            layer=layer,
            target_layer=target_layer,
            allow_diagonals=allow_diagonals,
            force_single_layer=force_single_layer,
            via_cost=via_cost,
            net_name=net_name,
        )

        return PathResult(
            success=waypoints is not None,
            waypoints_mm=waypoints or [],
            backend=self.last_backend,
            path_cells=list(self.last_path_cells) if self.last_path_cells else None,
            via_locations=list(self.last_via_locations),
        )

    def _fastpath_search(
        self,
        start_cell: GridCell,
        goal_cell: GridCell,
        layer: str,
        allow_diagonals: bool,
        net_name: Optional[str],
    ) -> Optional[List[Tuple[float, float]]]:
        # Prefer the 3D fastpath even for 2D routes: it accepts a contiguous
        # memoryview cost grid and avoids building nested Python lists (which
        # becomes very expensive on large boards).
        total_cells = self.grid.grid_width * self.grid.grid_height
        if total_cells > self.max_fastpath_cells_3d:
            return None

        if fast_astar_path_3d is None:
            return None

        cost_grid = self._build_cost_grid_2d_mv(layer, net_name)
        if cost_grid is None:
            return None

        path3 = fast_astar_path_3d(
            cost_grid,
            (start_cell.x, start_cell.y, 0),
            (goal_cell.x, goal_cell.y, 0),
            diagonal=allow_diagonals,
            via_cost=0.0,
        )
        if not path3:
            return None

        self.last_path_cells = [GridCell(x, y, layer) for x, y, _z in path3]
        self.last_via_locations = []
        self.last_backend = "fastpath2d_mv"
        return self._cells_to_mm_waypoints_layer_aware(self.last_path_cells)

    def _build_cost_grid(
        self, layer: str, net_name: Optional[str]
    ) -> Optional[List[List[float]]]:
        width = self.grid.grid_width
        height = self.grid.grid_height
        if width <= 0 or height <= 0:
            return None

        cost = [[1.0 for _ in range(width)] for _ in range(height)]

        pad_net_map = getattr(self.grid, "pad_net_map", {})
        allowed_zone = set()
        if net_name:
            allowed_zone = self.grid.forbidden_zones_by_net.get(net_name, set())

        # Treat pads as an all-layer keepout (layer-agnostic), so routes won't
        # "duck under" pads on the opposite side. This matches the project's
        # simplified short-checking that ignores layers.
        #
        # We conservatively apply a radius-based keepout (~0.5mm) around pad
        # copper. Importantly, we only generate keepout from *other* nets' pads
        # for the current route so overlapping pad keepouts don't accidentally
        # "punch holes" near adjacent pins.
        if pad_net_map:
            keepout_mm = 0.5
            keepout_radius = int(math.ceil(keepout_mm / self.grid.resolution_mm))
            keepout_r2 = keepout_radius * keepout_radius

            pad_cells_by_net = getattr(self.grid, "_pad_xy_cells_by_net", None)
            if pad_cells_by_net is None:
                pad_cells_by_net = {}
                for (px, py, _layer), pnet in pad_net_map.items():
                    pad_cells_by_net.setdefault(pnet, set()).add((px, py))
                setattr(self.grid, "_pad_xy_cells_by_net", pad_cells_by_net)

            keepout_offsets = getattr(self.grid, "_pad_keepout_offsets", None)
            keepout_offsets_key = getattr(self.grid, "_pad_keepout_offsets_key", None)
            if keepout_offsets is None or keepout_offsets_key != keepout_radius:
                keepout_offsets = []
                for dx in range(-keepout_radius, keepout_radius + 1):
                    for dy in range(-keepout_radius, keepout_radius + 1):
                        if dx * dx + dy * dy <= keepout_r2:
                            keepout_offsets.append((dx, dy))
                setattr(self.grid, "_pad_keepout_offsets", keepout_offsets)
                setattr(self.grid, "_pad_keepout_offsets_key", keepout_radius)

            keepout_other_cache = getattr(self.grid, "_pad_keepout_other_by_net", None)
            if keepout_other_cache is None:
                keepout_other_cache = {}
                setattr(self.grid, "_pad_keepout_other_by_net", keepout_other_cache)

            cache_key = (net_name, keepout_radius)
            keepout_other = keepout_other_cache.get(cache_key)
            if keepout_other is None:
                keepout_other = set()
                if not net_name or net_name not in pad_cells_by_net:
                    # No net context: keepout from all pads.
                    source_iter = pad_cells_by_net.values()
                else:
                    # Keepout from other pads only.
                    source_iter = (
                        cells
                        for pnet, cells in pad_cells_by_net.items()
                        if pnet != net_name
                    )

                for cells in source_iter:
                    for px, py in cells:
                        for dx, dy in keepout_offsets:
                            gx = px + dx
                            gy = py + dy
                            if 0 <= gx < width and 0 <= gy < height:
                                keepout_other.add((gx, gy))

                keepout_other_cache[cache_key] = keepout_other

            for px, py in keepout_other:
                cost[py][px] = 0.0

        for x, y in self.grid.obstacles.get(layer, set()):
            if net_name and pad_net_map.get((x, y, layer)) == net_name:
                continue
            if net_name and (x, y, layer) in allowed_zone:
                continue
            cost[y][x] = 0.0

        for x, y in self.grid.crossing_forbidden.get(layer, set()):
            if net_name and (x, y, layer) in allowed_zone:
                continue
            cost[y][x] = 0.0

        # Clearance zones are HARD BLOCKS for other nets. The owning net (if any)
        # may route through its own clearance (useful for multi-point nets).
        clearance_owner = getattr(self.grid, "clearance_owner", {})
        for x, y in self.grid.clearance_zones.get(layer, set()):
            owner = clearance_owner.get((x, y, layer))
            if owner == net_name and cost[y][x] > 0:
                continue
            cost[y][x] = 0.0

        for (x, y), value in self.grid.cost_map.get(layer, {}).items():
            if cost[y][x] > 0:
                cost[y][x] = float(value)

        return cost

    def _build_cost_grid_3d(
        self,
        net_name: Optional[str],
    ) -> Optional[List[List[List[float]]]]:
        layers = self.grid.layers
        if not layers:
            return None
        out = []
        for layer in layers:
            layer_cost = self._build_cost_grid(layer, net_name)
            if layer_cost is None:
                return None
            out.append(layer_cost)
        return out

    def _fastpath_search_3d(
        self,
        start_cell: GridCell,
        goal_cell: GridCell,
        allow_diagonals: bool,
        net_name: Optional[str],
        via_cost_mm: float,
    ) -> Optional[List[Tuple[float, float]]]:
        total_cells = (
            self.grid.grid_width * self.grid.grid_height * self.grid.layer_count
        )
        if total_cells > self.max_fastpath_cells_3d:
            return None

        layer_to_idx = {name: idx for idx, name in enumerate(self.grid.layers)}
        if start_cell.layer not in layer_to_idx or goal_cell.layer not in layer_to_idx:
            return None

        via_cost_units = float(via_cost_mm) / float(self.grid.resolution_mm)
        start = (start_cell.x, start_cell.y, layer_to_idx[start_cell.layer])
        goal = (goal_cell.x, goal_cell.y, layer_to_idx[goal_cell.layer])

        # Prefer the contiguous memoryview build when supported, but fall back to nested
        # Python lists in environments without the Cython accelerator (e.g. KiCad docker).
        try:
            cost_grid = self._build_cost_grid_3d_mv(net_name)
            if cost_grid is None:
                return None
            path = fast_astar_path_3d(
                cost_grid,
                start,
                goal,
                diagonal=allow_diagonals,
                via_cost=via_cost_units,
            )
        except NotImplementedError:
            cost_grid = self._build_cost_grid_3d(net_name)
            if cost_grid is None:
                return None
            path = fast_astar_path_3d(
                cost_grid,
                start,
                goal,
                diagonal=allow_diagonals,
                via_cost=via_cost_units,
            )
        if not path:
            return None

        idx_to_layer = self.grid.layers
        path_cells = [GridCell(x, y, idx_to_layer[z]) for x, y, z in path]
        path_cells = self._nudge_via_transitions_off_pads(path_cells)
        self.last_path_cells = path_cells
        self.last_backend = "fastpath3d"

        # Mark vias + record via locations.
        self._mark_vias_in_path(path_cells)

        return self._cells_to_mm_waypoints_layer_aware(path_cells)

    def _build_cost_grid_3d_mv(self, net_name: Optional[str]) -> Optional[memoryview]:
        """Build a 3D cost grid as a contiguous memoryview (layers, y, x).

        This avoids constructing nested Python lists and avoids the wrapper's
        list->array conversion cost for large grids.
        """
        width = self.grid.grid_width
        height = self.grid.grid_height
        layers = self.grid.layers
        if width <= 0 or height <= 0 or not layers:
            return None

        pad_net_map = getattr(self.grid, "pad_net_map", {})
        allowed_zone = set()
        if net_name:
            allowed_zone = self.grid.forbidden_zones_by_net.get(net_name, set())

        # Base cost: 1.0 everywhere (fast C-level fill).
        total = len(layers) * width * height
        flat = array("d", [1.0]) * total

        def idx(layer_idx: int, x: int, y: int) -> int:
            return (layer_idx * height + y) * width + x

        # All-layer pad keepout (~0.5mm radius) to avoid "ducking under" pads.
        #
        # Keepout is generated from *other* nets' pads for the current route so
        # overlapping pad keepouts don't accidentally "punch holes" near dense
        # pinfields (e.g. TQFP/QFN).
        if pad_net_map:
            keepout_mm = 0.5
            keepout_radius = int(math.ceil(keepout_mm / self.grid.resolution_mm))
            keepout_r2 = keepout_radius * keepout_radius

            pad_cells_by_net = getattr(self.grid, "_pad_xy_cells_by_net", None)
            if pad_cells_by_net is None:
                pad_cells_by_net = {}
                for (px, py, _layer), pnet in pad_net_map.items():
                    pad_cells_by_net.setdefault(pnet, set()).add((px, py))
                setattr(self.grid, "_pad_xy_cells_by_net", pad_cells_by_net)

            keepout_offsets = getattr(self.grid, "_pad_keepout_offsets", None)
            keepout_offsets_key = getattr(self.grid, "_pad_keepout_offsets_key", None)
            if keepout_offsets is None or keepout_offsets_key != keepout_radius:
                keepout_offsets = []
                for dx in range(-keepout_radius, keepout_radius + 1):
                    for dy in range(-keepout_radius, keepout_radius + 1):
                        if dx * dx + dy * dy <= keepout_r2:
                            keepout_offsets.append((dx, dy))
                setattr(self.grid, "_pad_keepout_offsets", keepout_offsets)
                setattr(self.grid, "_pad_keepout_offsets_key", keepout_radius)

            keepout_other_cache = getattr(self.grid, "_pad_keepout_other_by_net", None)
            if keepout_other_cache is None:
                keepout_other_cache = {}
                setattr(self.grid, "_pad_keepout_other_by_net", keepout_other_cache)

            cache_key = (net_name, keepout_radius)
            keepout_other = keepout_other_cache.get(cache_key)
            if keepout_other is None:
                keepout_other = set()
                if not net_name or net_name not in pad_cells_by_net:
                    source_iter = pad_cells_by_net.values()
                else:
                    source_iter = (
                        cells
                        for pnet, cells in pad_cells_by_net.items()
                        if pnet != net_name
                    )

                for cells in source_iter:
                    for px, py in cells:
                        for dx, dy in keepout_offsets:
                            gx = px + dx
                            gy = py + dy
                            if 0 <= gx < width and 0 <= gy < height:
                                keepout_other.add((gx, gy))

                keepout_other_cache[cache_key] = keepout_other

            for px, py in keepout_other:
                for layer_idx in range(len(layers)):
                    flat[idx(layer_idx, px, py)] = 0.0

        for layer_idx, layer in enumerate(layers):
            # Obstacles (pads, traces, etc.)
            for x, y in self.grid.obstacles.get(layer, set()):
                if net_name and pad_net_map.get((x, y, layer)) == net_name:
                    continue
                if net_name and (x, y, layer) in allowed_zone:
                    continue
                flat[idx(layer_idx, x, y)] = 0.0

            # Crossing forbidden zones (hard blocks) except own-net zones.
            for x, y in self.grid.crossing_forbidden.get(layer, set()):
                if net_name and (x, y, layer) in allowed_zone:
                    continue
                flat[idx(layer_idx, x, y)] = 0.0

            # Clearance zones are hard blocks for other nets.
            clearance_owner = getattr(self.grid, "clearance_owner", {})
            for x, y in self.grid.clearance_zones.get(layer, set()):
                owner = clearance_owner.get((x, y, layer))
                i = idx(layer_idx, x, y)
                if owner == net_name and flat[i] > 0.0:
                    continue
                flat[i] = 0.0

            # Custom cost map unless already blocked.
            for (x, y), value in self.grid.cost_map.get(layer, {}).items():
                i = idx(layer_idx, x, y)
                if flat[i] > 0.0:
                    flat[i] = float(value)

        mv_flat = memoryview(flat).cast("B")
        return mv_flat.cast("d", shape=(len(layers), height, width))

    def _build_cost_grid_2d_mv(
        self, layer: str, net_name: Optional[str]
    ) -> Optional[memoryview]:
        """Build a single-layer cost grid as a contiguous memoryview (1, y, x)."""
        width = self.grid.grid_width
        height = self.grid.grid_height
        if width <= 0 or height <= 0:
            return None

        pad_net_map = getattr(self.grid, "pad_net_map", {})
        allowed_zone = set()
        if net_name:
            allowed_zone = self.grid.forbidden_zones_by_net.get(net_name, set())

        total = width * height
        flat = array("d", [1.0]) * total

        def idx(x: int, y: int) -> int:
            return y * width + x

        if pad_net_map:
            keepout_mm = 0.5
            keepout_radius = int(math.ceil(keepout_mm / self.grid.resolution_mm))
            keepout_r2 = keepout_radius * keepout_radius

            pad_cells_by_net = getattr(self.grid, "_pad_xy_cells_by_net", None)
            if pad_cells_by_net is None:
                pad_cells_by_net = {}
                for (px, py, _layer), pnet in pad_net_map.items():
                    pad_cells_by_net.setdefault(pnet, set()).add((px, py))
                setattr(self.grid, "_pad_xy_cells_by_net", pad_cells_by_net)

            keepout_offsets = getattr(self.grid, "_pad_keepout_offsets", None)
            keepout_offsets_key = getattr(self.grid, "_pad_keepout_offsets_key", None)
            if keepout_offsets is None or keepout_offsets_key != keepout_radius:
                keepout_offsets = []
                for dx in range(-keepout_radius, keepout_radius + 1):
                    for dy in range(-keepout_radius, keepout_radius + 1):
                        if dx * dx + dy * dy <= keepout_r2:
                            keepout_offsets.append((dx, dy))
                setattr(self.grid, "_pad_keepout_offsets", keepout_offsets)
                setattr(self.grid, "_pad_keepout_offsets_key", keepout_radius)

            keepout_other_cache = getattr(self.grid, "_pad_keepout_other_by_net", None)
            if keepout_other_cache is None:
                keepout_other_cache = {}
                setattr(self.grid, "_pad_keepout_other_by_net", keepout_other_cache)

            cache_key = (net_name, keepout_radius, layer)
            keepout_other = keepout_other_cache.get(cache_key)
            if keepout_other is None:
                keepout_other = set()
                if not net_name or net_name not in pad_cells_by_net:
                    source_iter = pad_cells_by_net.values()
                else:
                    source_iter = (
                        cells
                        for pnet, cells in pad_cells_by_net.items()
                        if pnet != net_name
                    )

                for cells in source_iter:
                    for px, py in cells:
                        for dx, dy in keepout_offsets:
                            gx = px + dx
                            gy = py + dy
                            if 0 <= gx < width and 0 <= gy < height:
                                keepout_other.add((gx, gy))

                keepout_other_cache[cache_key] = keepout_other

            for px, py in keepout_other:
                flat[idx(px, py)] = 0.0

        for x, y in self.grid.obstacles.get(layer, set()):
            if net_name and pad_net_map.get((x, y, layer)) == net_name:
                continue
            if net_name and (x, y, layer) in allowed_zone:
                continue
            flat[idx(x, y)] = 0.0

        for x, y in self.grid.crossing_forbidden.get(layer, set()):
            if net_name and (x, y, layer) in allowed_zone:
                continue
            flat[idx(x, y)] = 0.0

        clearance_owner = getattr(self.grid, "clearance_owner", {})
        for x, y in self.grid.clearance_zones.get(layer, set()):
            owner = clearance_owner.get((x, y, layer))
            i = idx(x, y)
            if owner == net_name and flat[i] > 0.0:
                continue
            flat[i] = 0.0

        for (x, y), value in self.grid.cost_map.get(layer, {}).items():
            i = idx(x, y)
            if flat[i] > 0.0:
                flat[i] = float(value)

        mv_flat = memoryview(flat).cast("B")
        return mv_flat.cast("d", shape=(1, height, width))

    def _nudge_via_transitions_off_pads(
        self, path_cells: List[GridCell]
    ) -> List[GridCell]:
        """Move layer transitions off pad centers when possible.

        Our simplified DRC model treats via-in-pad as an error (drill holes co-located
        with pad centers). The 3D A* can legitimately choose a layer transition
        at a pad cell (especially at endpoints). This pass tries to shift such
        transitions by one cell to keep the routed result DRC-clean.
        """
        if len(path_cells) < 2:
            return path_cells

        pad_centers = getattr(self.grid, "pad_centers", None)
        if not pad_centers:
            return path_cells

        current_net = getattr(self, "current_net", None)

        out: List[GridCell] = [path_cells[0]]
        for cur in path_cells[1:]:
            prev = out[-1]

            # Detect a via transition (same x/y, different layer).
            if prev.x == cur.x and prev.y == cur.y and prev.layer != cur.layer:
                if (cur.x, cur.y) in pad_centers:
                    from_layer = prev.layer
                    to_layer = cur.layer
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nx = cur.x + dx
                        ny = cur.y + dy
                        if not self.grid.is_within_bounds(nx, ny):
                            continue
                        if (nx, ny) in pad_centers:
                            continue
                        if not self.grid.is_valid_cell(
                            nx, ny, from_layer, current_net=current_net
                        ):
                            continue
                        if not self.grid.is_valid_cell(
                            nx, ny, to_layer, current_net=current_net
                        ):
                            continue

                        out.append(GridCell(nx, ny, from_layer))
                        out.append(GridCell(nx, ny, to_layer))
                        break
                    else:
                        out.append(cur)
                else:
                    out.append(cur)
            else:
                out.append(cur)

        return out

    def _cells_to_mm_waypoints_layer_aware(
        self, path_cells: List[GridCell]
    ) -> List[Tuple[float, float]]:
        """Convert path cells to (x_mm, y_mm) waypoints, simplifying per-layer runs.

        This preserves via waypoints so downstream segment layer assignment (based
        on via locations) remains correct, while still reducing waypoint count to
        keep routing artifacts and DRC output stable.
        """
        if not path_cells:
            return []

        previous_layer = getattr(self, "_current_layer", None)

        def compress_run_cells(run: List[GridCell]) -> List[GridCell]:
            if len(run) <= 2:
                return run

            out: List[GridCell] = [run[0]]
            prev = run[0]
            prev_dx: Optional[int] = None
            prev_dy: Optional[int] = None

            for cur in run[1:]:
                dx = cur.x - prev.x
                dy = cur.y - prev.y

                # Ignore duplicates (shouldn't happen within a single-layer run).
                if dx == 0 and dy == 0:
                    prev = cur
                    continue

                if prev_dx is None:
                    prev_dx, prev_dy = dx, dy
                elif dx != prev_dx or dy != prev_dy:
                    # Direction change: keep the turning point.
                    out.append(prev)
                    prev_dx, prev_dy = dx, dy

                prev = cur

            if out[-1] != run[-1]:
                out.append(run[-1])
            return out

        def append_run(
            out: List[Tuple[float, float]],
            run: List[GridCell],
        ) -> None:
            if not run:
                return
            run = compress_run_cells(run)
            pts = [self.grid.to_mm_coords(cell.x, cell.y) for cell in run]

            if out and pts and out[-1] == pts[0]:
                out.extend(pts[1:])
            else:
                out.extend(pts)

        out: List[Tuple[float, float]] = []
        run: List[GridCell] = [path_cells[0]]
        for cell in path_cells[1:]:
            if cell.layer == run[-1].layer:
                run.append(cell)
                continue
            append_run(out, run)
            run = [cell]
        append_run(out, run)

        if previous_layer is not None:
            self._current_layer = previous_layer

        return out

    def _astar_search(
        self,
        start: GridCell,
        goal: GridCell,
        target_layer: str,
        allow_diagonals: bool,
        force_single_layer: bool = False,
        via_cost: float = None,
    ) -> Optional[List[GridCell]]:
        """
        Core A* search algorithm with multi-layer support.

        Args:
            start: Start grid cell
            goal: Goal grid cell
            target_layer: Target layer for goal (enables multi-layer if different from start)
            allow_diagonals: Allow diagonal moves
            force_single_layer: Disable layer transitions (single-layer routing only)
            via_cost: Via cost for layer transitions (uses self.via_cost if None)

        Returns:
            List of GridCell objects forming the path, or None if no path found
        """
        # Priority queue: (f_cost, counter, node)
        # Counter ensures stable ordering for equal f_costs
        open_set = []
        counter = 0

        # Create start node
        start_node = PathNode(
            cell=start, g_cost=0.0, h_cost=self._heuristic(start, goal), parent=None
        )

        heapq.heappush(open_set, (start_node.f_cost, counter, start_node))
        counter += 1

        # Track visited cells and their best g_cost
        visited: Dict[Tuple[int, int, str], float] = {}

        # Track nodes for path reconstruction
        node_map: Dict[Tuple[int, int, str], PathNode] = {
            (start.x, start.y, start.layer): start_node
        }

        while open_set:
            # Get node with lowest f_cost
            _, _, current_node = heapq.heappop(open_set)

            # Check if we reached the goal
            if (
                current_node.cell.x == goal.x
                and current_node.cell.y == goal.y
                and current_node.cell.layer == goal.layer
            ):
                return self._reconstruct_path(current_node)

            # Mark as visited
            cell_key = (
                current_node.cell.x,
                current_node.cell.y,
                current_node.cell.layer,
            )

            # Skip if we've already found a better path to this cell
            if cell_key in visited and visited[cell_key] <= current_node.g_cost:
                continue

            visited[cell_key] = current_node.g_cost

            # Explore neighbors (same-layer moves)
            current_net = getattr(self, "current_net", None)
            neighbors = self.grid.get_neighbors(
                current_node.cell.x,
                current_node.cell.y,
                current_node.cell.layer,
                allow_diagonals,
                current_net=current_net,
            )

            # Add layer transition neighbors if multi-layer routing enabled
            # Allow via transitions when force_single_layer is False, even if start==target
            # This enables "escape routing": F.Cu → via → B.Cu → via → F.Cu
            if not force_single_layer:
                layer_neighbors = self._get_layer_transition_neighbors(
                    current_node.cell.x,
                    current_node.cell.y,
                    current_node.cell.layer,
                    target_layer,
                    via_cost,
                )
                neighbors.extend(layer_neighbors)

            for neighbor_cell, move_cost in neighbors:
                neighbor_key = (neighbor_cell.x, neighbor_cell.y, neighbor_cell.layer)

                # Calculate tentative g_cost
                tentative_g = current_node.g_cost + move_cost

                # Skip if we've already found a better path to this neighbor
                if neighbor_key in visited and visited[neighbor_key] <= tentative_g:
                    continue

                # Create or update neighbor node
                if neighbor_key in node_map:
                    neighbor_node = node_map[neighbor_key]
                    if tentative_g >= neighbor_node.g_cost:
                        continue  # Not a better path
                    # Update with better path
                    neighbor_node.g_cost = tentative_g
                    neighbor_node.parent = current_node
                else:
                    # Create new node
                    neighbor_node = PathNode(
                        cell=neighbor_cell,
                        g_cost=tentative_g,
                        h_cost=self._heuristic(neighbor_cell, goal),
                        parent=current_node,
                    )
                    node_map[neighbor_key] = neighbor_node

                # Add to open set
                heapq.heappush(open_set, (neighbor_node.f_cost, counter, neighbor_node))
                counter += 1

        # No path found
        return None

    def _heuristic(self, cell: GridCell, goal: GridCell) -> float:
        """
        Calculate heuristic cost (Manhattan distance in mm).

        Args:
            cell: Current cell
            goal: Goal cell

        Returns:
            Estimated cost to reach goal from cell
        """
        dx = abs(cell.x - goal.x)
        dy = abs(cell.y - goal.y)

        # Manhattan distance in grid units, converted to mm
        manhattan = (dx + dy) * self.grid.resolution_mm

        # Diagonal distance (Chebyshev with diagonal cost)
        # This is admissible and gives better paths with diagonals
        diagonal = max(dx, dy) * self.grid.resolution_mm

        return diagonal

    def _get_layer_transition_neighbors(
        self,
        grid_x: int,
        grid_y: int,
        current_layer: str,
        target_layer: str,
        via_cost: Optional[float] = None,
    ) -> List[Tuple[GridCell, float]]:
        """
        Get neighbors on other layers (via placement).

        Supports multi-layer boards with different via types:
        - Through-hole: Can transition to any layer
        - Blind: Can transition from outer to adjacent inner, or vice versa
        - Buried: Can transition between inner layers only

        Args:
            grid_x: Current grid x-coordinate
            grid_y: Current grid y-coordinate
            current_layer: Current layer
            target_layer: Target layer for routing
            via_cost: Optional via cost override (uses self.via_cost if None)

        Returns:
            List of (neighbor_cell, cost) tuples for layer transitions
        """
        neighbors = []
        current_net = getattr(self, "current_net", None)

        # Use provided via_cost or default to instance via_cost
        effective_via_cost = via_cost if via_cost is not None else self.via_cost

        # Get possible layer transitions based on allowed via types
        transitions = self._get_possible_layer_transitions(current_layer)

        for to_layer, via_type in transitions:
            # Check if target layer is valid for routing at this position
            if not self.grid.is_valid_cell(
                grid_x, grid_y, to_layer, current_net=current_net
            ):
                continue

            if self.enforce_via_keepout:
                # A layer transition implies a via whose copper and clearance occupy
                # an area around the transition cell. The 3D A* otherwise checks only
                # the via center cell, which can lead to via-vs-trace collisions in KiCad.
                if not self._via_site_is_clear(
                    grid_x=grid_x,
                    grid_y=grid_y,
                    from_layer=current_layer,
                    to_layer=to_layer,
                    via_type=via_type,
                    net_name=current_net,
                ):
                    continue

            # Calculate cost with via type multiplier
            type_cost = self.via_type_costs.get(via_type, 1.0)
            transition_cost = effective_via_cost * type_cost

            # Create neighbor cell on target layer at same position
            neighbor_cell = GridCell(grid_x, grid_y, to_layer)
            neighbors.append((neighbor_cell, transition_cost))

        return neighbors

    def _via_site_is_clear(
        self,
        *,
        grid_x: int,
        grid_y: int,
        from_layer: str,
        to_layer: str,
        via_type: str,
        net_name: Optional[str],
    ) -> bool:
        via_layers: tuple[str, ...]
        if via_type == "through":
            via_layers = tuple(self.grid.layers)
        else:
            via_layers = tuple(self.grid.get_layers_between(from_layer, to_layer))

        keepout_mm = self.via_size_mm / 2.0 + self.grid.default_clearance_mm
        keepout_cells = int(math.ceil(keepout_mm / self.grid.resolution_mm))
        res = self.grid.resolution_mm
        pad_net_map = getattr(self.grid, "pad_net_map", {})
        allowed_zone = set()
        if net_name:
            allowed_zone = self.grid.forbidden_zones_by_net.get(net_name, set())

        for layer in via_layers:
            for dx in range(-keepout_cells, keepout_cells + 1):
                for dy in range(-keepout_cells, keepout_cells + 1):
                    gx = grid_x + dx
                    gy = grid_y + dy
                    if not self.grid.is_within_bounds(gx, gy):
                        continue
                    dist = math.sqrt(dx * dx + dy * dy) * res
                    if dist > keepout_mm:
                        continue
                    if (gx, gy) in self.grid.obstacles.get(layer, set()):
                        if net_name and pad_net_map.get((gx, gy, layer)) == net_name:
                            continue
                        if net_name and (gx, gy, layer) in allowed_zone:
                            continue
                        return False
                    if (gx, gy) in self.grid.crossing_forbidden.get(layer, set()):
                        if net_name and (gx, gy, layer) in allowed_zone:
                            continue
                        return False
        return True

    def _get_possible_layer_transitions(
        self, current_layer: str
    ) -> List[Tuple[str, str]]:
        """
        Get possible layer transitions from current layer based on allowed via types.

        Args:
            current_layer: Current layer name

        Returns:
            List of (target_layer, via_type) tuples
        """
        transitions = []
        layers = self.grid.layers
        current_idx = layers.index(current_layer) if current_layer in layers else -1

        if current_idx == -1:
            return transitions

        outer_layers = {"F.Cu", "B.Cu"}
        is_outer = current_layer in outer_layers

        for via_type in self.allowed_via_types:
            if via_type == "through":
                # Through-hole: can go to any other layer
                for layer in layers:
                    if layer != current_layer:
                        transitions.append((layer, "through"))

            elif via_type == "blind":
                # Blind: from outer to adjacent inner, or inner to outer
                if is_outer:
                    # From outer layer, can go to adjacent inner layers
                    adjacent = self.grid.get_adjacent_layers(current_layer)
                    for adj_layer in adjacent:
                        if adj_layer not in outer_layers:
                            transitions.append((adj_layer, "blind"))
                else:
                    # From inner layer, can go to adjacent outer if exists
                    adjacent = self.grid.get_adjacent_layers(current_layer)
                    for adj_layer in adjacent:
                        if adj_layer in outer_layers:
                            transitions.append((adj_layer, "blind"))

            elif via_type == "buried":
                # Buried: between inner layers only (no outer layers involved)
                if not is_outer:
                    adjacent = self.grid.get_adjacent_layers(current_layer)
                    for adj_layer in adjacent:
                        if adj_layer not in outer_layers:
                            transitions.append((adj_layer, "buried"))

        return transitions

    def _mark_vias_in_path(self, path_cells: List[GridCell]) -> None:
        """
        Mark vias in grid at layer transition points.

        For multi-layer boards, determines the correct via layer span
        based on the layers being transitioned between.

        Also records via locations in self.last_via_locations for callers
        to use when creating segments with proper layer assignments.

        Args:
            path_cells: List of GridCell objects forming the path
        """
        # Clear previous via locations
        self.last_via_locations = []

        for i in range(len(path_cells) - 1):
            current_cell = path_cells[i]
            next_cell = path_cells[i + 1]

            # Check if layer changes between consecutive cells
            if current_cell.layer != next_cell.layer:
                # Layer transition detected - mark via
                x_mm, y_mm = self.grid.to_mm_coords(current_cell.x, current_cell.y)

                # Record via location for segment creation
                self.last_via_locations.append(
                    (x_mm, y_mm, current_cell.layer, next_cell.layer)
                )

                # Determine via layers (all layers between the two transition layers)
                via_layers = tuple(
                    self.grid.get_layers_between(current_cell.layer, next_cell.layer)
                )

                current_net = getattr(self, "current_net", None)
                self.grid.mark_via(
                    x_mm,
                    y_mm,
                    size_mm=self.via_size_mm,
                    via_layers=via_layers,
                    clearance_mm=self.grid.default_clearance_mm,
                    net_name=current_net,
                )

    def _reconstruct_path(self, goal_node: PathNode) -> List[GridCell]:
        """
        Reconstruct path from goal node by following parent pointers.

        Args:
            goal_node: The goal node reached by A*

        Returns:
            List of GridCell objects from start to goal
        """
        path = []
        current = goal_node

        while current is not None:
            path.append(current.cell)
            current = current.parent

        # Reverse to get start-to-goal order
        path.reverse()
        return path

    def _simplify_path(
        self, path: List[Tuple[float, float]], epsilon: float = 0.01
    ) -> List[Tuple[float, float]]:
        """
        Simplify path by removing redundant waypoints using Douglas-Peucker algorithm.

        Removes waypoints that are collinear (within epsilon tolerance) to reduce
        the number of waypoints while maintaining path shape.

        Args:
            path: List of (x, y) waypoints in millimeters
            epsilon: Tolerance for collinearity (default 0.01mm)

        Returns:
            Simplified list of waypoints
        """
        if len(path) <= 2:
            return path

        # Always keep start and end
        simplified = [path[0]]

        i = 0
        while i < len(path) - 1:
            # Try to extend the current segment as far as possible
            j = i + 2
            while j < len(path):
                # Check if all points between i and j are collinear
                if not self._is_segment_clear(path, i, j, epsilon):
                    break
                j += 1

            # Add the farthest collinear point
            simplified.append(path[j - 1])
            i = j - 1

        # Ensure end point is included
        if simplified[-1] != path[-1]:
            simplified.append(path[-1])

        return simplified

    def _is_segment_clear(
        self,
        path: List[Tuple[float, float]],
        start_idx: int,
        end_idx: int,
        epsilon: float,
    ) -> bool:
        """
        Check if segment can be simplified (points are collinear AND no obstacles).

        Args:
            path: List of waypoints
            start_idx: Start index
            end_idx: End index
            epsilon: Tolerance for collinearity

        Returns:
            True if all intermediate points are within epsilon of the line
            AND the simplified segment doesn't cross any obstacles
        """
        if end_idx - start_idx <= 1:
            return True

        start = path[start_idx]
        end = path[end_idx]

        # Check each intermediate point for collinearity
        for i in range(start_idx + 1, end_idx):
            point = path[i]
            dist = self._point_to_line_distance(point, start, end)
            if dist > epsilon:
                return False

        # Also check that the simplified segment doesn't cross obstacles
        # Use the current layer from the pathfinder (set during find_path)
        layer = getattr(self, "_current_layer", "F.Cu")
        current_net = getattr(self, "current_net", None)

        # Sample points along the segment to check for obstacles
        start_gx, start_gy = self.grid.to_grid_coords(*start)
        end_gx, end_gy = self.grid.to_grid_coords(*end)

        # Use Bresenham to get all cells along the line
        cells = self._bresenham_line(start_gx, start_gy, end_gx, end_gy)
        for gx, gy in cells:
            if not self.grid.is_valid_cell(gx, gy, layer, current_net=current_net):
                # Obstacle in the way - can't simplify
                return False

        return True

    def _bresenham_line(
        self, x0: int, y0: int, x1: int, y1: int
    ) -> List[Tuple[int, int]]:
        """
        Bresenham's line algorithm to get all grid cells along a line.

        Args:
            x0, y0: Start grid coordinates
            x1, y1: End grid coordinates

        Returns:
            List of (grid_x, grid_y) tuples along the line
        """
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

    def _point_to_line_distance(
        self,
        point: Tuple[float, float],
        line_start: Tuple[float, float],
        line_end: Tuple[float, float],
    ) -> float:
        """
        Calculate perpendicular distance from point to line segment.

        Args:
            point: Point coordinates (x, y)
            line_start: Line start coordinates (x, y)
            line_end: Line end coordinates (x, y)

        Returns:
            Distance in millimeters
        """
        px, py = point
        x1, y1 = line_start
        x2, y2 = line_end

        # Line segment length squared
        line_len_sq = (x2 - x1) ** 2 + (y2 - y1) ** 2

        if line_len_sq == 0:
            # Line start and end are the same point
            return math.sqrt((px - x1) ** 2 + (py - y1) ** 2)

        # Parameter t = projection of point onto line (0 = start, 1 = end)
        t = max(
            0, min(1, ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / line_len_sq)
        )

        # Closest point on line segment
        closest_x = x1 + t * (x2 - x1)
        closest_y = y1 + t * (y2 - y1)

        # Distance from point to closest point
        return math.sqrt((px - closest_x) ** 2 + (py - closest_y) ** 2)

    def estimate_path_length(
        self, start_mm: Tuple[float, float], goal_mm: Tuple[float, float]
    ) -> float:
        """
        Estimate path length using Manhattan distance (quick heuristic).

        Args:
            start_mm: Start position (x, y) in millimeters
            goal_mm: Goal position (x, y) in millimeters

        Returns:
            Estimated path length in millimeters
        """
        dx = abs(goal_mm[0] - start_mm[0])
        dy = abs(goal_mm[1] - start_mm[1])
        return dx + dy

    def get_path_with_layers(
        self, path_cells: List[GridCell]
    ) -> List[Tuple[Tuple[float, float], str]]:
        """
        Convert path cells to (position, layer) tuples for detailed routing info.

        Args:
            path_cells: List of GridCell objects from pathfinding

        Returns:
            List of ((x, y), layer) tuples showing position and layer for each waypoint
        """
        path_with_layers = []
        for cell in path_cells:
            x_mm, y_mm = self.grid.to_mm_coords(cell.x, cell.y)
            path_with_layers.append(((x_mm, y_mm), cell.layer))
        return path_with_layers

    def get_path_statistics(self, path: List[Tuple[float, float]]) -> dict:
        """
        Calculate statistics for a path.

        Args:
            path: List of waypoints (x, y) in millimeters

        Returns:
            Dictionary with path statistics
        """
        if not path or len(path) < 2:
            return {
                "length_mm": 0.0,
                "segments": 0,
                "waypoints": len(path) if path else 0,
                "bends": 0,
            }

        # Calculate total length
        length = 0.0
        for i in range(len(path) - 1):
            x1, y1 = path[i]
            x2, y2 = path[i + 1]
            length += math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

        # Count direction changes (bends)
        bends = 0
        if len(path) >= 3:
            for i in range(len(path) - 2):
                # Get direction vectors
                dx1 = path[i + 1][0] - path[i][0]
                dy1 = path[i + 1][1] - path[i][1]
                dx2 = path[i + 2][0] - path[i + 1][0]
                dy2 = path[i + 2][1] - path[i + 1][1]

                # Normalize
                len1 = math.sqrt(dx1**2 + dy1**2)
                len2 = math.sqrt(dx2**2 + dy2**2)

                if len1 > 0 and len2 > 0:
                    dx1, dy1 = dx1 / len1, dy1 / len1
                    dx2, dy2 = dx2 / len2, dy2 / len2

                    # Check if direction changed (dot product != 1)
                    dot = dx1 * dx2 + dy1 * dy2
                    if abs(dot - 1.0) > 0.01:  # Tolerance for floating point
                        bends += 1

        return {
            "length_mm": round(length, 2),
            "segments": len(path) - 1,
            "waypoints": len(path),
            "bends": bends,
        }
