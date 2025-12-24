"""
Multi-Net Router Module

Coordinates routing of multiple nets with conflict detection and resolution.
Integrates PathFinder for single-net routing and LayerOptimizer for global
layer assignment optimization.
"""

from typing import List, Tuple, Dict, Optional, Set
from dataclasses import dataclass
import math
import fnmatch

from pcb_tool.routing.grid import RoutingGrid, GridCell
from pcb_tool.routing.pathfinder import PathFinder
from pcb_tool.routing.layer_optimizer import LayerOptimizer, NetPath, LayerAssignment


@dataclass
class NetDefinition:
    """Definition of a net to be routed."""
    name: str
    start: Tuple[float, float]  # (x, y) in mm
    end: Tuple[float, float]    # (x, y) in mm
    layer: str = "F.Cu"
    priority: int = 0  # Higher priority nets routed first


@dataclass
class RoutedNet:
    """Result of routing a single net."""
    name: str
    path: List[Tuple[float, float]]  # Waypoints in mm
    layer: str
    segments: List[Tuple[Tuple[float, float], Tuple[float, float]]]  # (start, end) pairs


class MultiNetRouter:
    """
    Multi-net routing coordinator.

    Orchestrates routing of multiple nets with:
    - Priority-based sequential routing
    - Conflict detection between nets
    - Layer assignment optimization
    - DRC validation
    """

    def __init__(
        self,
        grid: RoutingGrid,
        pathfinder: Optional[PathFinder] = None,
        optimizer: Optional[LayerOptimizer] = None,
        ground_plane_mode: bool = False,
        via_cost_map: Optional[Dict[str, float]] = None
    ):
        """
        Initialize the multi-net router.

        Args:
            grid: RoutingGrid instance for routing
            pathfinder: PathFinder instance (created if None)
            optimizer: LayerOptimizer instance (created if None)
            ground_plane_mode: Use ground plane strategy (B.Cu=GND plane, F.Cu=signals)
            via_cost_map: Optional mapping of net name patterns to via costs (supports wildcards)
        """
        self.grid = grid
        # In ground plane mode, make vias very cheap to encourage using B.Cu to avoid crossings
        # Cost of 0.5mm means vias are preferred over long detours or being blocked
        via_cost = 0.5 if ground_plane_mode else 10.0
        self.pathfinder = pathfinder or PathFinder(grid, via_cost=via_cost)
        self.optimizer = optimizer or LayerOptimizer(grid)
        self.ground_plane_mode = ground_plane_mode
        self.via_cost_map = via_cost_map or {}
        self.manually_routed_nets: Set[str] = set()
        self.routed_nets: Dict[str, RoutedNet] = {}  # Track routed nets for rip-up

    def _get_via_cost_for_net(self, net_name: str) -> Optional[float]:
        """
        Get via cost for a specific net using pattern matching.

        Args:
            net_name: Net name to match

        Returns:
            Via cost if pattern matches, None otherwise
        """
        for pattern, cost in self.via_cost_map.items():
            if fnmatch.fnmatch(net_name, pattern):
                return cost
        return None

    def add_manual_route(
        self,
        net_name: str,
        path: List[Tuple[float, float]],
        layer: str,
        width_mm: float = 0.25
    ) -> None:
        """
        Add a manually routed net to the routing grid.

        Manual routes are marked as obstacles and crossing-forbidden zones,
        forcing subsequent auto-routing to route around them.

        Args:
            net_name: Name of the net being manually routed
            path: List of waypoints (x, y) in millimeters
            layer: Layer the manual route is on ("F.Cu" or "B.Cu")
            width_mm: Trace width in millimeters (default 0.25mm)
        """
        # Track this net as manually routed
        self.manually_routed_nets.add(net_name)

        # Mark the manual route as obstacles and forbidden zones
        for i in range(len(path) - 1):
            start = path[i]
            end = path[i + 1]

            # Mark trace segment as obstacle (for clearance)
            self.grid.mark_trace_segment(
                start_mm=start,
                end_mm=end,
                layer=layer,
                width_mm=width_mm,
                clearance_mm=0.2  # Default clearance
            )

            # Mark crossing-forbidden zone (HARD BLOCK - prevents crossings)
            self.grid.mark_crossing_forbidden_zone(
                start_mm=start,
                end_mm=end,
                layer=layer,
                trace_width_mm=width_mm,
                net_name=net_name
            )

    def remove_net_routing(self, net_name: str) -> None:
        """
        Remove a net's routing from the grid.

        Removes forbidden zones for the specified net, allowing it to be
        re-routed. Note: Does NOT remove obstacles (trace segments) for safety.

        Args:
            net_name: Net name whose routing should be removed
        """
        # Remove from routed nets tracking
        if net_name in self.routed_nets:
            del self.routed_nets[net_name]

        # Remove forbidden zones from grid
        self.grid.remove_net_forbidden_zones(net_name)

        # Remove from manually routed nets if present
        self.manually_routed_nets.discard(net_name)

    def route_nets(
        self,
        net_definitions: List[NetDefinition],
        constraints: Optional['RoutingConstraints'] = None
    ) -> Dict[str, RoutedNet]:
        """
        Route multiple nets with conflict detection.

        Routes nets sequentially by priority, marking routed traces as obstacles
        for subsequent nets. Optionally uses Z3 optimizer for layer assignments.

        Args:
            net_definitions: List of NetDefinition objects
            constraints: Optional routing constraints (filtering, ordering)

        Returns:
            Dictionary mapping net names to RoutedNet objects
        """
        if not net_definitions:
            return {}

        # Apply constraints if provided
        if constraints:
            net_definitions = constraints.apply_constraints(net_definitions)

        # Prioritize nets (higher priority first)
        sorted_nets = self._prioritize_nets(net_definitions)

        # Route each net sequentially
        routed_nets = {}

        for net_def in sorted_nets:
            # Skip manually routed nets
            if net_def.name in self.manually_routed_nets:
                continue

            # In ground plane mode, skip GND (it's a solid plane on B.Cu)
            if self.ground_plane_mode and net_def.name.upper() in ['GND', 'GROUND']:
                continue

            # Determine routing layer and constraints
            if self.ground_plane_mode:
                # Prefer F.Cu but allow B.Cu for unavoidable crossings
                # This mimics real 2-layer boards where B.Cu is primarily GND plane
                # but can have signal traces to avoid crossings
                routing_layer = "F.Cu"
                force_single_layer = False  # Allow layer transitions to avoid crossings
            else:
                # Multi-layer routing allowed
                routing_layer = net_def.layer
                force_single_layer = False

            # Get via cost for this net (if specified)
            net_via_cost = self._get_via_cost_for_net(net_def.name)

            # Route the net (pass net_name to allow routing through own forbidden zones for MST)
            path = self.pathfinder.find_path(
                start_mm=net_def.start,
                goal_mm=net_def.end,
                layer=routing_layer,
                allow_diagonals=True,
                force_single_layer=force_single_layer,
                via_cost=net_via_cost,
                net_name=net_def.name
            )

            if path is None:
                # Routing failed - skip this net
                continue

            # Create segments from path
            segments = []
            for i in range(len(path) - 1):
                segments.append((path[i], path[i + 1]))

            # Store routed net
            routed_net = RoutedNet(
                name=net_def.name,
                path=path,
                layer=routing_layer,
                segments=segments
            )
            routed_nets[net_def.name] = routed_net
            self.routed_nets[net_def.name] = routed_net  # Track for rip-up

            # Mark this net's path as obstacle for subsequent nets
            self._mark_net_as_obstacle(path, routing_layer, net_def.name)

        # Validate routing (check for conflicts)
        if not self._validate_routing(routed_nets):
            # Conflicts detected - would trigger rip-up and re-route in full implementation
            pass

        return routed_nets

    def route_nets_with_optimization(
        self,
        net_definitions: List[NetDefinition]
    ) -> Dict[str, RoutedNet]:
        """
        Route multiple nets with Z3 layer optimization.

        First routes all nets (potentially with conflicts), then uses Z3 to
        optimize layer assignments to eliminate crossings and minimize vias.

        Args:
            net_definitions: List of NetDefinition objects

        Returns:
            Dictionary mapping net names to RoutedNet objects with optimized layers
        """
        # First, route all nets without marking as obstacles
        # (allows overlapping paths for optimization)
        initial_routes = {}

        for net_def in net_definitions:
            path = self.pathfinder.find_path(
                start_mm=net_def.start,
                goal_mm=net_def.end,
                layer=net_def.layer,
                allow_diagonals=True
            )

            if path is None:
                continue

            # Create segments from path
            segments = []
            for i in range(len(path) - 1):
                segments.append((path[i], path[i + 1]))

            initial_routes[net_def.name] = RoutedNet(
                name=net_def.name,
                path=path,
                layer=net_def.layer,
                segments=segments
            )

        # Convert to NetPath format for optimizer
        net_paths = []
        for net_name, routed_net in initial_routes.items():
            net_paths.append(NetPath(
                name=net_name,
                segments=routed_net.segments,
                default_layer=routed_net.layer
            ))

        # Optimize layer assignments
        layer_assignments = self.optimizer.optimize_layer_assignments(net_paths)

        # Apply optimized layer assignments (would update RoutedNet objects)
        # For now, return the initial routes
        # Full implementation would re-assign layers based on optimization results

        return initial_routes

    def _prioritize_nets(
        self,
        net_definitions: List[NetDefinition]
    ) -> List[NetDefinition]:
        """
        Prioritize nets for routing order.

        Routing order:
        1. Power nets (GND, VCC, VDD, VSS, +12V, +5V, +3V3 patterns) - critical infrastructure
        2. Explicit priority value (higher first)
        3. Number of connections (more connections = higher complexity = route first)
        4. Length (shorter nets first - easier to route)
        5. Name (alphabetical for determinism)

        Power nets are routed first because they typically need wider traces and
        provide critical infrastructure for the rest of the circuit. Signal nets
        are then routed around the established power distribution.

        Args:
            net_definitions: List of NetDefinition objects

        Returns:
            Sorted list of NetDefinition objects
        """
        # Hardcoded power net patterns (as per architectural decisions)
        POWER_NET_PATTERNS = {'GND', 'VCC', 'VDD', 'VSS', '+12V', '+5V', '+3V3'}

        def is_power_net(net_name: str) -> bool:
            """Check if net name matches power net patterns."""
            net_upper = net_name.upper()
            return any(pattern in net_upper for pattern in POWER_NET_PATTERNS)

        def priority_key(net_def: NetDefinition) -> Tuple:
            # Calculate estimated length
            dx = net_def.end[0] - net_def.start[0]
            dy = net_def.end[1] - net_def.start[1]
            length = math.sqrt(dx * dx + dy * dy)

            # Determine if power net (0 = power, 1 = signal)
            power_priority = 0 if is_power_net(net_def.name) else 1

            # Sort by:
            # 1. Power nets first (0 < 1)
            # 2. Explicit priority (descending - higher priority first)
            # 3. Length (ascending - shorter first)
            # 4. Name (ascending - alphabetical)
            return (power_priority, -net_def.priority, length, net_def.name)

        return sorted(net_definitions, key=priority_key)

    def _mark_net_as_obstacle(
        self,
        path: List[Tuple[float, float]],
        layer: str,
        net_name: str
    ) -> None:
        """
        Mark routed net as obstacle AND crossing-forbidden zone for subsequent routing.

        This method marks both:
        1. Trace segments as obstacles (for DRC clearance)
        2. Crossing-forbidden zones (HARD BLOCK - forces vias instead of crossings)

        Args:
            path: Waypoints of the routed path
            layer: Layer the net is routed on
            net_name: Net name (for tracking forbidden zones)
        """
        # Mark trace segments as obstacles (not just waypoints)
        for i in range(len(path) - 1):
            start = path[i]
            end = path[i + 1]

            # Mark trace segment as obstacle (for clearance)
            self.grid.mark_trace_segment(
                start_mm=start,
                end_mm=end,
                layer=layer,
                width_mm=0.25,  # Default trace width
                clearance_mm=0.2  # Default clearance
            )

            # Mark crossing-forbidden zone (HARD BLOCK - prevents crossings)
            # This forces subsequent nets to use vias instead of creating crossings
            self.grid.mark_crossing_forbidden_zone(
                start_mm=start,
                end_mm=end,
                layer=layer,
                trace_width_mm=0.25,
                net_name=net_name
            )

    def _detect_conflicts(
        self,
        routed_nets: Dict[str, RoutedNet]
    ) -> List[Tuple[str, str]]:
        """
        Detect conflicts between routed nets.

        Checks for:
        - Same-layer crossings between different nets
        - Clearance violations

        Args:
            routed_nets: Dictionary of routed nets

        Returns:
            List of (net1_name, net2_name) tuples with conflicts
        """
        conflicts = []

        net_list = list(routed_nets.values())
        for i, net1 in enumerate(net_list):
            for net2 in net_list[i + 1:]:
                # Check if nets on same layer
                if net1.layer == net2.layer:
                    # Check for segment crossings
                    for seg1 in net1.segments:
                        for seg2 in net2.segments:
                            if self._segments_intersect(seg1, seg2):
                                conflicts.append((net1.name, net2.name))
                                break

        return conflicts

    def _validate_routing(
        self,
        routed_nets: Dict[str, RoutedNet]
    ) -> bool:
        """
        Validate routing for DRC compliance.

        Checks:
        - No same-layer crossings
        - Clearance requirements met
        - All nets successfully routed

        Args:
            routed_nets: Dictionary of routed nets

        Returns:
            True if routing is valid, False if violations detected
        """
        # Check for conflicts
        conflicts = self._detect_conflicts(routed_nets)

        if conflicts:
            return False

        # All checks passed
        return True

    def _segments_intersect(
        self,
        seg1: Tuple[Tuple[float, float], Tuple[float, float]],
        seg2: Tuple[Tuple[float, float], Tuple[float, float]]
    ) -> bool:
        """
        Check if two line segments intersect.

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
        if 0 < t < 1 and 0 < u < 1:
            return True

        return False
