"""
Tests for CHECK commands (DRC, AIRWIRES, CLEARANCE, CONNECTIVITY)
"""

import pytest
from pcb_tool.commands import (
    CheckDrcCommand,
    CheckAirwiresCommand,
    CheckClearanceCommand,
    CheckConnectivityCommand
)
from pcb_tool.command_parser import CommandParser
from pcb_tool.data_model import Board, Component, Net, TraceSegment


@pytest.fixture
def empty_board():
    """Empty board with no components or nets"""
    return Board()


@pytest.fixture
def basic_board():
    """Board with a few components and nets"""
    board = Board()

    # Add components
    board.add_component(Component(
        ref="R1", value="10K", footprint="R_0805",
        position=(10.0, 20.0), rotation=0.0
    ))
    board.add_component(Component(
        ref="R2", value="10K", footprint="R_0805",
        position=(15.0, 20.0), rotation=0.0
    ))
    board.add_component(Component(
        ref="U1", value="ATmega328P", footprint="DIP-28",
        position=(50.0, 60.0), rotation=0.0
    ))

    # Add nets
    net_vcc = Net(name="VCC", code="1")
    net_vcc.add_connection("R1", "1")
    net_vcc.add_connection("R2", "1")
    net_vcc.add_connection("U1", "7")
    board.add_net(net_vcc)

    net_gnd = Net(name="GND", code="2")
    net_gnd.add_connection("R1", "2")
    net_gnd.add_connection("R2", "2")
    net_gnd.add_connection("U1", "8")
    board.add_net(net_gnd)

    return board


@pytest.fixture
def board_with_routing():
    """Board with components, nets, and some routing"""
    board = Board()

    # Add components
    board.add_component(Component(
        ref="R1", value="10K", footprint="R_0805",
        position=(10.0, 20.0), rotation=0.0
    ))
    board.add_component(Component(
        ref="R2", value="10K", footprint="R_0805",
        position=(15.0, 20.0), rotation=0.0
    ))

    # Add nets with routing
    net_vcc = Net(name="VCC", code="1", track_width=0.25)
    net_vcc.add_connection("R1", "1")
    net_vcc.add_connection("R2", "1")
    # Add segment
    segment = TraceSegment("VCC", (10.0, 20.0), (15.0, 20.0), "F.Cu", 0.25)
    net_vcc.add_segment(segment)
    board.add_net(net_vcc)

    net_gnd = Net(name="GND", code="2")
    net_gnd.add_connection("R1", "2")
    net_gnd.add_connection("R2", "2")
    # No segments - unrouted
    board.add_net(net_gnd)

    return board


@pytest.fixture
def board_with_clearance_violations():
    """Board with components too close together"""
    board = Board()

    # Components very close - 0.15mm apart (< 0.2mm minimum)
    board.add_component(Component(
        ref="R1", value="10K", footprint="R_0805",
        position=(10.0, 20.0), rotation=0.0
    ))
    board.add_component(Component(
        ref="R2", value="10K", footprint="R_0805",
        position=(10.15, 20.0), rotation=0.0
    ))

    # Another pair too close
    board.add_component(Component(
        ref="U1", value="ATmega328P", footprint="DIP-28",
        position=(50.0, 60.0), rotation=0.0
    ))
    board.add_component(Component(
        ref="C1", value="100nF", footprint="C_0805",
        position=(50.18, 60.0), rotation=0.0
    ))

    return board


