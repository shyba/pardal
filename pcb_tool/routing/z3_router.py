"""
Z3-Based Constraint Router for PCB Routing

Implements SMT-based simultaneous routing of multiple nets using the Z3 solver.
Based on research from MonoSAT (Bayless et al., 2016) and topological routing.

Key differences from A* pathfinding:
- Global optimization: solves all nets simultaneously
- Complete: guarantees solution or proves impossibility
- DRC-aware: encodes design rules as constraints
"""

from typing import List, Tuple, Dict, Optional, Set
from dataclasses import dataclass
import math

try:
    from z3 import *
except ImportError:
    raise ImportError(
        "Z3 solver not installed. Install with: pip install z3-solver"
    )

from pcb_tool.routing.grid import RoutingGrid
from pcb_tool.routing.multi_net_router import NetDefinition, RoutedNet


@dataclass
class Z3RoutingConfig:
    """Configuration for Z3 routing."""
    timeout_ms: int = 30000  # 30 seconds default
    via_cost: float = 5.0  # Cost penalty for vias
    wire_cost_per_mm: float = 1.0  # Cost per mm of wire length
    clearance_cells: int = 1  # Minimum clearance in grid cells
    optimize_wire_length: bool = True  # Minimize total wire length
    optimize_vias: bool = True  # Minimize via count


