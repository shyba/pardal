import pytest
from pathlib import Path
from pcb_tool.commands import LoadCommand
from pcb_tool.command_parser import CommandParser
from pcb_tool.data_model import Board

# Sample netlist for testing
SAMPLE_NETLIST = '''(export (version D)
  (components
    (comp (ref U1)
      (value ATmega328P)
      (footprint Package_DIP:DIP-28_W7.62mm))
    (comp (ref R1)
      (value 10k)
      (footprint Resistor_SMD:R_0805_2012Metric)))
  (nets
    (net (code 1) (name GND)
      (node (ref U1) (pin 8))
      (node (ref R1) (pin 2)))))
'''

@pytest.fixture
def sample_netlist_file(tmp_path):
    """Create temporary netlist file"""
    netlist = tmp_path / "test.net"
    netlist.write_text(SAMPLE_NETLIST)
    return netlist

def test_load_command_creation():
    """Test LoadCommand can be instantiated with path"""
    cmd = LoadCommand(Path("test.net"))
    assert cmd.path == Path("test.net")

def test_load_command_validate_file_not_found():
    """Test validation fails for nonexistent file"""
    cmd = LoadCommand(Path("/nonexistent/file.net"))
    board = Board()

    error = cmd.validate(board)

    assert error is not None
    assert "not found" in error.lower() or "does not exist" in error.lower()

def test_load_command_validate_success(sample_netlist_file):
    """Test validation succeeds for existing file"""
    cmd = LoadCommand(sample_netlist_file)
    board = Board()

    error = cmd.validate(board)

    assert error is None

def test_load_command_execute_loads_board(sample_netlist_file):
    """Test execute loads components and nets into board"""
    cmd = LoadCommand(sample_netlist_file)
    board = Board()

    result = cmd.execute(board)

    assert "OK" in result or "Loaded" in result
    assert len(board.components) == 2
    assert len(board.nets) == 1
    assert "U1" in board.components
    assert "R1" in board.components
    assert "GND" in board.nets

def test_load_command_execute_returns_stats(sample_netlist_file):
    """Test execute returns component/net counts"""
    cmd = LoadCommand(sample_netlist_file)
    board = Board()

    result = cmd.execute(board)

    assert "2" in result  # 2 components
    assert "1" in result  # 1 net

def test_parser_can_parse_load_command(sample_netlist_file):
    """Test CommandParser can parse LOAD command"""
    parser = CommandParser()

    cmd = parser.parse(f"LOAD {sample_netlist_file}")

    assert isinstance(cmd, LoadCommand)
    assert cmd.path == sample_netlist_file

def test_parser_handles_load_without_path():
    """Test parser handles LOAD without path gracefully"""
    parser = CommandParser()

    cmd = parser.parse("LOAD")

    # Should return None or a LoadCommand that will fail validation
    if cmd is not None:
        assert isinstance(cmd, LoadCommand)
        board = Board()
        error = cmd.validate(board)
        assert error is not None

def test_load_command_full_workflow(sample_netlist_file):
    """Test complete LOAD workflow: parse -> validate -> execute"""
    parser = CommandParser()
    board = Board()

    # Parse
    cmd = parser.parse(f"LOAD {sample_netlist_file}")
    assert cmd is not None

    # Validate
    error = cmd.validate(board)
    assert error is None

    # Execute
    result = cmd.execute(board)
    assert "OK" in result or "Loaded" in result

    # Verify board state
    assert len(board.components) == 2
    assert board.get_component("U1") is not None
