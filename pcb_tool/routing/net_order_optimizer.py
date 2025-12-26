"""
Net Order Optimizer using Z3 SMT Solver

Optimizes the routing order of nets based on net properties and user constraints.
Uses Z3 to find optimal ordering that minimizes routing complexity.
"""

from typing import List, Tuple, Dict, Optional
import math

# Try to import z3, gracefully handle if not available
try:
    import z3

    Z3_AVAILABLE = True
except ImportError:
    Z3_AVAILABLE = False


class NetOrderOptimizer:
    """
    Optimizes net routing order using Z3 SMT solver.

    Uses constraint solving to find optimal routing order that:
    - Routes shorter nets first (easier to route)
    - Respects user-specified ordering constraints
    - Routes higher priority nets earlier
    """

    def __init__(self):
        """Initialize the net order optimizer."""
        self.z3_available = Z3_AVAILABLE

    def optimize_order(
        self, nets: List[Dict], user_constraints: Optional[List[Tuple[str, str]]] = None
    ) -> List[str]:
        """
        Optimize routing order for given nets.

        Args:
            nets: List of net dictionaries with keys:
                  - name: Net name
                  - length: Estimated length in mm
                  - priority: Priority value (higher = more important)
            user_constraints: List of (net_a, net_b) tuples where net_a must route before net_b

        Returns:
            Ordered list of net names

        Example:
            >>> nets = [
            ...     {"name": "GND", "length": 50.0, "priority": 10},
            ...     {"name": "SIG1", "length": 20.0, "priority": 1},
            ...     {"name": "SIG2", "length": 30.0, "priority": 1}
            ... ]
            >>> optimizer = NetOrderOptimizer()
            >>> order = optimizer.optimize_order(nets)
            >>> # Shorter nets routed first: ["SIG1", "SIG2", "GND"]
        """
        if not nets:
            return []

        # If z3 not available, fall back to heuristic-based ordering
        if not self.z3_available:
            return self._fallback_order(nets, user_constraints)

        # Use Z3 to find optimal order
        return self._z3_optimize_order(nets, user_constraints or [])

    def _z3_optimize_order(
        self, nets: List[Dict], user_constraints: List[Tuple[str, str]]
    ) -> List[str]:
        """
        Use Z3 to find optimal net ordering.

        Args:
            nets: List of net dictionaries
            user_constraints: List of (net_a, net_b) ordering constraints

        Returns:
            Optimized list of net names
        """
        if not Z3_AVAILABLE:
            return self._fallback_order(nets, user_constraints)

        # Create Z3 optimizer
        opt = z3.Optimize()

        # Create order variables: order[net_name] = Int (position 0 to N-1)
        order_vars = {}
        for net in nets:
            order_vars[net["name"]] = z3.Int(f"order_{net['name']}")

        # Constraint: All orders must be distinct (each net at unique position)
        opt.add(z3.Distinct(*order_vars.values()))

        # Constraint: Orders must be in valid range [0, N-1]
        n = len(nets)
        for net in nets:
            opt.add(order_vars[net["name"]] >= 0)
            opt.add(order_vars[net["name"]] < n)

        # User constraints: order[A] < order[B] means A before B
        for net_a, net_b in user_constraints:
            if net_a in order_vars and net_b in order_vars:
                opt.add(order_vars[net_a] < order_vars[net_b])

        # Objective: We want shorter nets and higher priority nets to route FIRST
        # (have SMALLER order numbers).
        #
        # Define "routing cost" = length / (1 + priority)
        # - Higher priority → lower cost → should route first
        # - Shorter length → lower cost → should route first
        #
        # We MAXIMIZE sum(order * cost), so high-cost nets get HIGH order numbers
        # (route later) and low-cost nets get LOW order numbers (route first).
        objective_terms = []
        for net in nets:
            net_name = net["name"]
            length = net.get("length", 0)
            priority = net.get("priority", 0)

            # Routing cost: lower cost = routes earlier
            # Higher priority → lower cost (divide by (1+priority)^2 to make priority dominant)
            # Shorter length → lower cost
            # Using squared priority divisor ensures priority overrides length differences
            cost = max(1.0, length) / ((1.0 + priority) ** 2)
            # Scale to integer for Z3
            cost_int = int(cost * 100)

            objective_terms.append(order_vars[net_name] * cost_int)

        # MAXIMIZE the objective so high-cost nets get high order numbers
        if objective_terms:
            opt.maximize(z3.Sum(objective_terms))

        # Solve
        if opt.check() == z3.sat:
            model = opt.model()

            # Extract solution
            net_positions = []
            for net in nets:
                net_name = net["name"]
                position = model[order_vars[net_name]].as_long()
                net_positions.append((position, net_name))

            # Sort by position
            net_positions.sort()

            # Return ordered net names
            return [name for _, name in net_positions]
        else:
            # Z3 couldn't find solution, fall back to heuristic
            return self._fallback_order(nets, user_constraints)

    def _fallback_order(
        self, nets: List[Dict], user_constraints: Optional[List[Tuple[str, str]]] = None
    ) -> List[str]:
        """
        Fallback heuristic-based ordering when Z3 is not available.

        Uses simple heuristic: sort by (priority descending, length ascending).

        Args:
            nets: List of net dictionaries
            user_constraints: List of (net_a, net_b) ordering constraints (partially honored)

        Returns:
            Ordered list of net names
        """
        # Sort by priority (descending), then length (ascending)
        sorted_nets = sorted(
            nets, key=lambda n: (-n.get("priority", 0), n.get("length", 0))
        )

        # Basic constraint satisfaction: move constrained nets
        # This is a simple greedy approach, not guaranteed to satisfy all constraints
        result = [net["name"] for net in sorted_nets]

        if user_constraints:
            # Try to honor constraints by swapping
            for net_a, net_b in user_constraints:
                if net_a in result and net_b in result:
                    idx_a = result.index(net_a)
                    idx_b = result.index(net_b)
                    if idx_a > idx_b:  # A should come before B but doesn't
                        # Swap them
                        result[idx_a], result[idx_b] = result[idx_b], result[idx_a]

        return result