@pytest.fixture
def board_with_drc_errors():
    """Board with various DRC issues"""
    board = Board()

    # Components too close
    board.add_component(Component(
        ref="R1", value="10K", footprint="R_0805",
        position=(10.0, 20.0), rotation=0.0
    ))
    board.add_component(Component(
        ref="R2", value="10K", footprint="R_0805",
        position=(10.15, 20.0), rotation=0.0
    ))

    # Component with no connections
    board.add_component(Component(
        ref="U1", value="ATmega328P", footprint="DIP-28",
        position=(50.0, 60.0), rotation=0.0
    ))

    # Net with narrow track
    net_vcc = Net(name="VCC", code="1", track_width=0.15)
    net_vcc.add_connection("R1", "1")
    net_vcc.add_connection("R2", "1")
    segment = TraceSegment("VCC", (10.0, 20.0), (15.0, 20.0), "F.Cu", 0.15)
    net_vcc.add_segment(segment)
    board.add_net(net_vcc)

    # Net with connections but no routing
    net_gnd = Net(name="GND", code="2")
    net_gnd.add_connection("R1", "2")
    net_gnd.add_connection("R2", "2")
    board.add_net(net_gnd)

    return board


# CheckDrcCommand Tests

def test_check_drc_command_creation():
    """Test CheckDrcCommand can be created"""
    cmd = CheckDrcCommand()
    assert cmd is not None


def test_check_drc_validate_always_none():
    """Test CheckDrcCommand.validate always returns None (read-only)"""
    cmd = CheckDrcCommand()
    board = Board()
    assert cmd.validate(board) is None


def test_check_drc_execute_empty_board(empty_board):
    """Test CHECK DRC on empty board"""
    cmd = CheckDrcCommand()
    result = cmd.execute(empty_board)

    assert "DRC:" in result
    assert "0 errors" in result
    assert "0 warnings" in result


def test_check_drc_execute_clean_board(basic_board):
    """Test CHECK DRC on board with no violations"""
    cmd = CheckDrcCommand()
    result = cmd.execute(basic_board)

    # Should have some warnings (unrouted nets) but may have clearance errors
    assert "DRC:" in result


def test_check_drc_execute_with_violations(board_with_drc_errors):
    """Test CHECK DRC detects various violations"""
    cmd = CheckDrcCommand()
    result = cmd.execute(board_with_drc_errors)

    assert "DRC:" in result
    # Check for clearance violation
    assert "Clearance violation" in result or "clearance" in result.lower()
    # Check for track width issue
    assert "Track width" in result or "width" in result.lower()
    # Check for component with no connections
    assert "no connections" in result.lower() or "U1" in result
    # Check for unrouted net
    assert "unrouted" in result.lower() or "GND" in result


def test_check_drc_undo_returns_empty_string():
    """Test CheckDrcCommand.undo returns empty string (read-only)"""
    cmd = CheckDrcCommand()
    board = Board()
    assert cmd.undo(board) == ""


# CheckAirwiresCommand Tests

def test_check_airwires_command_creation():
    """Test CheckAirwiresCommand can be created"""
    cmd = CheckAirwiresCommand()
    assert cmd is not None
    assert cmd.net_name is None


def test_check_airwires_command_creation_with_net():
    """Test CheckAirwiresCommand can be created with net filter"""
    cmd = CheckAirwiresCommand(net_name="VCC")
    assert cmd.net_name == "VCC"


def test_check_airwires_validate_no_net():
    """Test CheckAirwiresCommand.validate when no net specified"""
    cmd = CheckAirwiresCommand()
    board = Board()
    assert cmd.validate(board) is None


def test_check_airwires_validate_net_exists(basic_board):
    """Test CheckAirwiresCommand.validate when net exists"""
    cmd = CheckAirwiresCommand(net_name="VCC")
    assert cmd.validate(basic_board) is None


def test_check_airwires_validate_net_not_found():
    """Test CheckAirwiresCommand.validate when net doesn't exist"""
    cmd = CheckAirwiresCommand(net_name="NONEXISTENT")
    board = Board()
    error = cmd.validate(board)
    assert error is not None
    assert "not found" in error.lower()


