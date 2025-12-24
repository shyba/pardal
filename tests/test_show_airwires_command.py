# tests/test_show_airwires_command.py
import pytest
from pcb_tool.commands import ShowAirwiresCommand
from pcb_tool.command_parser import CommandParser
from pcb_tool.data_model import Board, Component, Net, TraceSegment


@pytest.fixture
def sample_board():
    """Create a sample board with mixed routed and unrouted nets."""
    board = Board()

    # Add components
    board.add_component(Component(
        ref="U1", value="IC", footprint="DIP-8",
        position=(10.0, 20.0), rotation=0.0
    ))
    board.add_component(Component(
        ref="R1", value="10k", footprint="R_0805",
        position=(30.0, 40.0), rotation=0.0
    ))
    board.add_component(Component(
        ref="R2", value="10k", footprint="R_0805",
        position=(50.0, 40.0), rotation=0.0
    ))
    board.add_component(Component(
        ref="C1", value="100nF", footprint="C_0805",
        position=(70.0, 20.0), rotation=0.0
    ))

    # VCC net - completely unrouted (4 connections, 0 segments)
    vcc_net = Net(name="VCC", code="1")
    vcc_net.add_connection("U1", "8")
    vcc_net.add_connection("R1", "1")
    vcc_net.add_connection("R2", "1")
    vcc_net.add_connection("C1", "1")
    board.add_net(vcc_net)

    # GND net - partially routed (3 connections, has some segments)
    gnd_net = Net(name="GND", code="2")
    gnd_net.add_connection("U1", "4")
    gnd_net.add_connection("R1", "2")
    gnd_net.add_connection("C1", "2")
    # Add some routing
    gnd_net.add_segment(TraceSegment(
        net_name="GND",
        start=(10.0, 20.0),
        end=(30.0, 40.0),
        layer="F.Cu",
        width=0.25
    ))
    board.add_net(gnd_net)

    # /LED net - fully routed (2 connections, has segments)
    led_net = Net(name="/LED", code="3")
    led_net.add_connection("R2", "2")
    led_net.add_connection("U1", "5")
    led_net.add_segment(TraceSegment(
        net_name="/LED",
        start=(50.0, 40.0),
        end=(10.0, 20.0),
        layer="F.Cu",
        width=0.25
    ))
    board.add_net(led_net)

    return board


def test_show_airwires_command_creation_without_filter():
    """Test ShowAirwiresCommand can be created without filter."""
    cmd = ShowAirwiresCommand()
    assert cmd.net_name is None


def test_show_airwires_command_creation_with_filter():
    """Test ShowAirwiresCommand can be created with net filter."""
    cmd = ShowAirwiresCommand("VCC")
    assert cmd.net_name == "VCC"


def test_show_airwires_command_validate_no_filter(sample_board):
    """Test validation succeeds when no filter is specified."""
    cmd = ShowAirwiresCommand()
    error = cmd.validate(sample_board)
    assert error is None


def test_show_airwires_command_validate_with_valid_filter(sample_board):
    """Test validation succeeds when valid net filter is specified."""
    cmd = ShowAirwiresCommand("VCC")
    error = cmd.validate(sample_board)
    assert error is None


def test_show_airwires_command_validate_net_not_found():
    """Test validation fails when filtered net doesn't exist."""
    cmd = ShowAirwiresCommand("NONEXISTENT")
    board = Board()
    error = cmd.validate(board)
    assert error is not None
    assert "not found" in error.lower()


def test_show_airwires_command_execute_all_nets(sample_board):
    """Test execute shows all unrouted connections across all nets."""
    cmd = ShowAirwiresCommand()
    result = cmd.execute(sample_board)

    # Header should show total unrouted connections
    # VCC has 4 connections unrouted, GND and /LED are routed (0 unrouted)
    assert "AIRWIRES: 4 unrouted connections" in result

    # Should list all nets with their status
    assert 'NET "VCC"' in result
    assert "4 connections" in result
    assert "0 routed" in result

    assert 'NET "GND"' in result
    assert "3 connections" in result

    assert 'NET "/LED"' in result or 'NET "/LED"' in result
    assert "2 connections" in result


def test_show_airwires_command_execute_with_filter(sample_board):
    """Test execute shows only filtered net."""
    cmd = ShowAirwiresCommand("VCC")
    result = cmd.execute(sample_board)

    # Should show VCC net
    assert 'NET "VCC"' in result
    assert "4 connections" in result
    assert "0 routed" in result

    # Should NOT show other nets
    assert 'NET "GND"' not in result or result.count('NET "') == 1


def test_show_airwires_command_execute_shows_routed_status(sample_board):
    """Test execute distinguishes between routed and unrouted nets."""
    cmd = ShowAirwiresCommand()
    result = cmd.execute(sample_board)

    # Nets with segments should be marked as routed
    assert 'NET "GND"' in result
    assert 'NET "/LED"' in result


def test_show_airwires_command_undo_returns_empty(sample_board):
    """Test undo returns empty string (read-only command)."""
    cmd = ShowAirwiresCommand()
    result = cmd.undo(sample_board)
    assert result == ""


def test_parser_can_parse_show_airwires_without_filter():
    """Test parser can parse SHOW AIRWIRES without filter."""
    parser = CommandParser()
    cmd = parser.parse("SHOW AIRWIRES")

    assert isinstance(cmd, ShowAirwiresCommand)
    assert cmd.net_name is None


def test_parser_can_parse_show_airwires_with_filter():
    """Test parser can parse SHOW AIRWIRES NET <name>."""
    parser = CommandParser()
    cmd = parser.parse("SHOW AIRWIRES NET VCC")

    assert isinstance(cmd, ShowAirwiresCommand)
    assert cmd.net_name == "VCC"


def test_parser_show_airwires_with_quoted_filter():
    """Test parser can parse SHOW AIRWIRES with quoted net name."""
    parser = CommandParser()
    cmd = parser.parse('SHOW AIRWIRES NET "VCC"')

    assert isinstance(cmd, ShowAirwiresCommand)
    assert cmd.net_name == "VCC"


def test_show_airwires_command_full_workflow(sample_board):
    """Test full workflow from parsing to execution."""
    parser = CommandParser()
    cmd = parser.parse("SHOW AIRWIRES")

    assert cmd.validate(sample_board) is None
    result = cmd.execute(sample_board)

    assert "AIRWIRES:" in result
    assert "unrouted connections" in result


def test_show_airwires_command_no_connections():
    """Test execute handles board with no connections."""
    board = Board()
    net = Net(name="VCC", code="1")
    board.add_net(net)

    cmd = ShowAirwiresCommand()
    result = cmd.execute(board)

    assert "AIRWIRES: 0 unrouted connections" in result
