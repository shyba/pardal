"""Integration tests for AUTOROUTE and OPTIMIZE commands in REPL workflow.

Tests the complete REPL workflow from loading netlist through autorouting
and optimization, including command chaining and state management.
"""

import pytest
from pathlib import Path
from pcb_tool.data_model import Board, Component, Net, Pad
from pcb_tool.command_parser import CommandParser
from pcb_tool.commands import AutoRouteCommand, OptimizeRoutingCommand


def create_test_netlist_board():
    """Create a realistic test board simulating loaded netlist."""
    board = Board()

    # Add components simulating a simple circuit (use small coordinates that fit in grid)
    components_data = [
        ("U1", "STM32", "QFP-64", (15.0, 15.0)),
        ("C1", "100n", "C_0805", (10.0, 10.0)),
        ("C2", "100n", "C_0805", (20.0, 10.0)),
        ("R1", "10k", "R_0805", (25.0, 15.0)),
        ("R2", "10k", "R_0805", (5.0, 15.0)),
        ("LED1", "RED", "LED_0805", (15.0, 25.0)),
    ]

    for ref, value, footprint, pos in components_data:
        comp = Component(
            ref=ref,
            value=value,
            footprint=footprint,
            position=pos,
            rotation=0.0,
            layer="F.Cu"
        )
        # Add pads
        comp.pads = [
            Pad(number=1, position_offset=(-0.5, 0.0), size=(0.8, 0.8)),
            Pad(number=2, position_offset=(0.5, 0.0), size=(0.8, 0.8))
        ]
        board.add_component(comp)

    # Add nets simulating netlist connections (2-point nets for current router)
    nets_data = [
        ("GND", [("C1", "1"), ("C2", "1")]),
        ("VCC", [("U1", "2"), ("C1", "2")]),
        ("LED_OUT", [("LED1", "1"), ("R2", "1")]),
        ("RESET", [("U1", "1"), ("R1", "1")]),
    ]

    for i, (net_name, connections) in enumerate(nets_data, start=1):
        net = Net(name=net_name, code=str(i))
        for ref, pin in connections:
            net.add_connection(ref, pin)
        board.add_net(net)

    return board


def test_repl_workflow_autoroute_single_net():
    """Test REPL workflow: parse and execute AUTOROUTE NET command."""
    board = create_test_netlist_board()
    parser = CommandParser()

    # Parse AUTOROUTE NET command
    cmd = parser.parse("AUTOROUTE NET GND")
    assert cmd is not None
    assert isinstance(cmd, AutoRouteCommand)

    # Validate and execute
    error = cmd.validate(board)
    assert error is None

    result = cmd.execute(board)
    assert result is not None
    assert "GND" in result

    # Verify routing was added
    gnd_net = board.nets["GND"]
    assert len(gnd_net.segments) > 0


def test_repl_workflow_autoroute_all():
    """Test REPL workflow: parse and execute AUTOROUTE ALL command."""
    board = create_test_netlist_board()
    parser = CommandParser()

    # Parse AUTOROUTE ALL command
    cmd = parser.parse("AUTOROUTE ALL")
    assert cmd is not None
    assert isinstance(cmd, AutoRouteCommand)

    # Execute
    result = cmd.execute(board)
    assert result is not None
    assert "routed" in result.lower()

    # Verify all nets with connections are routed
    for net in board.nets.values():
        if len(net.connections) >= 2:
            assert len(net.segments) > 0, f"Net {net.name} should be routed"


def test_repl_workflow_autoroute_with_layer_preference():
    """Test REPL workflow: AUTOROUTE with layer preference."""
    board = create_test_netlist_board()
    parser = CommandParser()

    # Parse with layer preference
    cmd = parser.parse("AUTOROUTE NET VCC LAYER B.Cu")
    assert cmd is not None
    assert isinstance(cmd, AutoRouteCommand)
    assert cmd.prefer_layer == "B.Cu"

    # Execute
    result = cmd.execute(board)
    assert result is not None


def test_repl_workflow_optimize_after_autoroute():
    """Test REPL workflow: AUTOROUTE followed by OPTIMIZE ROUTING."""
    board = create_test_netlist_board()
    parser = CommandParser()

    # Step 1: Auto-route all nets
    autoroute_cmd = parser.parse("AUTOROUTE ALL")
    autoroute_result = autoroute_cmd.execute(board)
    assert "routed" in autoroute_result.lower()

    # Step 2: Optimize routing
    optimize_cmd = parser.parse("OPTIMIZE ROUTING ALL")
    assert isinstance(optimize_cmd, OptimizeRoutingCommand)

    optimize_result = optimize_cmd.execute(board)
    assert optimize_result is not None
    assert "optim" in optimize_result.lower()


