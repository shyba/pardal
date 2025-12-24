"""
Tests for Lazy Constraints Module

Tests management of blocking constraints for Z3 iterative refinement.
"""

import pytest
from pcb_tool.routing.lazy_constraints import LazyConstraintManager
from pcb_tool.routing.crossing_detector import Crossing


def test_add_crossing_blocks():
    """Test adding crossing blocks."""
    manager = LazyConstraintManager()

    # Create some crossings
    crossings = [
        Crossing(net1="net1", net2="net2", cell=(5, 5), layer="F.Cu"),
        Crossing(net1="net3", net2="net4", cell=(10, 10), layer="F.Cu")
    ]

    # Add blocks
    manager.add_crossing_blocks(crossings)

    # Verify blocks were added
    assert manager.get_count() == 2

    # Verify blocked cells
    assert len(manager.blocked_cells) == 2

    # Check deterministic blocking (max net name should be blocked)
    blocked_nets = [net for net, cell, layer in manager.blocked_cells]
    assert "net2" in blocked_nets  # max("net1", "net2") = "net2"
    assert "net4" in blocked_nets  # max("net3", "net4") = "net4"


def test_apply_to_solver():
    """Test applying constraints to mock solver."""
    manager = LazyConstraintManager()

    # Create crossing
    crossings = [
        Crossing(net1="net1", net2="net2", cell=(5, 5), layer="F.Cu")
    ]
    manager.add_crossing_blocks(crossings)

    # Mock Z3 components
    class MockSolver:
        def __init__(self):
            self.constraints = []

        def add(self, constraint):
            self.constraints.append(constraint)

    class MockVar:
        def __init__(self, name):
            self.name = name

        def __ne__(self, other):
            return f"{self.name} != {other}"

    # Create mock solver and variables
    solver = MockSolver()
    cell_vars = {
        (5, 5, "F.Cu"): MockVar("cell_5_5_F.Cu")
    }
    net_name_to_idx = {
        "net1": 0,
        "net2": 1
    }

    # Apply constraints
    manager.apply_to_solver(solver, cell_vars, net_name_to_idx)

    # Verify constraint was added
    assert len(solver.constraints) == 1
    # "net2" should be blocked (max of net1, net2)
    assert "cell_5_5_F.Cu != 1" in str(solver.constraints[0])


def test_count_tracking():
    """Test count tracking."""
    manager = LazyConstraintManager()

    # Initially zero
    assert manager.get_count() == 0

    # Add some blocks
    crossings = [
        Crossing(net1="net1", net2="net2", cell=(5, 5), layer="F.Cu"),
        Crossing(net1="net3", net2="net4", cell=(10, 10), layer="F.Cu"),
        Crossing(net1="net5", net2="net6", cell=(15, 15), layer="B.Cu")
    ]
    manager.add_crossing_blocks(crossings)

    # Verify count
    assert manager.get_count() == 3


def test_empty_crossings():
    """Test handling empty crossings list."""
    manager = LazyConstraintManager()

    # Add empty list
    manager.add_crossing_blocks([])

    # Count should be zero
    assert manager.get_count() == 0