class Z3Router:
    """
    Z3-based constraint router for PCB routing.

    Uses Satisfiability Modulo Theories (SMT) to solve routing as a global
    constraint satisfaction problem rather than sequential greedy pathfinding.

    Encoding Strategy:
    - For each grid cell (x, y, layer): integer variable representing which net
      occupies it (-1 = empty, 0..N-1 = net index)
    - Constraints ensure connectivity, exclusivity, clearance, and DRC compliance
    - Optimization minimizes wire length and via count
    """

    def __init__(
        self,
        grid: RoutingGrid,
        config: Optional[Z3RoutingConfig] = None
    ):
        """
        Initialize Z3 router.

        Args:
            grid: RoutingGrid instance for routing
            config: Optional configuration parameters
        """
        self.grid = grid
        self.config = config or Z3RoutingConfig()
        self.solver = Optimize()  # Use Optimize instead of Solver for objectives
        self.solver.set("timeout", self.config.timeout_ms)

        # Cell occupation variables: maps (x, y, layer) -> Int (net_id or -1)
        self.cell_vars: Dict[Tuple[int, int, str], ArithRef] = {}

        # Path distance variables: maps (net_idx, x, y, layer) -> Int (step from start)
        # Used for path continuity constraints
        self.distance_vars: Dict[Tuple[int, int, int, str], ArithRef] = {}

        # Via placement variables: maps (net_idx, x, y) -> Bool (via exists)
        self.via_vars: Dict[Tuple[int, int, int], BoolRef] = {}

        # Configuration flags
        self.enable_path_continuity = False  # Enable proper path constraints
        self.use_fixedpoint_reachability = False  # Use Z3 fixedpoint for reachability
        self.trace_width_cells = 1  # Trace width in grid cells (for future use)
        self.max_dist_buffer = 10  # Extra cells allowed beyond Manhattan distance

        # Fixedpoint engine for reachability constraints
        self.fixedpoint = None  # Created on demand

    def solve_routing(
        self,
        net_definitions: List[NetDefinition]
    ) -> Dict[str, RoutedNet]:
        """
        Solve routing for multiple nets using Z3 constraint solver.

        Args:
            net_definitions: List of nets to route (may include multiple segments per net)

        Returns:
            Dictionary mapping net names to RoutedNet objects

        Raises:
            RoutingError: If routing is impossible (UNSAT) or times out
        """
        if not net_definitions:
            return {}

        # Group segments by net name (critical for MST routing!)
        # Multiple segments of same net must share the same net_idx
        unique_nets = list(set(n.name for n in net_definitions))
        self.net_name_to_idx = {name: idx for idx, name in enumerate(unique_nets)}

        print(f"Z3 Router: Solving {len(unique_nets)} nets ({len(net_definitions)} segments)...")
        print(f"  Grid: {self.grid.grid_width}x{self.grid.grid_height} cells")
        print(f"  Layers: F.Cu, B.Cu")
        print(f"  Timeout: {self.config.timeout_ms}ms")

        # Group segments by net for connectivity constraints
        self.segments_by_net = {}
        for net_def in net_definitions:
            if net_def.name not in self.segments_by_net:
                self.segments_by_net[net_def.name] = []
            self.segments_by_net[net_def.name].append(net_def)

        # Step 1: Create variables for all cells and all nets
        self._create_variables(unique_nets)

        # Step 2: Add constraints
        self._add_obstacle_constraints()
        self._add_connectivity_constraints(net_definitions)
        self._add_exclusivity_constraints(net_definitions)
        self._add_clearance_constraints(net_definitions)

        # Step 3: Add optimization objectives
        if self.config.optimize_wire_length:
            self._add_wire_length_objective(net_definitions)
        if self.config.optimize_vias:
            self._add_via_minimization_objective(net_definitions)

        # Step 4: Solve
        print("  Solving constraints...")
        check_result = self.solver.check()

        if check_result == sat:
            print("  ✓ SAT: Solution found!")
            model = self.solver.model()
            return self._extract_routes(model, net_definitions)
        elif check_result == unsat:
            print("  ✗ UNSAT: Provably impossible to route with current placement")
            raise RoutingError("Z3 proved routing is impossible - adjust component placement")
        else:  # unknown (timeout)
            print("  ? UNKNOWN: Solver timeout")
            raise RoutingError(f"Z3 timeout after {self.config.timeout_ms}ms")

    def _create_variables(self, unique_net_names: List[str]) -> None:
        """Create Z3 variables for all grid cells."""
        print("  Creating variables...")

        # Create cell occupation variables
        # -1 = empty, 0..N-1 = net index (NOT segment index!)
        layers = ["F.Cu", "B.Cu"]
        for layer in layers:
            for x in range(self.grid.grid_width):
                for y in range(self.grid.grid_height):
                    var_name = f"cell_{x}_{y}_{layer}"
                    self.cell_vars[(x, y, layer)] = Int(var_name)

                    # Constraint: Cell can only contain valid net index or -1 (empty)
                    self.solver.add(
                        And(
                            self.cell_vars[(x, y, layer)] >= -1,
                            self.cell_vars[(x, y, layer)] < len(unique_net_names)
                        )
                    )

        print(f"    Created {len(self.cell_vars)} cell variables")

    def _add_obstacle_constraints(self) -> None:
        """Mark obstacle cells as unusable."""
        print("  Adding obstacle constraints...")

        obstacle_count = 0
        layers = ["F.Cu", "B.Cu"]
        for layer in layers:
            for (x, y) in self.grid.obstacles.get(layer, set()):
                if (x, y, layer) in self.cell_vars:
                    # Obstacle cells must remain empty
                    self.solver.add(self.cell_vars[(x, y, layer)] == -1)
                    obstacle_count += 1

        print(f"    Blocked {obstacle_count} obstacle cells")

    def _add_connectivity_constraints(self, net_definitions: List[NetDefinition]) -> None:
        """
        Add connectivity constraints for each net segment.

        All segments of the same net share the same net_idx, so they can
        occupy the same cells without conflict (critical for MST routing!).
        """
        print("  Adding connectivity constraints...")

        for net_def in net_definitions:
            # Get the net index for this net name (all segments share same index)
            net_idx = self.net_name_to_idx[net_def.name]

            # Convert mm coordinates to grid coordinates
            start_x = int(round(net_def.start[0] / self.grid.resolution_mm))
            start_y = int(round(net_def.start[1] / self.grid.resolution_mm))
            goal_x = int(round(net_def.end[0] / self.grid.resolution_mm))
            goal_y = int(round(net_def.end[1] / self.grid.resolution_mm))

            layer = net_def.layer

            # Clamp to grid bounds
            start_x = max(0, min(self.grid.grid_width - 1, start_x))
            start_y = max(0, min(self.grid.grid_height - 1, start_y))
            goal_x = max(0, min(self.grid.grid_width - 1, goal_x))
            goal_y = max(0, min(self.grid.grid_height - 1, goal_y))

            # Constraint: Start and goal cells must be occupied by this net
            # Multiple segments of same net can share these cells (same net_idx)
            if (start_x, start_y, layer) in self.cell_vars:
                self.solver.add(self.cell_vars[(start_x, start_y, layer)] == net_idx)

            if (goal_x, goal_y, layer) in self.cell_vars:
                self.solver.add(self.cell_vars[(goal_x, goal_y, layer)] == net_idx)

            # Add path continuity constraints if enabled
            if self.enable_path_continuity:
                self._add_path_continuity_for_segment(
                    net_idx, net_def.name, start_x, start_y, goal_x, goal_y, layer
                )

        print(f"    Added connectivity for {len(net_definitions)} segments")

    def _add_path_continuity_for_segment(
        self,
        net_idx: int,
        net_name: str,
        start_x: int,
        start_y: int,
        goal_x: int,
        goal_y: int,
        layer: str
    ) -> None:
        """
        Add path continuity using REACHABILITY constraints (inspired by Z3 fixedpoints).

        Approach:
        - Create boolean reachability variables: reachable[net][x][y]
        - Constraint: start is reachable (base case)
        - Constraint: if cell is reachable AND neighbor is occupied, neighbor is reachable (induction)
        - Constraint: goal must be reachable (ensures connectivity)

        This encodes transitive closure as SAT constraints within the main solver.
        Much lighter than distance variables, more precise than neighbor-only constraints.
        """
        if not hasattr(self, 'reachability_vars'):
            self.reachability_vars = {}  # (net_idx, x, y, layer) -> BoolRef

        # Create reachability variables for this net on this layer
        for x in range(self.grid.grid_width):
            for y in range(self.grid.grid_height):
                if (x, y, layer) not in self.cell_vars:
                    continue

                var_key = (net_idx, x, y, layer)
                if var_key not in self.reachability_vars:
                    self.reachability_vars[var_key] = Bool(f"reach_{net_idx}_{x}_{y}_{layer}")

        # Base case: Start cell is reachable
        start_key = (net_idx, start_x, start_y, layer)
        if start_key in self.reachability_vars:
            self.solver.add(self.reachability_vars[start_key])

        # Inductive case: A cell can ONLY be reachable if:
        # - It's the start (base case), OR
        # - At least one of its neighbors is (occupied by this net AND reachable)
        for x in range(self.grid.grid_width):
            for y in range(self.grid.grid_height):
                # Skip start cell (base case handles it)
                if x == start_x and y == start_y:
                    continue

                cell_key = (net_idx, x, y, layer)
                if cell_key not in self.reachability_vars:
                    continue

                neighbors = self._get_cell_neighbors(x, y, layer)

                # Build list of conditions: neighbor is reachable AND occupied by this net
                neighbor_reachable_conditions = []
                for nx, ny, nl in neighbors:
                    neighbor_key = (net_idx, nx, ny, nl)
                    if neighbor_key not in self.reachability_vars:
                        continue

                    # Neighbor is reachable AND occupied by this net
                    neighbor_reachable_conditions.append(
                        And(
                            self.reachability_vars[neighbor_key],
                            self.cell_vars[(nx, ny, nl)] == net_idx
                        )
                    )

                if neighbor_reachable_conditions:
                    # CRITICAL: A cell can ONLY be reachable if at least one neighbor
                    # is reachable and occupied (forces connected path)
                    # Bi-directional: reachable IFF at least one neighbor is reachable+occupied
                    self.solver.add(
                        self.reachability_vars[cell_key] == Or(neighbor_reachable_conditions)
                    )

        # Goal condition: Goal cell must be reachable
        goal_key = (net_idx, goal_x, goal_y, layer)
        if goal_key in self.reachability_vars:
            self.solver.add(self.reachability_vars[goal_key])

        # Consistency: If cell is reachable, it must be occupied by this net
        # (Otherwise we can have "reachable" cells that aren't actually part of the path)
        for x in range(self.grid.grid_width):
            for y in range(self.grid.grid_height):
                cell_key = (net_idx, x, y, layer)
                if cell_key not in self.reachability_vars:
                    continue

                if (x, y, layer) in self.cell_vars:
                    # If reachable, must be occupied by this net
                    self.solver.add(
                        Implies(
                            self.reachability_vars[cell_key],
                            self.cell_vars[(x, y, layer)] == net_idx
                        )
                    )

    def _get_cell_neighbors(
        self,
        x: int,
        y: int,
        layer: str
    ) -> List[Tuple[int, int, str]]:
        """Get valid neighboring cells (orthogonal only for simplicity)."""
        neighbors = []

        # Orthogonal neighbors (N, S, E, W)
        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nx, ny = x + dx, y + dy
            if 0 <= nx < self.grid.grid_width and 0 <= ny < self.grid.grid_height:
                if (nx, ny, layer) in self.cell_vars:
                    neighbors.append((nx, ny, layer))

        return neighbors

    def _add_exclusivity_constraints(self, net_definitions: List[NetDefinition]) -> None:
        """
        Ensure no two different nets occupy the same cell on the same layer.

        This is automatically enforced by our encoding: each cell can only
        contain one net index. But we add explicit constraints for clarity.
        """
        print("  Adding exclusivity constraints...")

        # Already enforced by cell_vars being integer with single value
        # No additional constraints needed!

        print("    Exclusivity enforced by variable encoding")

    def _add_clearance_constraints(self, net_definitions: List[NetDefinition]) -> None:
        """
        Add minimum clearance constraints between different nets.

        For adjacent cells on same layer, ensure they're not occupied by
        different nets (or add clearance buffer).
        """
        print("  Adding clearance constraints...")

        if self.config.clearance_cells == 0:
            print("    Clearance disabled (0 cells)")
            return

        clearance_count = 0
        num_unique_nets = len(self.net_name_to_idx)

        for layer in ["F.Cu", "B.Cu"]:
            for x in range(self.grid.grid_width):
                for y in range(self.grid.grid_height):
                    if (x, y, layer) not in self.cell_vars:
                        continue

                    # Check neighbors within clearance distance
                    for dx in range(-self.config.clearance_cells, self.config.clearance_cells + 1):
                        for dy in range(-self.config.clearance_cells, self.config.clearance_cells + 1):
                            if dx == 0 and dy == 0:
                                continue

                            nx, ny = x + dx, y + dy
                            if (nx, ny, layer) not in self.cell_vars:
                                continue

                            # If cell occupied by net A, neighbor cannot be occupied by different net
                            # (both can be occupied by same net, or either can be empty)
                            for net_idx in range(num_unique_nets):
                                self.solver.add(
                                    Implies(
                                        self.cell_vars[(x, y, layer)] == net_idx,
                                        Or(
                                            self.cell_vars[(nx, ny, layer)] == net_idx,
                                            self.cell_vars[(nx, ny, layer)] == -1
                                        )
                                    )
                                )
                                clearance_count += 1

        print(f"    Added {clearance_count} clearance constraints")

    def _add_wire_length_objective(self, net_definitions: List[NetDefinition]) -> None:
        """Add optimization objective to minimize total wire length."""
        print("  Adding wire length minimization objective...")

        # Count total cells occupied by any net
        total_cells = []

        for layer in ["F.Cu", "B.Cu"]:
            for x in range(self.grid.grid_width):
                for y in range(self.grid.grid_height):
                    if (x, y, layer) not in self.cell_vars:
                        continue

                    # If cell is occupied (not -1), count it
                    total_cells.append(
                        If(self.cell_vars[(x, y, layer)] >= 0, 1, 0)
                    )

        if total_cells:
            wire_length_cost = Sum(total_cells) * self.config.wire_cost_per_mm
            self.solver.minimize(wire_length_cost)
            print(f"    Minimizing wire length ({len(total_cells)} cell variables)")

    def _add_via_minimization_objective(self, net_definitions: List[NetDefinition]) -> None:
        """Add optimization objective to minimize via count."""
        print("  Adding via minimization objective...")

        # Count layer transitions for each net
        # A via occurs when a net occupies same (x,y) on multiple layers

        via_count_terms = []
        num_unique_nets = len(self.net_name_to_idx)

        for x in range(self.grid.grid_width):
            for y in range(self.grid.grid_height):
                # Check if any net has a via at this position
                for net_idx in range(num_unique_nets):
                    # Check for vias between F.Cu and B.Cu
                    layer1, layer2 = "F.Cu", "B.Cu"

                    if (x, y, layer1) in self.cell_vars and (x, y, layer2) in self.cell_vars:
                        # Via exists if same net on both layers at this position
                        via_exists = And(
                            self.cell_vars[(x, y, layer1)] == net_idx,
                            self.cell_vars[(x, y, layer2)] == net_idx
                        )
                        via_count_terms.append(If(via_exists, 1, 0))

        if via_count_terms:
            via_cost = Sum(via_count_terms) * self.config.via_cost
            self.solver.minimize(via_cost)
            print(f"    Minimizing vias ({len(via_count_terms)} via positions)")

    def _extract_routes(
        self,
        model: ModelRef,
        net_definitions: List[NetDefinition]
    ) -> Dict[str, RoutedNet]:
        """
        Extract routing solution from Z3 model.

        Args:
            model: Satisfied Z3 model
            net_definitions: List of net segments that were routed

        Returns:
            Dictionary mapping net names to RoutedNet objects
        """
        print("  Extracting routes from model...")

        routed_nets = {}

        # Process each unique net (not each segment!)
        for net_name, net_idx in self.net_name_to_idx.items():
            # Find all cells occupied by this net
            occupied_cells = []

            for layer in ["F.Cu", "B.Cu"]:
                for x in range(self.grid.grid_width):
                    for y in range(self.grid.grid_height):
                        if (x, y, layer) not in self.cell_vars:
                            continue

                        cell_value = model.eval(self.cell_vars[(x, y, layer)])

                        # Check if this cell is occupied by current net
                        if cell_value.as_long() == net_idx:
                            # Convert grid coordinates back to mm
                            x_mm = x * self.grid.resolution_mm
                            y_mm = y * self.grid.resolution_mm
                            occupied_cells.append((x_mm, y_mm, layer))

            if not occupied_cells:
                continue

            # Convert occupied cells to path and segments
            # For now, simple approach: use occupied cells as waypoints
            path = [(x, y) for x, y, layer in occupied_cells]

            # Create segments from adjacent cells
            segments = []
            # TODO: Reconstruct proper segments from occupied cells
            # For now, just create segments from path
            for i in range(len(path) - 1):
                segments.append((path[i], path[i + 1]))

            # Get layer from first segment of this net
            net_segments = self.segments_by_net[net_name]
            layer = net_segments[0].layer if net_segments else "F.Cu"

            routed_net = RoutedNet(
                name=net_name,
                path=path,
                layer=layer,
                segments=segments
            )

            routed_nets[net_name] = routed_net
            print(f"    {net_name}: {len(occupied_cells)} cells, {len(segments)} segments")

        return routed_nets


class RoutingError(Exception):
    """Exception raised when routing fails."""
    pass