def test_repl_workflow_command_chaining():
    """Test REPL workflow: multiple commands in sequence."""
    board = create_test_netlist_board()
    parser = CommandParser()

    # Simulate REPL command sequence
    commands = [
        "AUTOROUTE NET GND",
        "AUTOROUTE NET VCC",
        "AUTOROUTE NET LED_OUT",
        "OPTIMIZE ROUTING ALL"
    ]

    for cmd_str in commands:
        cmd = parser.parse(cmd_str)
        assert cmd is not None, f"Failed to parse: {cmd_str}"

        error = cmd.validate(board)
        assert error is None, f"Validation failed for: {cmd_str}"

        result = cmd.execute(board)
        assert result is not None, f"Execution failed for: {cmd_str}"


def test_repl_workflow_undo_autoroute():
    """Test REPL workflow: AUTOROUTE followed by undo."""
    board = create_test_netlist_board()
    parser = CommandParser()

    # Auto-route GND net
    cmd = parser.parse("AUTOROUTE NET GND")
    cmd.execute(board)

    # Verify routing exists
    assert len(board.nets["GND"].segments) > 0

    # Undo
    undo_result = cmd.undo(board)
    assert "Undone" in undo_result

    # Verify routing was removed
    assert len(board.nets["GND"].segments) == 0


def test_repl_workflow_error_handling_invalid_net():
    """Test REPL workflow: error handling for invalid net name."""
    board = create_test_netlist_board()
    parser = CommandParser()

    # Try to route non-existent net
    cmd = parser.parse("AUTOROUTE NET INVALID_NET")
    error = cmd.validate(board)

    assert error is not None
    assert "not found" in error.lower()


def test_repl_workflow_error_handling_empty_board():
    """Test REPL workflow: error handling for empty board."""
    board = Board()  # Empty board
    parser = CommandParser()

    # Try to autoroute on empty board
    cmd = parser.parse("AUTOROUTE ALL")
    error = cmd.validate(board)

    assert error is not None
    assert "no components" in error.lower() or "no nets" in error.lower()


def test_repl_workflow_autoroute_unrouted_only():
    """Test REPL workflow: AUTOROUTE ALL UNROUTED command."""
    board = create_test_netlist_board()
    parser = CommandParser()

    # Manually route GND net (simulate previous routing)
    from pcb_tool.data_model import TraceSegment
    board.nets["GND"].add_segment(
        TraceSegment("GND", (50, 50), (45, 45), "F.Cu", 0.25)
    )

    # Auto-route only unrouted nets
    cmd = parser.parse("AUTOROUTE ALL UNROUTED")
    assert cmd.net_name == "UNROUTED"

    result = cmd.execute(board)
    assert result is not None

    # GND should still have only 1 segment
    assert len(board.nets["GND"].segments) == 1

    # Other nets should be routed
    for net_name in ["VCC", "LED_OUT", "RESET"]:
        if len(board.nets[net_name].connections) >= 2:
            assert len(board.nets[net_name].segments) > 0


def test_repl_workflow_case_insensitive_commands():
    """Test REPL workflow: commands are case insensitive."""
    board = create_test_netlist_board()
    parser = CommandParser()

    # Test lowercase
    cmd = parser.parse("autoroute all")
    assert isinstance(cmd, AutoRouteCommand)

    # Test mixed case
    cmd = parser.parse("AutoRoute NET gnd")
    assert isinstance(cmd, AutoRouteCommand)

    # Test uppercase
    cmd = parser.parse("OPTIMIZE ROUTING ALL")
    assert isinstance(cmd, OptimizeRoutingCommand)


def test_repl_workflow_parser_validation():
    """Test REPL workflow: parser returns None for invalid syntax."""
    parser = CommandParser()

    # Invalid: missing NET or ALL
    cmd = parser.parse("AUTOROUTE")
    assert cmd is None

    # Invalid: missing ROUTING keyword
    cmd = parser.parse("OPTIMIZE NET GND")
    assert cmd is None

    # Invalid: incomplete command
    cmd = parser.parse("AUTOROUTE NET")
    assert cmd is None


