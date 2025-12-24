import pytest
from pcb_tool.commands import RouteCommand
from pcb_tool.command_parser import CommandParser
from pcb_tool.data_model import Board, Net, TraceSegment


@pytest.fixture
def sample_board():
    """Create a board with test nets."""
    board = Board()
    net1 = Net(name="GND", code="1", track_width=0.25)
    net2 = Net(name="VCC", code="2", track_width=0.5)
    net3 = Net(name="signal with spaces", code="3", track_width=0.3)
    board.add_net(net1)
    board.add_net(net2)
    board.add_net(net3)
    return board


def test_route_command_creation_basic():
    """Test creating RouteCommand with minimal parameters."""
    cmd = RouteCommand("GND", (10.0, 20.0), (30.0, 40.0))
    assert cmd.net_name == "GND"
    assert cmd.start_pos == (10.0, 20.0)
    assert cmd.end_pos == (30.0, 40.0)
    assert cmd.layer == "F.Cu"
    assert cmd.width is None


def test_route_command_creation_with_all_params():
    """Test creating RouteCommand with all parameters."""
    cmd = RouteCommand("VCC", (5.0, 10.0), (15.0, 20.0), layer="B.Cu", width=0.5)
    assert cmd.net_name == "VCC"
    assert cmd.start_pos == (5.0, 10.0)
    assert cmd.end_pos == (15.0, 20.0)
    assert cmd.layer == "B.Cu"
    assert cmd.width == 0.5


def test_route_command_validate_net_not_found():
    """Test validation fails when net doesn't exist."""
    cmd = RouteCommand("NONEXISTENT", (0.0, 0.0), (10.0, 10.0))
    board = Board()
    error = cmd.validate(board)
    assert error is not None
    assert "ERROR:" in error
    assert "not found" in error.lower()
    assert "NONEXISTENT" in error


def test_route_command_validate_invalid_layer():
    """Test validation fails with invalid layer."""
    cmd = RouteCommand("GND", (0.0, 0.0), (10.0, 10.0), layer="Invalid.Cu")
    board = Board()
    board.add_net(Net(name="GND", code="1"))
    error = cmd.validate(board)
    assert error is not None
    assert "ERROR:" in error
    assert "layer" in error.lower()
    assert "Invalid.Cu" in error


def test_route_command_validate_width_too_small():
    """Test validation fails when width is below minimum."""
    cmd = RouteCommand("GND", (0.0, 0.0), (10.0, 10.0), width=0.05)
    board = Board()
    board.add_net(Net(name="GND", code="1"))
    error = cmd.validate(board)
    assert error is not None
    assert "ERROR:" in error
    assert "width" in error.lower() or "minimum" in error.lower()
    assert "0.05" in error


def test_route_command_validate_success(sample_board):
    """Test validation succeeds with valid parameters."""
    cmd = RouteCommand("GND", (0.0, 0.0), (10.0, 10.0))
    error = cmd.validate(sample_board)
    assert error is None


def test_route_command_execute(sample_board):
    """Test executing route command adds segment to net."""
    cmd = RouteCommand("GND", (10.0, 20.0), (30.0, 40.0))
    result = cmd.execute(sample_board)

    assert "OK:" in result
    assert "GND" in result
    assert "(10" in result or "10.0" in result

    # Verify segment was added
    net = sample_board.nets["GND"]
    assert len(net.segments) == 1
    segment = net.segments[0]
    assert segment.start == (10.0, 20.0)
    assert segment.end == (30.0, 40.0)
    assert segment.layer == "F.Cu"
    assert segment.width == 0.25  # Default from net


def test_route_command_execute_with_custom_width(sample_board):
    """Test executing with custom width."""
    cmd = RouteCommand("GND", (5.0, 5.0), (15.0, 15.0), width=0.5)
    cmd.execute(sample_board)

    net = sample_board.nets["GND"]
    segment = net.segments[0]
    assert segment.width == 0.5


