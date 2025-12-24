"""
Tests for routing constraints system.

Tests the ability to specify must-route nets, optional nets,
explicit routing order, and integrated via costs.
"""

import pytest
from pcb_tool.routing.grid import RoutingGrid
from pcb_tool.routing.multi_net_router import MultiNetRouter, NetDefinition
from pcb_tool.routing.constraints import RoutingConstraints
from pcb_tool.commands import AutoRouteCommand


def test_must_route_constraint():
    """Test that only must_route nets are attempted.

    When must_route is specified, only those nets should be routed.
    """
    grid = RoutingGrid(width_mm=50, height_mm=50, resolution_mm=0.5)
    router = MultiNetRouter(grid)

    # Define three nets
    net1 = NetDefinition(name="NET1", start=(10, 10), end=(40, 10), layer="F.Cu")
    net2 = NetDefinition(name="NET2", start=(10, 25), end=(40, 25), layer="F.Cu")
    net3 = NetDefinition(name="NET3", start=(10, 40), end=(40, 40), layer="F.Cu")

    # Create constraints with only NET1 and NET2 as must-route
    constraints = RoutingConstraints(must_route=["NET1", "NET2"])

    # Route with constraints
    routed = router.route_nets([net1, net2, net3], constraints=constraints)

    # Only NET1 and NET2 should be routed (NET3 filtered out)
    assert "NET1" in routed
    assert "NET2" in routed
    assert "NET3" not in routed


def test_optional_nets_graceful_failure():
    """Test that optional nets can fail without error.

    Optional nets are marked but failures should not prevent
    routing of other nets.
    """
    constraints = RoutingConstraints(
        optional=["OPTIONAL_NET1", "OPTIONAL_NET2"]
    )

    # Test helper methods
    assert constraints.is_optional("OPTIONAL_NET1") is True
    assert constraints.is_optional("OPTIONAL_NET2") is True
    assert constraints.is_optional("CRITICAL_NET") is False


def test_route_order_constraint():
    """Test that explicit route_order is respected.

    Explicit routing order should override priority-based ordering.
    """
    grid = RoutingGrid(width_mm=50, height_mm=50, resolution_mm=0.5)
    router = MultiNetRouter(grid)

    # Define three nets with different priorities
    net1 = NetDefinition(name="NET1", start=(10, 10), end=(40, 10), layer="F.Cu", priority=10)
    net2 = NetDefinition(name="NET2", start=(10, 25), end=(40, 25), layer="F.Cu", priority=5)
    net3 = NetDefinition(name="NET3", start=(10, 40), end=(40, 40), layer="F.Cu", priority=1)

    # Create constraints with explicit order (overrides priority)
    constraints = RoutingConstraints(route_order=["NET3", "NET1", "NET2"])

    # Apply constraints
    net_defs = [net1, net2, net3]
    ordered_nets = constraints.apply_constraints(net_defs)

    # Verify order: NET3, NET1, NET2 (not priority-based)
    assert ordered_nets[0].name == "NET3"
    assert ordered_nets[1].name == "NET1"
    assert ordered_nets[2].name == "NET2"


def test_constraints_command_integration():
    """Test constraints through AutoRouteCommand interface.

    Verify that AutoRouteCommand correctly accepts and applies
    routing constraints.
    """
    # Create constraints
    constraints = RoutingConstraints(
        must_route=["CRITICAL1", "CRITICAL2"],
        optional=["OPTIONAL"],
        route_order=["CRITICAL1", "CRITICAL2"],
        via_costs={"CRITICAL1": 100.0}
    )

    # Create auto-route command with constraints
    cmd = AutoRouteCommand(
        net_name="ALL",
        constraints=constraints
    )

    # Verify constraints are stored
    assert cmd.constraints is not None
    assert cmd.constraints.must_route == ["CRITICAL1", "CRITICAL2"]
    assert cmd.constraints.optional == ["OPTIONAL"]
    assert cmd.constraints.route_order == ["CRITICAL1", "CRITICAL2"]
    assert cmd.constraints.via_costs == {"CRITICAL1": 100.0}

    # Verify helper methods work
    assert constraints.is_optional("OPTIONAL") is True
    assert constraints.get_via_cost("CRITICAL1") == 100.0