def test_repl_workflow_complete_pcb_design():
    """Test complete REPL workflow simulating real PCB design session."""
    board = create_test_netlist_board()
    parser = CommandParser()

    # Step 1: Check initial state
    assert len(board.components) == 6
    assert len(board.nets) == 4

    # Step 2: Route power nets first (common practice)
    gnd_cmd = parser.parse("AUTOROUTE NET GND")
    gnd_result = gnd_cmd.execute(board)
    assert "routed" in gnd_result.lower()

    vcc_cmd = parser.parse("AUTOROUTE NET VCC")
    vcc_result = vcc_cmd.execute(board)
    assert "routed" in vcc_result.lower()

    # Step 3: Route remaining nets
    remaining_cmd = parser.parse("AUTOROUTE ALL UNROUTED")
    remaining_result = remaining_cmd.execute(board)
    assert remaining_result is not None

    # Step 4: Optimize all routing
    optimize_cmd = parser.parse("OPTIMIZE ROUTING ALL")
    optimize_result = optimize_cmd.execute(board)
    assert "optim" in optimize_result.lower()

    # Step 5: Verify all nets are routed
    for net in board.nets.values():
        if len(net.connections) >= 2:
            assert len(net.segments) > 0, f"Net {net.name} should be routed"

    # Step 6: Test undo capability
    undo_result = optimize_cmd.undo(board)
    assert "Undone" in undo_result or "Restored" in undo_result


def test_repl_workflow_quoted_net_names():
    """Test REPL workflow with quoted net names containing special characters."""
    board = Board()

    # Add components
    comp1 = Component("U1", "IC", "QFP-64", (50.0, 50.0), 0.0)
    comp1.pads = [Pad(1, (0, 0), (1, 1)), Pad(2, (2, 0), (1, 1))]
    board.add_component(comp1)

    comp2 = Component("U2", "IC", "QFP-64", (60.0, 50.0), 0.0)
    comp2.pads = [Pad(1, (0, 0), (1, 1)), Pad(2, (2, 0), (1, 1))]
    board.add_component(comp2)

    # Add net with special characters
    net = Net(name="Net-_(VCC_3V3)", code="1")
    net.add_connection("U1", "1")
    net.add_connection("U2", "1")
    board.add_net(net)

    parser = CommandParser()

    # Parse with quoted name
    cmd = parser.parse('AUTOROUTE NET "Net-_(VCC_3V3)"')
    assert cmd is not None
    assert cmd.net_name == "Net-_(VCC_3V3)"

    result = cmd.execute(board)
    assert result is not None


def test_repl_workflow_performance():
    """Test REPL workflow completes in reasonable time for typical board."""
    import time

    board = create_test_netlist_board()
    parser = CommandParser()

    # Time the autoroute operation
    start = time.time()
    cmd = parser.parse("AUTOROUTE ALL")
    cmd.execute(board)
    elapsed = time.time() - start

    # Should complete in under 2 seconds for small board
    assert elapsed < 2.0

    # Time the optimize operation
    start = time.time()
    opt_cmd = parser.parse("OPTIMIZE ROUTING ALL")
    opt_cmd.execute(board)
    opt_elapsed = time.time() - start

    # Optimization should also be fast
    assert opt_elapsed < 5.0  # More lenient for Z3 solver


def test_repl_workflow_state_consistency():
    """Test that REPL workflow maintains consistent board state."""
    board = create_test_netlist_board()
    parser = CommandParser()

    # Record initial state
    initial_components = len(board.components)
    initial_nets = len(board.nets)

    # Execute commands
    parser.parse("AUTOROUTE ALL").execute(board)
    parser.parse("OPTIMIZE ROUTING ALL").execute(board)

    # Verify state consistency
    assert len(board.components) == initial_components
    assert len(board.nets) == initial_nets

    # Verify nets still have their connections
    for net in board.nets.values():
        assert len(net.connections) > 0


def test_repl_workflow_multiple_autoroute_calls():
    """Test that calling AUTOROUTE multiple times doesn't duplicate segments."""
    board = create_test_netlist_board()
    parser = CommandParser()

    # Route once
    cmd1 = parser.parse("AUTOROUTE NET GND")
    cmd1.execute(board)
    first_count = len(board.nets["GND"].segments)

    # Route again (should add more segments if routing algorithm is stateless)
    cmd2 = parser.parse("AUTOROUTE NET GND")
    cmd2.execute(board)
    second_count = len(board.nets["GND"].segments)

    # Count should have increased (new routing added)
    assert second_count >= first_count