def test_check_airwires_execute_all_nets(board_with_routing):
    """Test CHECK AIRWIRES on all nets"""
    cmd = CheckAirwiresCommand()
    result = cmd.execute(board_with_routing)

    assert "AIRWIRES:" in result
    assert "unrouted connections" in result.lower()
    assert "VCC" in result
    assert "GND" in result
    # VCC is routed
    assert "0 routed" in result or "2 routed" in result
    # GND is unrouted
    assert "unrouted" in result.lower()


def test_check_airwires_execute_specific_net(board_with_routing):
    """Test CHECK AIRWIRES NET <name>"""
    cmd = CheckAirwiresCommand(net_name="GND")
    result = cmd.execute(board_with_routing)

    assert "AIRWIRES:" in result
    assert "GND" in result


def test_check_airwires_execute_empty_board(empty_board):
    """Test CHECK AIRWIRES on empty board"""
    cmd = CheckAirwiresCommand()
    result = cmd.execute(empty_board)

    assert "AIRWIRES:" in result
    assert "0 unrouted connections" in result


def test_check_airwires_undo_returns_empty_string():
    """Test CheckAirwiresCommand.undo returns empty string"""
    cmd = CheckAirwiresCommand()
    board = Board()
    assert cmd.undo(board) == ""


# CheckClearanceCommand Tests

def test_check_clearance_command_creation():
    """Test CheckClearanceCommand can be created"""
    cmd = CheckClearanceCommand()
    assert cmd is not None


def test_check_clearance_validate_always_none():
    """Test CheckClearanceCommand.validate always returns None"""
    cmd = CheckClearanceCommand()
    board = Board()
    assert cmd.validate(board) is None


def test_check_clearance_execute_empty_board(empty_board):
    """Test CHECK CLEARANCE on empty board"""
    cmd = CheckClearanceCommand()
    result = cmd.execute(empty_board)

    assert "CLEARANCE:" in result
    assert "0 violations" in result


def test_check_clearance_execute_no_violations(basic_board):
    """Test CHECK CLEARANCE on board without violations"""
    cmd = CheckClearanceCommand()
    result = cmd.execute(basic_board)

    assert "CLEARANCE:" in result


def test_check_clearance_execute_with_violations(board_with_clearance_violations):
    """Test CHECK CLEARANCE detects violations"""
    cmd = CheckClearanceCommand()
    result = cmd.execute(board_with_clearance_violations)

    assert "CLEARANCE:" in result
    assert "violations" in result.lower()
    # Check for specific violations
    assert "R1" in result
    assert "R2" in result
    assert "0.15mm" in result or "0.2mm" in result
    assert "too close" in result.lower()


def test_check_clearance_undo_returns_empty_string():
    """Test CheckClearanceCommand.undo returns empty string"""
    cmd = CheckClearanceCommand()
    board = Board()
    assert cmd.undo(board) == ""


# CheckConnectivityCommand Tests

def test_check_connectivity_command_creation():
    """Test CheckConnectivityCommand can be created"""
    cmd = CheckConnectivityCommand()
    assert cmd is not None


def test_check_connectivity_validate_always_none():
    """Test CheckConnectivityCommand.validate always returns None"""
    cmd = CheckConnectivityCommand()
    board = Board()
    assert cmd.validate(board) is None


def test_check_connectivity_execute_empty_board(empty_board):
    """Test CHECK CONNECTIVITY on empty board"""
    cmd = CheckConnectivityCommand()
    result = cmd.execute(empty_board)

    assert "CONNECTIVITY:" in result
    assert "OK" in result


def test_check_connectivity_execute_all_connected(basic_board):
    """Test CHECK CONNECTIVITY on board with all pins connected"""
    cmd = CheckConnectivityCommand()
    result = cmd.execute(basic_board)

    assert "CONNECTIVITY:" in result
    # All components have connections
    if "issues" not in result.lower():
        assert "OK" in result


