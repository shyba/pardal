"""
Tests for Z3-based net order optimization.

Tests the NetOrderOptimizer's ability to find optimal routing orders
using Z3 constraint solving, with graceful fallback when Z3 is unavailable.
"""

import pytest
from pcb_tool.routing.net_order_optimizer import NetOrderOptimizer, Z3_AVAILABLE


def test_optimize_order_by_length():
    """Test that optimizer orders shorter nets first.

    When no constraints are given, shorter nets should be ordered
    before longer nets to simplify routing.
    """
    optimizer = NetOrderOptimizer()

    nets = [
        {"name": "LONG", "length": 100.0, "priority": 0},
        {"name": "SHORT", "length": 10.0, "priority": 0},
        {"name": "MEDIUM", "length": 50.0, "priority": 0}
    ]

    order = optimizer.optimize_order(nets)

    # Should order by length: SHORT, MEDIUM, LONG
    assert order.index("SHORT") < order.index("MEDIUM")
    assert order.index("MEDIUM") < order.index("LONG")


def test_optimize_order_with_user_constraints():
    """Test that optimizer respects user-specified ordering constraints.

    User constraints like "A before B" should be honored even if
    they conflict with length-based ordering.
    """
    optimizer = NetOrderOptimizer()

    nets = [
        {"name": "A", "length": 100.0, "priority": 0},  # Long
        {"name": "B", "length": 50.0, "priority": 0},   # Medium
        {"name": "C", "length": 10.0, "priority": 0}    # Short
    ]

    # Constraint: A must route before C (even though C is shorter)
    user_constraints = [("A", "C")]

    order = optimizer.optimize_order(nets, user_constraints)

    # A must come before C (constraint)
    assert order.index("A") < order.index("C")

    # All nets should be present
    assert len(order) == 3
    assert set(order) == {"A", "B", "C"}


def test_z3_not_available_fallback():
    """Test graceful fallback when Z3 is not available.

    Optimizer should fall back to heuristic-based ordering
    when Z3 is not installed.
    """
    optimizer = NetOrderOptimizer()

    nets = [
        {"name": "HIGH_PRI", "length": 100.0, "priority": 10},
        {"name": "LOW_PRI", "length": 10.0, "priority": 0}
    ]

    # Should work regardless of Z3 availability
    order = optimizer.optimize_order(nets)

    # High priority should come first (fallback behavior)
    assert order.index("HIGH_PRI") < order.index("LOW_PRI")

    # Verify Z3 availability flag is set correctly
    assert optimizer.z3_available == Z3_AVAILABLE


def test_optimize_order_with_priorities():
    """Test that higher priority nets are ordered earlier.

    Priority should override length-based ordering.
    """
    optimizer = NetOrderOptimizer()

    nets = [
        {"name": "LOW_PRI", "length": 10.0, "priority": 1},
        {"name": "HIGH_PRI", "length": 100.0, "priority": 10}
    ]

    order = optimizer.optimize_order(nets)

    # High priority should override length
    # (HIGH_PRI should come before LOW_PRI despite being longer)
    assert order.index("HIGH_PRI") < order.index("LOW_PRI")


def test_optimize_empty_nets():
    """Test optimizer handles empty net list gracefully."""
    optimizer = NetOrderOptimizer()

    order = optimizer.optimize_order([])

    assert order == []


def test_optimize_single_net():
    """Test optimizer handles single net correctly."""
    optimizer = NetOrderOptimizer()

    nets = [{"name": "SINGLE", "length": 50.0, "priority": 0}]

    order = optimizer.optimize_order(nets)

    assert order == ["SINGLE"]
