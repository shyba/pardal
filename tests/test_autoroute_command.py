"""Tests for AutoRouteCommand and OptimizeRoutingCommand."""

import pytest
from pcb_tool.data_model import Board, Component, Net, Pad
from pcb_tool.commands import AutoRouteCommand, OptimizeRoutingCommand
from pcb_tool.command_parser import CommandParser


def create_test_board_with_nets():
    """Create a test board with components and nets for routing tests."""
    board = Board()

    # Add components with pads
    comp1 = Component(
        ref="R1",
        value="10k",
        footprint="R_0805",
        position=(10.0, 10.0),
        rotation=0.0,
        layer="F.Cu"
    )
    comp1.pads = [
        Pad(number=1, position_offset=(0.0, 0.0), size=(1.0, 1.0)),
        Pad(number=2, position_offset=(2.0, 0.0), size=(1.0, 1.0))
    ]
    board.add_component(comp1)

    comp2 = Component(
        ref="R2",
        value="10k",
        footprint="R_0805",
        position=(20.0, 10.0),
        rotation=0.0,
        layer="F.Cu"
    )
    comp2.pads = [
        Pad(number=1, position_offset=(0.0, 0.0), size=(1.0, 1.0)),
        Pad(number=2, position_offset=(2.0, 0.0), size=(1.0, 1.0))
    ]
    board.add_component(comp2)

    comp3 = Component(
        ref="C1",
        value="100n",
        footprint="C_0805",
        position=(10.0, 20.0),
        rotation=0.0,
        layer="F.Cu"
    )
    comp3.pads = [
        Pad(number=1, position_offset=(0.0, 0.0), size=(1.0, 1.0)),
        Pad(number=2, position_offset=(2.0, 0.0), size=(1.0, 1.0))
    ]
    board.add_component(comp3)

    # Add nets with connections
    net1 = Net(name="GND", code="1")
    net1.add_connection("R1", "1")
    net1.add_connection("R2", "1")
    board.add_net(net1)

    net2 = Net(name="VCC", code="2")
    net2.add_connection("R2", "2")
    net2.add_connection("C1", "1")
    board.add_net(net2)

    net3 = Net(name="SIG", code="3")
    net3.add_connection("R1", "2")
    net3.add_connection("C1", "2")
    board.add_net(net3)

    return board


def test_autoroute_command_creation():
    """Test AutoRouteCommand initialization."""
    # Default: route all nets
    cmd = AutoRouteCommand()
    assert cmd.net_name == "ALL"
    assert cmd.prefer_layer is None
    assert cmd.optimize is True

    # Specific net
    cmd = AutoRouteCommand(net_name="GND")
    assert cmd.net_name == "GND"

    # With layer preference
    cmd = AutoRouteCommand(net_name="GND", prefer_layer="B.Cu")
    assert cmd.net_name == "GND"
    assert cmd.prefer_layer == "B.Cu"

    # Unrouted only
    cmd = AutoRouteCommand(net_name="UNROUTED")
    assert cmd.net_name == "UNROUTED"


def test_autoroute_validate_empty_board():
    """Test AutoRouteCommand validation fails on empty board."""
    cmd = AutoRouteCommand()
    board = Board()

    error = cmd.validate(board)
    assert error is not None
    assert "no components" in error.lower()


def test_autoroute_validate_no_nets():
    """Test AutoRouteCommand validation fails when board has no nets."""
    cmd = AutoRouteCommand()
    board = Board()
    board.add_component(Component("R1", "10k", "R_0805", (10, 10), 0.0))

    error = cmd.validate(board)
    assert error is not None
    assert "no nets" in error.lower()


def test_autoroute_validate_net_not_found():
    """Test AutoRouteCommand validation fails when specified net doesn't exist."""
    cmd = AutoRouteCommand(net_name="INVALID_NET")
    board = create_test_board_with_nets()

    error = cmd.validate(board)
    assert error is not None
    assert "not found" in error.lower()


