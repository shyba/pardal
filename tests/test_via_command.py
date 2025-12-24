import pytest
from pcb_tool.commands import ViaCommand
from pcb_tool.command_parser import CommandParser
from pcb_tool.data_model import Board, Net, Via


@pytest.fixture
def sample_board():
    """Create a board with test nets."""
    board = Board()
    net1 = Net(name="GND", code="1", via_size=0.8, via_drill=0.4)
    net2 = Net(name="VCC", code="2", via_size=1.0, via_drill=0.6)
    net3 = Net(name="signal with spaces", code="3", via_size=0.8, via_drill=0.4)
    board.add_net(net1)
    board.add_net(net2)
    board.add_net(net3)
    return board


def test_via_command_creation_basic():
    """Test creating ViaCommand with minimal parameters."""
    cmd = ViaCommand("GND", (50.0, 60.0))
    assert cmd.net_name == "GND"
    assert cmd.position == (50.0, 60.0)
    assert cmd.size is None
    assert cmd.drill is None


def test_via_command_creation_with_all_params():
    """Test creating ViaCommand with all parameters."""
    cmd = ViaCommand("VCC", (10.0, 20.0), size=1.0, drill=0.5)
    assert cmd.net_name == "VCC"
    assert cmd.position == (10.0, 20.0)
    assert cmd.size == 1.0
    assert cmd.drill == 0.5


def test_via_command_validate_net_not_found():
    """Test validation fails when net doesn't exist."""
    cmd = ViaCommand("NONEXISTENT", (50.0, 60.0))
    board = Board()
    error = cmd.validate(board)
    assert error is not None
    assert "ERROR:" in error
    assert "not found" in error.lower()
    assert "NONEXISTENT" in error


def test_via_command_validate_size_too_small():
    """Test validation fails when size is below minimum."""
    cmd = ViaCommand("GND", (50.0, 60.0), size=0.3)
    board = Board()
    board.add_net(Net(name="GND", code="1"))
    error = cmd.validate(board)
    assert error is not None
    assert "ERROR:" in error
    assert "size" in error.lower() or "minimum" in error.lower()
    assert "0.3" in error


def test_via_command_validate_drill_too_large():
    """Test validation fails when drill >= size."""
    cmd = ViaCommand("GND", (50.0, 60.0), size=0.8, drill=0.8)
    board = Board()
    board.add_net(Net(name="GND", code="1"))
    error = cmd.validate(board)
    assert error is not None
    assert "ERROR:" in error
    assert "drill" in error.lower()
    assert "0.8" in error


def test_via_command_validate_drill_larger_than_size():
    """Test validation fails when drill > size."""
    cmd = ViaCommand("GND", (50.0, 60.0), size=0.6, drill=0.7)
    board = Board()
    board.add_net(Net(name="GND", code="1"))
    error = cmd.validate(board)
    assert error is not None
    assert "ERROR:" in error
    assert "drill" in error.lower()


def test_via_command_validate_success(sample_board):
    """Test validation succeeds with valid parameters."""
    cmd = ViaCommand("GND", (50.0, 60.0))
    error = cmd.validate(sample_board)
    assert error is None


def test_via_command_validate_success_with_size(sample_board):
    """Test validation succeeds with custom size and drill."""
    cmd = ViaCommand("GND", (50.0, 60.0), size=1.0, drill=0.5)
    error = cmd.validate(sample_board)
    assert error is None


def test_via_command_execute(sample_board):
    """Test executing via command adds via to net."""
    cmd = ViaCommand("GND", (50.0, 60.0))
    result = cmd.execute(sample_board)

    assert "OK:" in result
    assert "GND" in result
    assert "50" in result or "50.0" in result

    # Verify via was added
    net = sample_board.nets["GND"]
    assert len(net.vias) == 1
    via = net.vias[0]
    assert via.position == (50.0, 60.0)
    assert via.size == 0.8  # Default from net
    assert via.drill == 0.4  # Default from net
    assert via.layers == ("F.Cu", "B.Cu")


def test_via_command_execute_with_custom_size(sample_board):
    """Test executing with custom size and drill."""
    cmd = ViaCommand("VCC", (25.0, 35.0), size=1.2, drill=0.6)
    cmd.execute(sample_board)

    net = sample_board.nets["VCC"]
    via = net.vias[0]
    assert via.size == 1.2
    assert via.drill == 0.6


def test_via_command_undo(sample_board):
    """Test undo removes the via."""
    cmd = ViaCommand("GND", (50.0, 60.0))
    cmd.execute(sample_board)

    net = sample_board.nets["GND"]
    assert len(net.vias) == 1

    result = cmd.undo(sample_board)
    assert "OK:" in result
    assert len(net.vias) == 0


def test_parser_can_parse_via_basic():
    """Test parser handles basic VIA command."""
    parser = CommandParser()
    cmd = parser.parse("VIA NET GND AT 50 60")

    assert isinstance(cmd, ViaCommand)
    assert cmd.net_name == "GND"
    assert cmd.position == (50.0, 60.0)
    assert cmd.size is None
    assert cmd.drill is None


def test_parser_can_parse_via_with_size():
    """Test parser handles VIA with SIZE parameter."""
    parser = CommandParser()
    cmd = parser.parse("VIA NET VCC AT 10 20 SIZE 1.0")

    assert isinstance(cmd, ViaCommand)
    assert cmd.net_name == "VCC"
    assert cmd.position == (10.0, 20.0)
    assert cmd.size == 1.0
    assert cmd.drill is None


def test_parser_can_parse_via_with_drill():
    """Test parser handles VIA with DRILL parameter."""
    parser = CommandParser()
    cmd = parser.parse("VIA NET GND AT 30 40 DRILL 0.5")

    assert isinstance(cmd, ViaCommand)
    assert cmd.drill == 0.5


def test_parser_can_parse_via_with_all_params():
    """Test parser handles VIA with all optional parameters."""
    parser = CommandParser()
    cmd = parser.parse("VIA NET signal AT 5 10 SIZE 1.2 DRILL 0.6")

    assert isinstance(cmd, ViaCommand)
    assert cmd.net_name == "signal"
    assert cmd.position == (5.0, 10.0)
    assert cmd.size == 1.2
    assert cmd.drill == 0.6


def test_parser_can_parse_via_quoted_name():
    """Test parser handles quoted net names."""
    parser = CommandParser()
    cmd = parser.parse('VIA NET "signal with spaces" AT 50 60')

    assert isinstance(cmd, ViaCommand)
    assert cmd.net_name == "signal with spaces"


def test_via_command_full_workflow(sample_board):
    """Test complete workflow: parse, validate, execute."""
    parser = CommandParser()
    cmd = parser.parse("VIA NET GND AT 100 100 SIZE 1.0 DRILL 0.5")

    assert cmd is not None
    assert cmd.validate(sample_board) is None

    result = cmd.execute(sample_board)
    assert "OK:" in result

    net = sample_board.nets["GND"]
    assert len(net.vias) == 1
    assert net.vias[0].position == (100.0, 100.0)
    assert net.vias[0].size == 1.0
    assert net.vias[0].drill == 0.5


def test_via_command_multiple_vias(sample_board):
    """Test adding multiple vias to same net."""
    cmd1 = ViaCommand("GND", (10.0, 10.0))
    cmd2 = ViaCommand("GND", (20.0, 20.0))
    cmd3 = ViaCommand("GND", (30.0, 30.0))

    cmd1.execute(sample_board)
    cmd2.execute(sample_board)
    cmd3.execute(sample_board)

    net = sample_board.nets["GND"]
    assert len(net.vias) == 3
