# tests/test_show_net_command.py
import pytest
from pcb_tool.commands import ShowNetCommand
from pcb_tool.command_parser import CommandParser
from pcb_tool.data_model import Board, Component, Net, TraceSegment, Via


@pytest.fixture
def sample_board():
    """Create a sample board with nets, connections, routing, and vias."""
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

    # Add VCC net with connections and routing
    vcc_net = Net(name="VCC", code="1")
    vcc_net.add_connection("U1", "8")
    vcc_net.add_connection("R1", "1")
    vcc_net.add_connection("R2", "1")
    vcc_net.add_connection("C1", "1")

    # Add segments to VCC
    vcc_net.add_segment(TraceSegment(
        net_name="VCC",
        start=(10.0, 20.0),
        end=(30.0, 40.0),
        layer="F.Cu",
        width=0.25
    ))
    vcc_net.add_segment(TraceSegment(
        net_name="VCC",
        start=(30.0, 40.0),
        end=(50.0, 40.0),
        layer="F.Cu",
        width=0.25
    ))

    # Add via to VCC
    vcc_net.add_via(Via(
        net_name="VCC",
        position=(30.0, 40.0),
        size=0.8,
        drill=0.4,
        layers=("F.Cu", "B.Cu")
    ))

    board.add_net(vcc_net)

    # Add GND net with connections but no routing
    gnd_net = Net(name="GND", code="2")
    gnd_net.add_connection("U1", "4")
    gnd_net.add_connection("R1", "2")
    gnd_net.add_connection("C1", "2")
    board.add_net(gnd_net)

    return board


def test_show_net_command_creation():
    """Test ShowNetCommand can be created with net name."""
    cmd = ShowNetCommand("VCC")
    assert cmd.net_name == "VCC"


def test_show_net_command_validate_net_not_found():
    """Test validation fails when net doesn't exist."""
    cmd = ShowNetCommand("NONEXISTENT")
    board = Board()
    error = cmd.validate(board)
    assert error is not None
    assert "not found" in error.lower()


def test_show_net_command_validate_success(sample_board):
    """Test validation succeeds for existing net."""
    cmd = ShowNetCommand("VCC")
    error = cmd.validate(sample_board)
    assert error is None


def test_show_net_command_execute_with_connections_only(sample_board):
    """Test execute shows connections for net with no routing."""
    cmd = ShowNetCommand("GND")
    result = cmd.execute(sample_board)

    # Check for net header
    assert 'NET "GND"' in result
    assert "(code 2)" in result

    # Check for connections section
    assert "Connections: 3" in result
    assert "U1.4" in result
    assert "R1.2" in result
    assert "C1.2" in result

    # Should not show routing section for unrouted net
    assert "Segments: 0" in result or "no routed segments" in result.lower()


def test_show_net_command_execute_with_routing(sample_board):
    """Test execute shows connections, segments, and vias for routed net."""
    cmd = ShowNetCommand("VCC")
    result = cmd.execute(sample_board)

    # Check for net header
    assert 'NET "VCC"' in result
    assert "(code 1)" in result

    # Check for connections
    assert "Connections: 4" in result
    assert "U1.8" in result
    assert "R1.1" in result

    # Check for routing section
    assert "Segments: 2" in result
    assert "(10.0, 20.0)" in result
    assert "(30.0, 40.0)" in result
    assert "(50.0, 40.0)" in result
    assert "[F.Cu" in result
    assert "0.25mm" in result

    # Check for vias
    assert "Vias: 1" in result
    assert "[0.8mm, drill 0.4mm]" in result


def test_show_net_command_undo_returns_empty(sample_board):
    """Test undo returns empty string (read-only command)."""
    cmd = ShowNetCommand("VCC")
    result = cmd.undo(sample_board)
    assert result == ""


def test_parser_can_parse_show_net_command():
    """Test parser can parse SHOW NET command."""
    parser = CommandParser()
    cmd = parser.parse("SHOW NET VCC")

    assert isinstance(cmd, ShowNetCommand)
    assert cmd.net_name == "VCC"


def test_parser_show_net_with_quoted_name():
    """Test parser can parse SHOW NET with quoted net name."""
    parser = CommandParser()
    cmd = parser.parse('SHOW NET "VCC"')

    assert isinstance(cmd, ShowNetCommand)
    assert cmd.net_name == "VCC"


def test_show_net_command_full_workflow(sample_board):
    """Test full workflow from parsing to execution."""
    parser = CommandParser()
    cmd = parser.parse("SHOW NET VCC")

    assert cmd.validate(sample_board) is None
    result = cmd.execute(sample_board)

    assert 'NET "VCC"' in result
    assert "Connections: 4" in result
    assert "Segments: 2" in result
    assert "Vias: 1" in result


def test_show_net_command_with_multiple_vias():
    """Test execute shows multiple vias correctly."""
    board = Board()

    # Create net with multiple vias
    net = Net(name="GND", code="1")
    net.add_connection("U1", "1")
    net.add_connection("U2", "1")

    net.add_via(Via("GND", (10.0, 10.0), 0.8, 0.4, ("F.Cu", "B.Cu")))
    net.add_via(Via("GND", (20.0, 20.0), 1.0, 0.5, ("F.Cu", "B.Cu")))
    net.add_via(Via("GND", (30.0, 30.0), 0.8, 0.4, ("F.Cu", "B.Cu")))

    board.add_net(net)

    cmd = ShowNetCommand("GND")
    result = cmd.execute(board)

    assert "Vias: 3" in result
    assert "(10.0, 10.0)" in result
    assert "(20.0, 20.0)" in result
    assert "(30.0, 30.0)" in result