def test_autoroute_validate_invalid_layer():
    """Test AutoRouteCommand validation fails with invalid layer."""
    cmd = AutoRouteCommand(net_name="GND", prefer_layer="INVALID")
    board = create_test_board_with_nets()

    error = cmd.validate(board)
    assert error is not None
    assert "invalid layer" in error.lower()


def test_autoroute_validate_success():
    """Test AutoRouteCommand validation succeeds with valid inputs."""
    cmd = AutoRouteCommand(net_name="GND")
    board = create_test_board_with_nets()

    error = cmd.validate(board)
    assert error is None


def test_autoroute_single_net():
    """Test routing a single net."""
    board = create_test_board_with_nets()
    cmd = AutoRouteCommand(net_name="GND")

    # Validate
    error = cmd.validate(board)
    assert error is None

    # Execute
    result = cmd.execute(board)
    assert result is not None
    assert "GND" in result

    # Check that routing was added
    net = board.nets["GND"]
    assert len(net.segments) > 0


def test_autoroute_all_nets():
    """Test routing all nets."""
    board = create_test_board_with_nets()
    cmd = AutoRouteCommand(net_name="ALL")

    error = cmd.validate(board)
    assert error is None

    result = cmd.execute(board)
    assert result is not None

    # Check that all nets with connections were routed
    for net in board.nets.values():
        if len(net.connections) >= 2:
            assert len(net.segments) > 0


def test_autoroute_unrouted_only():
    """Test routing only unrouted nets."""
    board = create_test_board_with_nets()

    # First route GND net manually (add a dummy segment)
    from pcb_tool.data_model import TraceSegment
    board.nets["GND"].add_segment(
        TraceSegment("GND", (10, 10), (20, 10), "F.Cu", 0.25)
    )

    # Now route unrouted nets
    cmd = AutoRouteCommand(net_name="UNROUTED")
    result = cmd.execute(board)

    # GND should still have only 1 segment (the manual one)
    assert len(board.nets["GND"].segments) == 1

    # Other nets should be routed
    assert len(board.nets["VCC"].segments) > 0
    assert len(board.nets["SIG"].segments) > 0


def test_autoroute_with_layer_preference():
    """Test routing with layer preference."""
    board = create_test_board_with_nets()
    cmd = AutoRouteCommand(net_name="GND", prefer_layer="B.Cu")

    error = cmd.validate(board)
    assert error is None

    result = cmd.execute(board)
    assert result is not None


def test_autoroute_undo():
    """Test undoing autoroute command."""
    board = create_test_board_with_nets()
    cmd = AutoRouteCommand(net_name="GND")

    # Route net
    cmd.execute(board)
    original_segment_count = len(board.nets["GND"].segments)
    assert original_segment_count > 0

    # Undo
    undo_result = cmd.undo(board)
    assert "Undone" in undo_result
    assert len(board.nets["GND"].segments) == 0


def test_optimize_routing_command_creation():
    """Test OptimizeRoutingCommand initialization."""
    # Default: optimize all nets
    cmd = OptimizeRoutingCommand()
    assert cmd.net_name == "ALL"

    # Specific net
    cmd = OptimizeRoutingCommand(net_name="GND")
    assert cmd.net_name == "GND"


def test_optimize_validate_no_nets():
    """Test OptimizeRoutingCommand validation fails when board has no nets."""
    cmd = OptimizeRoutingCommand()
    board = Board()

    error = cmd.validate(board)
    assert error is not None
    assert "no nets" in error.lower()


def test_optimize_validate_no_routing():
    """Test OptimizeRoutingCommand validation fails when there's no routing."""
    cmd = OptimizeRoutingCommand()
    board = create_test_board_with_nets()

    error = cmd.validate(board)
    assert error is not None
    assert "no routing" in error.lower()


def test_optimize_validate_net_not_found():
    """Test OptimizeRoutingCommand validation fails when net doesn't exist."""
    board = create_test_board_with_nets()
    # Add routing to at least one net so board has routing
    from pcb_tool.data_model import TraceSegment
    board.nets["GND"].add_segment(
        TraceSegment("GND", (10, 10), (20, 10), "F.Cu", 0.25)
    )

    cmd = OptimizeRoutingCommand(net_name="INVALID_NET")
    error = cmd.validate(board)
    assert error is not None
    assert "not found" in error.lower()