def test_route_command_execute_back_layer(sample_board):
    """Test executing on back layer."""
    cmd = RouteCommand("VCC", (0.0, 0.0), (50.0, 50.0), layer="B.Cu")
    cmd.execute(sample_board)

    net = sample_board.nets["VCC"]
    segment = net.segments[0]
    assert segment.layer == "B.Cu"


def test_route_command_undo(sample_board):
    """Test undo removes the segment."""
    cmd = RouteCommand("GND", (10.0, 10.0), (20.0, 20.0))
    cmd.execute(sample_board)

    net = sample_board.nets["GND"]
    assert len(net.segments) == 1

    result = cmd.undo(sample_board)
    assert "OK:" in result
    assert len(net.segments) == 0


def test_parser_can_parse_route_basic():
    """Test parser handles basic ROUTE command."""
    parser = CommandParser()
    cmd = parser.parse("ROUTE NET GND FROM 10 20 TO 30 40")

    assert isinstance(cmd, RouteCommand)
    assert cmd.net_name == "GND"
    assert cmd.start_pos == (10.0, 20.0)
    assert cmd.end_pos == (30.0, 40.0)
    assert cmd.layer == "F.Cu"
    assert cmd.width is None


def test_parser_can_parse_route_with_layer():
    """Test parser handles ROUTE with LAYER parameter."""
    parser = CommandParser()
    cmd = parser.parse("ROUTE NET VCC FROM 0 0 TO 50 50 LAYER B.Cu")

    assert isinstance(cmd, RouteCommand)
    assert cmd.net_name == "VCC"
    assert cmd.layer == "B.Cu"


def test_parser_can_parse_route_with_width():
    """Test parser handles ROUTE with WIDTH parameter."""
    parser = CommandParser()
    cmd = parser.parse("ROUTE NET GND FROM 5 10 TO 15 20 WIDTH 0.5")

    assert isinstance(cmd, RouteCommand)
    assert cmd.net_name == "GND"
    assert cmd.width == 0.5


def test_parser_can_parse_route_with_all_params():
    """Test parser handles ROUTE with all optional parameters."""
    parser = CommandParser()
    cmd = parser.parse("ROUTE NET signal FROM 1 2 TO 3 4 LAYER B.Cu WIDTH 0.75")

    assert isinstance(cmd, RouteCommand)
    assert cmd.net_name == "signal"
    assert cmd.start_pos == (1.0, 2.0)
    assert cmd.end_pos == (3.0, 4.0)
    assert cmd.layer == "B.Cu"
    assert cmd.width == 0.75


def test_parser_can_parse_route_quoted_name():
    """Test parser handles quoted net names."""
    parser = CommandParser()
    cmd = parser.parse('ROUTE NET "signal with spaces" FROM 10 20 TO 30 40')

    assert isinstance(cmd, RouteCommand)
    assert cmd.net_name == "signal with spaces"


def test_route_command_full_workflow(sample_board):
    """Test complete workflow: parse, validate, execute."""
    parser = CommandParser()
    cmd = parser.parse("ROUTE NET GND FROM 0 0 TO 100 100 LAYER F.Cu WIDTH 0.3")

    assert cmd is not None
    assert cmd.validate(sample_board) is None

    result = cmd.execute(sample_board)
    assert "OK:" in result

    net = sample_board.nets["GND"]
    assert len(net.segments) == 1
    assert net.segments[0].start == (0.0, 0.0)
    assert net.segments[0].end == (100.0, 100.0)
    assert net.segments[0].width == 0.3


def test_route_command_multiple_segments(sample_board):
    """Test adding multiple segments to same net."""
    cmd1 = RouteCommand("GND", (0.0, 0.0), (10.0, 0.0))
    cmd2 = RouteCommand("GND", (10.0, 0.0), (10.0, 10.0))
    cmd3 = RouteCommand("GND", (10.0, 10.0), (20.0, 10.0))

    cmd1.execute(sample_board)
    cmd2.execute(sample_board)
    cmd3.execute(sample_board)

    net = sample_board.nets["GND"]
    assert len(net.segments) == 3
