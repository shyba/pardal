"""
Iterative Router Integration

Hybrid Z3 + A* router with lazy constraint iteration.
Combines global Z3 allocation with A* pathfinding and crossing detection.

Inspired by FreeRouting's approach:
- Multi-pass routing with random order shuffling
- Keep best result across passes
- Scoring system to evaluate routing quality
"""

import random
from typing import Dict, List, Optional, Tuple
from z3 import sat, unsat
from pcb_tool.routing.z3_router import Z3Router, Z3RoutingConfig
from pcb_tool.routing.path_connector import PathConnector
from pcb_tool.routing.crossing_detector import CrossingDetector
from pcb_tool.routing.lazy_constraints import LazyConstraintManager
from pcb_tool.routing.grid import RoutingGrid
from pcb_tool.routing.multi_net_router import NetDefinition, RoutedNet


class IterativeRouter:
    """
    Hybrid Z3 + A* router with lazy constraint iteration.

    Flow:
    1. Z3 global allocation (no path continuity, fast)
    2. A* pathfinding to connect waypoints
    3. Detect crossings
    4. If crossings: add blocking constraints, repeat from step 1
    5. Return DRC-clean paths
    """

    def __init__(
        self,
        grid: RoutingGrid,
        max_iterations: int = 10,
        z3_timeout_ms: int = 120000
    ):
        """
        Initialize iterative router.

        Args:
            grid: RoutingGrid instance for routing
            max_iterations: Maximum refinement iterations (default 10)
            z3_timeout_ms: Z3 solver timeout in milliseconds (default 120000 = 2 minutes)
        """
        self.grid = grid
        self.max_iterations = max_iterations
        self.z3_timeout = z3_timeout_ms
        self.constraint_manager = LazyConstraintManager()

    def route(
        self,
        net_definitions: List[NetDefinition],
        single_pass: bool = True
    ) -> Dict[str, List[Tuple[float, float]]]:
        """
        Route all nets with hybrid Z3 + A*.

        Args:
            net_definitions: List of NetDefinition objects
            single_pass: If True, use single-pass mode (Z3 once → sequential A*).
                        If False, use iterative refinement (legacy).

        Returns:
            Dict of net_name -> continuous path (list of mm points)
        """
        if single_pass:
            return self._route_single_pass(net_definitions)
        else:
            return self._route_iterative(net_definitions)

    def _route_single_pass(
        self,
        net_definitions: List[NetDefinition]
    ) -> Dict[str, List[Tuple[float, float]]]:
        """
        Single-pass hybrid routing: Z3 once → sequential A*.

        Since PathConnector routes nets sequentially (adding each path
        to obstacles before routing the next), we don't need Z3 iterations.

        Returns:
            Dict of net_name -> continuous path (list of mm points)
        """
        net_segments = self._group_segments(net_definitions)

        # Phase 1: Z3 allocation (once)
        print("Phase 1: Z3 global allocation...")
        z3_result = self._run_z3(net_definitions)
        if not z3_result:
            print("Z3 failed")
            return {}

        print(f"  ✓ Z3 allocated {len(z3_result)} nets")

        # Phase 2: Sequential A* (handles crossings by design)
        print("Phase 2: Sequential A* pathfinding...")
        connector = PathConnector(self.grid)
        connected = connector.connect_all_nets(z3_result, net_segments)

        # Convert to path dict
        paths = {name: cp.path for name, cp in connected.items() if cp.success}

        print(f"  ✓ A* connected {len(paths)} nets")

        # Phase 3: Verify no crossings
        print("Phase 3: Crossing verification...")
        detector = CrossingDetector(self.grid.resolution_mm)
        crossings = detector.detect_crossings(paths)

        if not crossings:
            print("  ✓ No crossings detected!")
        else:
            print(f"  ⚠ {len(crossings)} crossings detected")
            for c in crossings[:5]:
                print(f"    - {c.net1} × {c.net2} at {c.cell}")

        return paths

    def route_multi_pass(
        self,
        net_definitions: List[NetDefinition],
        num_passes: int = 8,
        seed: Optional[int] = None
    ) -> Dict[str, List[Tuple[float, float]]]:
        """
        Multi-pass routing with random order shuffling (FreeRouting-inspired).

        Runs multiple passes with different net orderings, keeping the best result.
        This often finds better solutions than a single fixed-order pass.

        Args:
            net_definitions: List of NetDefinition objects
            num_passes: Number of passes to run (default 8, like FreeRouting)
            seed: Optional random seed for reproducibility

        Returns:
            Dict of net_name -> continuous path (list of mm points)
        """
        if seed is not None:
            random.seed(seed)

        net_segments = self._group_segments(net_definitions)
        net_names = list(net_segments.keys())

        # Run Z3 once to get global allocation
        print("Phase 1: Z3 global allocation...")
        z3_result = self._run_z3(net_definitions)
        if not z3_result:
            print("Z3 failed")
            return {}
        print(f"  ✓ Z3 allocated {len(z3_result)} nets")

        best_paths = {}
        best_score = float('inf')

        for pass_no in range(1, num_passes + 1):
            # Shuffle net order for this pass
            shuffled_names = net_names.copy()
            random.shuffle(shuffled_names)

            # Reorder net_segments dict
            ordered_segments = {name: net_segments[name] for name in shuffled_names}

            # Route with this order
            connector = PathConnector(self.grid)
            connected = connector.connect_all_nets(z3_result, ordered_segments)

            # Convert to path dict
            paths = {name: cp.path for name, cp in connected.items() if cp.success}

            # Score this result
            score = self._score_routing(paths, net_definitions)

            routed_count = len(paths)
            total_count = len(net_names)

            if score < best_score:
                best_score = score
                best_paths = paths.copy()
                print(f"  Pass {pass_no}/{num_passes}: {routed_count}/{total_count} nets, score={score:.0f} ★ (new best)")
            else:
                print(f"  Pass {pass_no}/{num_passes}: {routed_count}/{total_count} nets, score={score:.0f}")

            # Early exit if perfect score
            if score == 0:
                print(f"  ✓ Perfect routing found on pass {pass_no}!")
                break

        # Verify final result
        print("\nPhase 3: Crossing verification...")
        detector = CrossingDetector(self.grid.resolution_mm)
        crossings = detector.detect_crossings(best_paths)

        if not crossings:
            print("  ✓ No crossings detected!")
        else:
            print(f"  ⚠ {len(crossings)} crossings detected")

        print(f"\n✓ Best result: {len(best_paths)}/{len(net_names)} nets routed, score={best_score:.0f}")
        return best_paths

    def _score_routing(
        self,
        paths: Dict[str, List[Tuple[float, float]]],
        net_definitions: List[NetDefinition]
    ) -> float:
        """
        Score a routing result (lower is better).

        Scoring inspired by FreeRouting:
        - Unrouted net: 4000 penalty
        - Crossing: 1000 penalty
        - Via: 50 penalty (not implemented yet)

        Args:
            paths: Dict of net_name -> path
            net_definitions: Original net definitions

        Returns:
            Score (lower is better, 0 is perfect)
        """
        score = 0.0

        # Count unrouted nets
        expected_nets = set(nd.name for nd in net_definitions)
        routed_nets = set(paths.keys())
        unrouted = expected_nets - routed_nets
        score += len(unrouted) * 4000  # FreeRouting's penalty

        # Count crossings
        detector = CrossingDetector(self.grid.resolution_mm)
        crossings = detector.detect_crossings(paths)
        score += len(crossings) * 1000  # FreeRouting's penalty

        # Could add: wire length, via count, etc.

        return score

    def _route_iterative(
        self,
        net_definitions: List[NetDefinition]
    ) -> Dict[str, List[Tuple[float, float]]]:
        """
        Iterative refinement routing (legacy mode).

        Returns:
            Dict of net_name -> continuous path (list of mm points)
        """
        # Group segments by net name
        net_segments = self._group_segments(net_definitions)

        for iteration in range(self.max_iterations):
            print(f"Iteration {iteration + 1}/{self.max_iterations}")

            # Phase 1: Z3 allocation
            z3_result = self._run_z3(net_definitions)
            if not z3_result:
                print("Z3 failed")
                return {}

            # Phase 2: A* pathfinding
            connector = PathConnector(self.grid)
            connected = connector.connect_all_nets(z3_result, net_segments)

            # Convert to path dict
            paths = {name: cp.path for name, cp in connected.items() if cp.success}

            # Phase 3: Crossing detection
            detector = CrossingDetector(self.grid.resolution_mm)
            crossings = detector.detect_crossings(paths)

            if not crossings:
                print(f"Success! No crossings after {iteration + 1} iterations")
                return paths

            # Add blocking constraints
            print(f"Found {len(crossings)} crossings, adding constraints")
            self.constraint_manager.add_crossing_blocks(crossings)

        print(f"Warning: Max iterations reached with {len(crossings)} crossings remaining")
        return paths

    def _run_z3(self, net_definitions: List[NetDefinition]) -> Optional[Dict[str, RoutedNet]]:
        """
        Run Z3 with current blocking constraints.

        Args:
            net_definitions: List of net definitions to route

        Returns:
            Dictionary of net_name -> RoutedNet, or None if failed
        """
        config = Z3RoutingConfig(
            timeout_ms=self.z3_timeout,
            clearance_cells=0,
            optimize_wire_length=True
        )
        router = Z3Router(self.grid, config)
        router.enable_path_continuity = False

        try:
            # First, we need to set up the Z3 router's internal state
            # by calling solve_routing, which creates net_name_to_idx
            # But we want to add constraints BEFORE solving
            # So we need to manually set up like solve_routing does

            if not net_definitions:
                return {}

            # Group segments by net name (copied from Z3Router.solve_routing)
            unique_nets = list(set(n.name for n in net_definitions))
            net_name_to_idx = {name: idx for idx, name in enumerate(unique_nets)}

            # Create variables (also need to do this before applying constraints)
            router.net_name_to_idx = net_name_to_idx
            router._create_variables(unique_nets)

            # NOW apply blocking constraints
            self.constraint_manager.apply_to_solver(
                router.solver,
                router.cell_vars,
                net_name_to_idx
            )

            # Continue with rest of solve_routing setup
            router.segments_by_net = {}
            for net_def in net_definitions:
                if net_def.name not in router.segments_by_net:
                    router.segments_by_net[net_def.name] = []
                router.segments_by_net[net_def.name].append(net_def)

            # Add constraints
            router._add_obstacle_constraints()
            router._add_connectivity_constraints(net_definitions)
            router._add_exclusivity_constraints(net_definitions)
            router._add_clearance_constraints(net_definitions)

            # Add optimization objectives
            if config.optimize_wire_length:
                router._add_wire_length_objective(net_definitions)
            if config.optimize_vias:
                router._add_via_minimization_objective(net_definitions)

            # Solve
            print("  Solving constraints...")
            check_result = router.solver.check()

            if check_result == sat:
                print("  ✓ SAT: Solution found!")
                model = router.solver.model()
                return router._extract_routes(model, net_definitions)
            else:
                print(f"  ✗ Failed: {check_result}")
                return None

        except Exception as e:
            print(f"Z3 error: {e}")
            return None

    def _group_segments(self, net_definitions: List[NetDefinition]) -> Dict[str, List[NetDefinition]]:
        """
        Group net definitions by net name.

        Args:
            net_definitions: List of NetDefinition objects

        Returns:
            Dictionary mapping net name -> list of NetDefinition segments
        """
        groups = {}
        for nd in net_definitions:
            if nd.name not in groups:
                groups[nd.name] = []
            groups[nd.name].append(nd)
        return groups