def test_optimize_validate_net_not_routed():
    """Test OptimizeRoutingCommand validation fails when specified net is not routed."""
    board = create_test_board_with_nets()
    # Add routing to VCC but not GND
    from pcb_tool.data_model import TraceSegment
    board.nets["VCC"].add_segment(
        TraceSegment("VCC", (20, 10), (10, 20), "F.Cu", 0.25)
    )

    cmd = OptimizeRoutingCommand(net_name="GND")
    error = cmd.validate(board)
    assert error is not None
    assert "no routing" in error.lower()


def test_optimize_routing_all_nets():
    """Test optimizing all routed nets."""
    board = create_test_board_with_nets()

    # Add some routing first
    from pcb_tool.data_model import TraceSegment
    board.nets["GND"].add_segment(
        TraceSegment("GND", (10, 10), (20, 10), "F.Cu", 0.25)
    )
    board.nets["VCC"].add_segment(
        TraceSegment("VCC", (20, 10), (10, 20), "F.Cu", 0.25)
    )

    cmd = OptimizeRoutingCommand(net_name="ALL")
    error = cmd.validate(board)
    assert error is None

    result = cmd.execute(board)
    assert result is not None
    assert "optimal" in result.lower() or "optimized" in result.lower()


def test_optimize_routing_single_net():
    """Test optimizing a single net."""
    board = create_test_board_with_nets()

    # Add routing to GND
    from pcb_tool.data_model import TraceSegment
    board.nets["GND"].add_segment(
        TraceSegment("GND", (10, 10), (15, 10), "F.Cu", 0.25)
    )
    board.nets["GND"].add_segment(
        TraceSegment("GND", (15, 10), (20, 10), "F.Cu", 0.25)
    )

    cmd = OptimizeRoutingCommand(net_name="GND")
    error = cmd.validate(board)
    assert error is None

    result = cmd.execute(board)
    assert result is not None


def test_optimize_undo():
    """Test undoing optimize routing command."""
    board = create_test_board_with_nets()

    # Add routing
    from pcb_tool.data_model import TraceSegment
    segment = TraceSegment("GND", (10, 10), (20, 10), "F.Cu", 0.25)
    board.nets["GND"].add_segment(segment)
    original_layer = segment.layer

    cmd = OptimizeRoutingCommand(net_name="GND")
    cmd.execute(board)

    # Undo
    undo_result = cmd.undo(board)
    assert "Undone" in undo_result or "Restored" in undo_result


def test_parser_autoroute_net():
    """Test parsing AUTOROUTE NET command."""
    parser = CommandParser()

    cmd = parser.parse("AUTOROUTE NET GND")
    assert isinstance(cmd, AutoRouteCommand)
    assert cmd.net_name == "GND"


def test_parser_autoroute_net_with_layer():
    """Test parsing AUTOROUTE NET with LAYER."""
    parser = CommandParser()

    cmd = parser.parse("AUTOROUTE NET GND LAYER B.Cu")
    assert isinstance(cmd, AutoRouteCommand)
    assert cmd.net_name == "GND"
    assert cmd.prefer_layer == "B.Cu"


def test_parser_autoroute_all():
    """Test parsing AUTOROUTE ALL command."""
    parser = CommandParser()

    cmd = parser.parse("AUTOROUTE ALL")
    assert isinstance(cmd, AutoRouteCommand)
    assert cmd.net_name == "ALL"


def test_parser_autoroute_all_unrouted():
    """Test parsing AUTOROUTE ALL UNROUTED command."""
    parser = CommandParser()

    cmd = parser.parse("AUTOROUTE ALL UNROUTED")
    assert isinstance(cmd, AutoRouteCommand)
    assert cmd.net_name == "UNROUTED"