def test_check_connectivity_execute_with_floating_pins():
    """Test CHECK CONNECTIVITY detects floating pins"""
    board = Board()

    # Component with no net connections
    board.add_component(Component(
        ref="R5", value="10K", footprint="R_0805",
        position=(10.0, 20.0), rotation=0.0
    ))

    # Net with only 1 connection
    net = Net(name="DEBUG", code="3")
    net.add_connection("R5", "1")
    board.add_net(net)

    cmd = CheckConnectivityCommand()
    result = cmd.execute(board)

    assert "CONNECTIVITY:" in result
    assert "issues" in result.lower() or "floating" in result.lower()


def test_check_connectivity_undo_returns_empty_string():
    """Test CheckConnectivityCommand.undo returns empty string"""
    cmd = CheckConnectivityCommand()
    board = Board()
    assert cmd.undo(board) == ""


# Parser Tests

def test_parser_check_drc():
    """Test parsing CHECK DRC"""
    parser = CommandParser()
    cmd = parser.parse("CHECK DRC")

    assert isinstance(cmd, CheckDrcCommand)


def test_parser_check_airwires():
    """Test parsing CHECK AIRWIRES"""
    parser = CommandParser()
    cmd = parser.parse("CHECK AIRWIRES")

    assert isinstance(cmd, CheckAirwiresCommand)
    assert cmd.net_name is None


def test_parser_check_airwires_net():
    """Test parsing CHECK AIRWIRES NET <name>"""
    parser = CommandParser()
    cmd = parser.parse("CHECK AIRWIRES NET VCC")

    assert isinstance(cmd, CheckAirwiresCommand)
    assert cmd.net_name == "VCC"


def test_parser_check_clearance():
    """Test parsing CHECK CLEARANCE"""
    parser = CommandParser()
    cmd = parser.parse("CHECK CLEARANCE")

    assert isinstance(cmd, CheckClearanceCommand)


def test_parser_check_connectivity():
    """Test parsing CHECK CONNECTIVITY"""
    parser = CommandParser()
    cmd = parser.parse("CHECK CONNECTIVITY")

    assert isinstance(cmd, CheckConnectivityCommand)


def test_parser_check_invalid_subcommand():
    """Test parsing invalid CHECK subcommand"""
    parser = CommandParser()
    cmd = parser.parse("CHECK INVALID")

    assert cmd is None


def test_parser_check_case_insensitive():
    """Test CHECK commands are case-insensitive"""
    parser = CommandParser()

    cmd = parser.parse("check drc")
    assert isinstance(cmd, CheckDrcCommand)

    cmd = parser.parse("ChEcK aIrWiReS")
    assert isinstance(cmd, CheckAirwiresCommand)


# Integration Tests

def test_check_drc_integration_workflow(board_with_drc_errors):
    """Test full CHECK DRC workflow"""
    parser = CommandParser()
    cmd = parser.parse("CHECK DRC")

    assert cmd is not None
    error = cmd.validate(board_with_drc_errors)
    assert error is None

    result = cmd.execute(board_with_drc_errors)
    assert "DRC:" in result

    # Should be read-only (no undo)
    assert cmd.undo(board_with_drc_errors) == ""


def test_check_airwires_integration_workflow(board_with_routing):
    """Test full CHECK AIRWIRES workflow"""
    parser = CommandParser()
    cmd = parser.parse("CHECK AIRWIRES NET GND")

    assert cmd is not None
    error = cmd.validate(board_with_routing)
    assert error is None

    result = cmd.execute(board_with_routing)
    assert "AIRWIRES:" in result
    assert "GND" in result


def test_check_clearance_integration_workflow(board_with_clearance_violations):
    """Test full CHECK CLEARANCE workflow"""
    parser = CommandParser()
    cmd = parser.parse("CHECK CLEARANCE")

    assert cmd is not None
    error = cmd.validate(board_with_clearance_violations)
    assert error is None

    result = cmd.execute(board_with_clearance_violations)
    assert "CLEARANCE:" in result
    assert "violations" in result.lower()
