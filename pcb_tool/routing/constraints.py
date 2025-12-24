"""
Routing Constraints System

Allows users to specify routing constraints like must-route nets,
optional nets, explicit routing order, and per-net via costs.
"""

from typing import List, Dict, Optional
from dataclasses import dataclass, field


@dataclass
class RoutingConstraints:
    """
    Routing constraints for multi-net routing.

    Allows specification of:
    - Must-route nets (routing failure is critical)
    - Optional nets (failures are acceptable)
    - Explicit routing order (overrides priority-based)
    - Per-net via costs (integrated with via_cost_map)
    """

    must_route: List[str] = field(default_factory=list)
    """Nets that MUST be routed successfully"""

    optional: List[str] = field(default_factory=list)
    """Nets that can fail gracefully (optional)"""

    route_order: List[str] = field(default_factory=list)
    """Explicit routing order (overrides priority-based ordering)"""

    via_costs: Dict[str, float] = field(default_factory=dict)
    """Per-net via costs (pattern matching supported)"""

    def apply_constraints(self, net_definitions: List) -> List:
        """
        Apply constraints to filter and reorder net definitions.

        Args:
            net_definitions: List of NetDefinition objects

        Returns:
            Filtered and reordered list of NetDefinition objects

        Processing:
        1. If must_route specified, filter to only those nets
        2. If route_order specified, reorder accordingly
        3. Optional nets are marked but not filtered
        """
        # If must_route is specified, filter to only must-route nets
        if self.must_route:
            net_definitions = [
                net for net in net_definitions
                if net.name in self.must_route
            ]

        # If route_order is specified, reorder nets accordingly
        if self.route_order:
            # Create a mapping from name to net definition
            net_map = {net.name: net for net in net_definitions}

            # Build ordered list based on route_order
            ordered_nets = []
            for net_name in self.route_order:
                if net_name in net_map:
                    ordered_nets.append(net_map[net_name])

            # Add any remaining nets not in route_order at the end
            remaining_nets = [
                net for net in net_definitions
                if net.name not in self.route_order
            ]
            net_definitions = ordered_nets + remaining_nets

        return net_definitions

    def is_optional(self, net_name: str) -> bool:
        """
        Check if a net is marked as optional.

        Args:
            net_name: Net name to check

        Returns:
            True if net is optional, False otherwise
        """
        return net_name in self.optional

    def get_via_cost(self, net_name: str) -> Optional[float]:
        """
        Get via cost for a specific net.

        Args:
            net_name: Net name

        Returns:
            Via cost if specified, None otherwise
        """
        return self.via_costs.get(net_name)