def test_parser_autoroute_net_with_spaces():
    """Test parsing AUTOROUTE NET with multi-word net name."""
    parser = CommandParser()

    cmd = parser.parse('AUTOROUTE NET "Net-_VCC_3V3"')
    assert isinstance(cmd, AutoRouteCommand)
    assert cmd.net_name == "Net-_VCC_3V3"


def test_parser_optimize_routing_all():
    """Test parsing OPTIMIZE ROUTING ALL command."""
    parser = CommandParser()

    cmd = parser.parse("OPTIMIZE ROUTING ALL")
    assert isinstance(cmd, OptimizeRoutingCommand)
    assert cmd.net_name == "ALL"


def test_parser_optimize_routing_net():
    """Test parsing OPTIMIZE ROUTING NET command."""
    parser = CommandParser()

    cmd = parser.parse("OPTIMIZE ROUTING NET GND")
    assert isinstance(cmd, OptimizeRoutingCommand)
    assert cmd.net_name == "GND"


def test_parser_optimize_routing_net_with_spaces():
    """Test parsing OPTIMIZE ROUTING NET with multi-word net name."""
    parser = CommandParser()

    cmd = parser.parse('OPTIMIZE ROUTING NET "Net-_VCC_3V3"')
    assert isinstance(cmd, OptimizeRoutingCommand)
    assert cmd.net_name == "Net-_VCC_3V3"


def test_parser_autoroute_invalid():
    """Test parsing invalid AUTOROUTE commands."""
    parser = CommandParser()

    # No arguments
    cmd = parser.parse("AUTOROUTE")
    assert cmd is None

    # Invalid subcommand
    cmd = parser.parse("AUTOROUTE INVALID")
    assert cmd is None


def test_parser_optimize_invalid():
    """Test parsing invalid OPTIMIZE commands."""
    parser = CommandParser()

    # No arguments
    cmd = parser.parse("OPTIMIZE")
    assert cmd is None

    # Missing ROUTING keyword
    cmd = parser.parse("OPTIMIZE NET GND")
    assert cmd is None

    # Missing net name or ALL
    cmd = parser.parse("OPTIMIZE ROUTING")
    assert cmd is None


def test_parser_case_insensitive():
    """Test that parser is case insensitive."""
    parser = CommandParser()

    cmd = parser.parse("autoroute all")
    assert isinstance(cmd, AutoRouteCommand)

    cmd = parser.parse("OPTIMIZE routing ALL")
    assert isinstance(cmd, OptimizeRoutingCommand)

    cmd = parser.parse("AutoRoute Net gnd")
    assert isinstance(cmd, AutoRouteCommand)
    assert cmd.net_name == "gnd"


def test_autoroute_no_valid_connections():
    """Test autoroute when nets have no valid connections."""
    board = Board()
    board.add_component(Component("R1", "10k", "R_0805", (10, 10), 0.0))
    board.add_component(Component("R2", "10k", "R_0805", (20, 10), 0.0))

    # Add net with only one connection (can't route)
    net = Net(name="GND", code="1")
    net.add_connection("R1", "1")
    board.add_net(net)

    cmd = AutoRouteCommand(net_name="GND")
    result = cmd.execute(board)

    assert "no valid connections" in result.lower() or "could not be routed" in result.lower()


def test_autoroute_integration_workflow():
    """Test complete autoroute workflow."""
    board = create_test_board_with_nets()

    # Step 1: Route all nets
    cmd = AutoRouteCommand(net_name="ALL")
    assert cmd.validate(board) is None
    result = cmd.execute(board)
    assert "routed" in result.lower()

    # Step 2: Verify routing exists
    for net in board.nets.values():
        if len(net.connections) >= 2:
            assert len(net.segments) > 0

    # Step 3: Optimize routing
    opt_cmd = OptimizeRoutingCommand(net_name="ALL")
    assert opt_cmd.validate(board) is None
    opt_result = opt_cmd.execute(board)
    assert opt_result is not None

    # Step 4: Undo optimization
    opt_cmd.undo(board)

    # Step 5: Undo routing
    cmd.undo(board)
    for net in board.nets.values():
        assert len(net.segments) == 0
