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

from pcb_tool.routing.grid import RoutingGrid, GridCell


@dataclass
class PathNode:
    """
    Node in the A* search tree.

    Represents a position in the search space with associated costs.
    """
    cell: GridCell
    g_cost: float  # Cost from start to this node
    h_cost: float  # Heuristic cost from this node to goal
    parent: Optional['PathNode'] = None

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
        return (self.cell.x, self.cell.y, self.cell.layer) == \
               (other.cell.x, other.cell.y, other.cell.layer)


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
        allowed_via_types: Optional[List[str]] = None
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

        # Via cost multipliers for different via types
        # Blind/buried vias are slightly preferred (less routing congestion)
        self.via_type_costs = {
            "through": 1.0,
            "blind": 0.9,
            "buried": 0.85
        }

    def find_path(
        self,
        start_mm: Tuple[float, float],
        goal_mm: Tuple[float, float],
        layer: str,
        target_layer: Optional[str] = None,
        allow_diagonals: bool = True,
        force_single_layer: bool = False,
        via_cost: Optional[float] = None,
        net_name: Optional[str] = None
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
        # Store net_name for use in neighbor generation
        self.current_net = net_name

        # Default to single-layer routing
        if target_layer is None:
            target_layer = layer

        # Force both layers to be the same if single-layer mode
        if force_single_layer:
            target_layer = layer

        # Convert to grid coordinates
        start_grid = self.grid.to_grid_coords(*start_mm)
        goal_grid = self.grid.to_grid_coords(*goal_mm)

        # Check if start and goal are valid
        if not self.grid.is_valid_cell(*start_grid, layer, current_net=net_name):
            return None
        if not self.grid.is_valid_cell(*goal_grid, target_layer, current_net=net_name):
            return None

        # Create start and goal cells
        start_cell = GridCell(start_grid[0], start_grid[1], layer)
        goal_cell = GridCell(goal_grid[0], goal_grid[1], target_layer)

        # Use provided via_cost or default to instance via_cost
        effective_via_cost = via_cost if via_cost is not None else self.via_cost

        # A* search with multi-layer support
        path_cells = self._astar_search(start_cell, goal_cell, target_layer, allow_diagonals, force_single_layer, effective_via_cost)

        if path_cells is None:
            return None

        # Mark vias at layer transitions
        self._mark_vias_in_path(path_cells)

        # Convert grid path to millimeter coordinates
        path_mm = [self.grid.to_mm_coords(cell.x, cell.y) for cell in path_cells]

        # Simplify path by removing redundant waypoints
        simplified_path = self._simplify_path(path_mm)

        return simplified_path

    def _astar_search(
        self,
        start: GridCell,
        goal: GridCell,
        target_layer: str,
        allow_diagonals: bool,
        force_single_layer: bool = False,
        via_cost: float = None
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
            cell=start,
            g_cost=0.0,
            h_cost=self._heuristic(start, goal),
            parent=None
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
            if (current_node.cell.x == goal.x and
                current_node.cell.y == goal.y and
                current_node.cell.layer == goal.layer):
                return self._reconstruct_path(current_node)

            # Mark as visited
            cell_key = (current_node.cell.x, current_node.cell.y, current_node.cell.layer)

            # Skip if we've already found a better path to this cell
            if cell_key in visited and visited[cell_key] <= current_node.g_cost:
                continue

            visited[cell_key] = current_node.g_cost

            # Explore neighbors (same-layer moves)
            current_net = getattr(self, 'current_net', None)
            neighbors = self.grid.get_neighbors(
                current_node.cell.x,
                current_node.cell.y,
                current_node.cell.layer,
                allow_diagonals,
                current_net=current_net
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
                    via_cost
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
                        parent=current_node
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
        via_cost: Optional[float] = None
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
        current_net = getattr(self, 'current_net', None)

        # Use provided via_cost or default to instance via_cost
        effective_via_cost = via_cost if via_cost is not None else self.via_cost

        # Get possible layer transitions based on allowed via types
        transitions = self._get_possible_layer_transitions(current_layer)

        for to_layer, via_type in transitions:
            # Check if target layer is valid for routing at this position
            if not self.grid.is_valid_cell(grid_x, grid_y, to_layer, current_net=current_net):
                continue

            # Calculate cost with via type multiplier
            type_cost = self.via_type_costs.get(via_type, 1.0)
            transition_cost = effective_via_cost * type_cost

            # Create neighbor cell on target layer at same position
            neighbor_cell = GridCell(grid_x, grid_y, to_layer)
            neighbors.append((neighbor_cell, transition_cost))

        return neighbors

    def _get_possible_layer_transitions(
        self,
        current_layer: str
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

        Args:
            path_cells: List of GridCell objects forming the path
        """
        for i in range(len(path_cells) - 1):
            current_cell = path_cells[i]
            next_cell = path_cells[i + 1]

            # Check if layer changes between consecutive cells
            if current_cell.layer != next_cell.layer:
                # Layer transition detected - mark via
                x_mm, y_mm = self.grid.to_mm_coords(current_cell.x, current_cell.y)

                # Determine via layers (all layers between the two transition layers)
                via_layers = tuple(self.grid.get_layers_between(
                    current_cell.layer, next_cell.layer
                ))

                self.grid.mark_via(x_mm, y_mm, size_mm=0.8, via_layers=via_layers)

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
        self,
        path: List[Tuple[float, float]],
        epsilon: float = 0.01
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
        epsilon: float
    ) -> bool:
        """
        Check if all points between start and end are approximately collinear.

        Args:
            path: List of waypoints
            start_idx: Start index
            end_idx: End index
            epsilon: Tolerance for collinearity

        Returns:
            True if all intermediate points are within epsilon of the line
        """
        if end_idx - start_idx <= 1:
            return True

        start = path[start_idx]
        end = path[end_idx]

        # Check each intermediate point
        for i in range(start_idx + 1, end_idx):
            point = path[i]
            dist = self._point_to_line_distance(point, start, end)
            if dist > epsilon:
                return False

        return True

    def _point_to_line_distance(
        self,
        point: Tuple[float, float],
        line_start: Tuple[float, float],
        line_end: Tuple[float, float]
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
        t = max(0, min(1, ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / line_len_sq))

        # Closest point on line segment
        closest_x = x1 + t * (x2 - x1)
        closest_y = y1 + t * (y2 - y1)

        # Distance from point to closest point
        return math.sqrt((px - closest_x) ** 2 + (py - closest_y) ** 2)

    def estimate_path_length(
        self,
        start_mm: Tuple[float, float],
        goal_mm: Tuple[float, float]
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
        self,
        path_cells: List[GridCell]
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
                "bends": 0
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
                len1 = math.sqrt(dx1 ** 2 + dy1 ** 2)
                len2 = math.sqrt(dx2 ** 2 + dy2 ** 2)

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
            "bends": bends
        }
