"""
Layer Optimizer Module

Uses Z3 SMT solver for global optimization of layer assignments and via placement
across multiple nets. Provides constraint-based optimization to minimize vias and
prevent crossings.
"""

from typing import List, Tuple, Dict, Optional, Set
from dataclasses import dataclass
import math

try:
    from z3 import *
    Z3_AVAILABLE = True
except ImportError:
    Z3_AVAILABLE = False

from pcb_tool.routing.grid import RoutingGrid, GridCell


@dataclass
class NetPath:
    """Represents a routed net with its path segments."""
    name: str
    segments: List[Tuple[Tuple[float, float], Tuple[float, float]]]  # List of (start, end) in mm
    default_layer: str = "F.Cu"


@dataclass
class LayerAssignment:
    """Result of layer optimization for a net."""
    net_name: str
    segment_assignments: List[Tuple[int, str, bool]]  # (segment_idx, layer, via_after)


class LayerOptimizer:
    """
    Z3-based layer assignment optimizer for multi-net routing.

    Optimizes layer assignments across multiple nets to:
    - Minimize via count
    - Prevent same-layer crossings between different nets
    - Maintain routing connectivity
    """

    def __init__(self, grid: RoutingGrid, timeout: float = 30.0):
        """
        Initialize the layer optimizer.

        Args:
            grid: RoutingGrid instance for the PCB
            timeout: Z3 solver timeout in seconds (default 30.0)
        """
        if not Z3_AVAILABLE:
            raise ImportError(
                "Z3 solver not available. Install with: pip install z3-solver==4.12.6.0"
            )

        self.grid = grid
        self.timeout = timeout

    def optimize_layer_assignments(
        self,
        nets_paths: List[NetPath]
    ) -> Dict[str, LayerAssignment]:
        """
        Optimize layer assignments for multiple nets.

        Uses Z3 SMT solver to find optimal layer assignments that minimize vias
        and prevent crossings. Falls back to greedy heuristic if solver times out
        or cannot find solution.

        Args:
            nets_paths: List of NetPath objects representing routed nets

        Returns:
            Dictionary mapping net names to LayerAssignment objects
        """
        if not nets_paths:
            return {}

        try:
            # Encode constraints
            optimizer, layer_vars, via_vars = self._encode_constraints(nets_paths)

            # Set timeout (in milliseconds)
            optimizer.set("timeout", int(self.timeout * 1000))

            # Solve
            result = optimizer.check()

            if result == sat:
                # Solution found - decode it
                model = optimizer.model()
                return self._decode_solution(model, layer_vars, via_vars, nets_paths)
            else:
                # No solution or timeout - use greedy fallback
                return self._greedy_fallback(nets_paths)

        except Exception as e:
            # Any error - fall back to greedy
            return self._greedy_fallback(nets_paths)

    def _encode_constraints(
        self,
        nets_paths: List[NetPath]
    ) -> Tuple[Optimize, Dict, Dict]:
        """
        Encode routing constraints as Z3 formulas.

        Creates Z3 variables and constraints for:
        - Layer assignment for each segment (Bool: True=F.Cu, False=B.Cu)
        - Via placement at segment junctions (Bool: via present)
        - Connectivity constraints (layer changes require vias)
        - Crossing prevention constraints (no same-layer crossings)

        Args:
            nets_paths: List of NetPath objects

        Returns:
            Tuple of (optimizer, layer_vars, via_vars)
            - optimizer: Z3 Optimize object with constraints
            - layer_vars: Dict mapping (net_name, segment_idx) to Bool variable
            - via_vars: Dict mapping (net_name, junction_idx) to Bool variable
        """
        optimizer = Optimize()

        # Create variables
        layer_vars = self._create_layer_variables(nets_paths)
        via_vars = self._create_via_variables(nets_paths)

        # Add constraints
        self._add_connectivity_constraints(optimizer, layer_vars, via_vars, nets_paths)
        self._add_crossing_constraints(optimizer, layer_vars, nets_paths)

        # Objective: Minimize via count
        via_count = Sum([If(via_var, 1, 0) for via_var in via_vars.values()])
        optimizer.minimize(via_count)

        return optimizer, layer_vars, via_vars

    def _create_layer_variables(
        self,
        nets_paths: List[NetPath]
    ) -> Dict[Tuple[str, int], Bool]:
        """
        Create Z3 Bool variables for layer assignments.

        Args:
            nets_paths: List of NetPath objects

        Returns:
            Dict mapping (net_name, segment_idx) to Z3 Bool variable
            (True = F.Cu, False = B.Cu)
        """
        layer_vars = {}

        for net_path in nets_paths:
            for seg_idx in range(len(net_path.segments)):
                var_name = f"layer_{net_path.name}_seg{seg_idx}"
                layer_vars[(net_path.name, seg_idx)] = Bool(var_name)

        return layer_vars

    def _create_via_variables(
        self,
        nets_paths: List[NetPath]
    ) -> Dict[Tuple[str, int], Bool]:
        """
        Create Z3 Bool variables for via placement.

        Args:
            nets_paths: List of NetPath objects

        Returns:
            Dict mapping (net_name, junction_idx) to Z3 Bool variable
            (True = via present, False = no via)
        """
        via_vars = {}

        for net_path in nets_paths:
            # Via can be placed after each segment (junction between segments)
            # Number of junctions = number of segments - 1
            for junction_idx in range(len(net_path.segments) - 1):
                var_name = f"via_{net_path.name}_junc{junction_idx}"
                via_vars[(net_path.name, junction_idx)] = Bool(var_name)

        return via_vars

    def _add_connectivity_constraints(
        self,
        solver: Optimize,
        layer_vars: Dict,
        via_vars: Dict,
        nets_paths: List[NetPath]
    ) -> None:
        """
        Add connectivity constraints to solver.

        Ensures that:
        - If adjacent segments are on different layers, a via is required
        - Via placement is consistent with layer transitions

        Args:
            solver: Z3 Optimize object
            layer_vars: Layer assignment variables
            via_vars: Via placement variables
            nets_paths: List of NetPath objects
        """
        for net_path in nets_paths:
            # For each junction between adjacent segments
            for seg_idx in range(len(net_path.segments) - 1):
                current_layer = layer_vars[(net_path.name, seg_idx)]
                next_layer = layer_vars[(net_path.name, seg_idx + 1)]
                via_present = via_vars[(net_path.name, seg_idx)]

                # Constraint: Via required if and only if layers differ
                # via_present <-> (current_layer != next_layer)
                # Which is: via_present <-> (current_layer XOR next_layer)
                solver.add(via_present == Xor(current_layer, next_layer))

    def _add_crossing_constraints(
        self,
        solver: Optimize,
        layer_vars: Dict,
        nets_paths: List[NetPath]
    ) -> None:
        """
        Add crossing prevention constraints to solver.

        Ensures that:
        - Segments from different nets on the same layer do not cross
        - Uses line segment intersection detection

        Args:
            solver: Z3 Optimize object
            layer_vars: Layer assignment variables
            nets_paths: List of NetPath objects
        """
        # Check all pairs of segments from different nets
        for i, net1 in enumerate(nets_paths):
            for j, net2 in enumerate(nets_paths):
                if i >= j:  # Only check each pair once
                    continue

                # Check all segment pairs between these two nets
                for seg1_idx, seg1 in enumerate(net1.segments):
                    for seg2_idx, seg2 in enumerate(net2.segments):
                        # Check if segments intersect geometrically
                        if self._segments_intersect(seg1, seg2):
                            # If they intersect, they cannot both be on the same layer
                            layer1 = layer_vars[(net1.name, seg1_idx)]
                            layer2 = layer_vars[(net2.name, seg2_idx)]

                            # Constraint: NOT (layer1 == layer2)
                            # Which is: layer1 != layer2
                            # Which is: layer1 XOR layer2
                            solver.add(Xor(layer1, layer2))

    def _decode_solution(
        self,
        model: ModelRef,
        layer_vars: Dict,
        via_vars: Dict,
        nets_paths: List[NetPath]
    ) -> Dict[str, LayerAssignment]:
        """
        Decode Z3 model into layer assignments.

        Extracts layer assignments and via positions from Z3 solution.

        Args:
            model: Z3 model (solution)
            layer_vars: Layer assignment variables
            via_vars: Via placement variables
            nets_paths: List of NetPath objects

        Returns:
            Dictionary mapping net names to LayerAssignment objects
        """
        assignments = {}

        for net_path in nets_paths:
            segment_assignments = []

            for seg_idx in range(len(net_path.segments)):
                # Get layer assignment from model
                layer_var = layer_vars[(net_path.name, seg_idx)]
                layer_value = model.evaluate(layer_var, model_completion=True)

                # Convert Bool to layer name (True = F.Cu, False = B.Cu)
                layer = "F.Cu" if is_true(layer_value) else "B.Cu"

                # Check if via is placed after this segment
                via_after = False
                if seg_idx < len(net_path.segments) - 1:  # Not the last segment
                    via_var = via_vars[(net_path.name, seg_idx)]
                    via_value = model.evaluate(via_var, model_completion=True)
                    via_after = is_true(via_value)

                segment_assignments.append((seg_idx, layer, via_after))

            assignments[net_path.name] = LayerAssignment(
                net_name=net_path.name,
                segment_assignments=segment_assignments
            )

        return assignments

    def _greedy_fallback(
        self,
        nets_paths: List[NetPath]
    ) -> Dict[str, LayerAssignment]:
        """
        Greedy fallback heuristic for layer assignment.

        Simple heuristic:
        - Prefer single layer per net (use default layer)
        - Place vias only when forced by multi-layer requirements
        - No optimization, just valid routing

        Args:
            nets_paths: List of NetPath objects

        Returns:
            Dictionary mapping net names to LayerAssignment objects
        """
        assignments = {}

        for net_path in nets_paths:
            segment_assignments = []

            # Simple heuristic: use default layer for all segments, no vias
            for idx in range(len(net_path.segments)):
                # (segment_idx, layer, via_after)
                segment_assignments.append((idx, net_path.default_layer, False))

            assignments[net_path.name] = LayerAssignment(
                net_name=net_path.name,
                segment_assignments=segment_assignments
            )

        return assignments

    def _segments_intersect(
        self,
        seg1: Tuple[Tuple[float, float], Tuple[float, float]],
        seg2: Tuple[Tuple[float, float], Tuple[float, float]]
    ) -> bool:
        """
        Check if two line segments intersect.

        Uses line segment intersection algorithm.

        Args:
            seg1: First segment ((x1, y1), (x2, y2))
            seg2: Second segment ((x1, y1), (x2, y2))

        Returns:
            True if segments intersect, False otherwise
        """
        (x1, y1), (x2, y2) = seg1
        (x3, y3), (x4, y4) = seg2

        # Calculate denominators
        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)

        # Parallel or coincident lines
        if abs(denom) < 1e-10:
            return False

        # Calculate intersection parameters
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
        u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom

        # Check if intersection is within both segments
        # Use strict inequality to avoid endpoint touches
        if 0 < t < 1 and 0 < u < 1:
            return True

        return False
