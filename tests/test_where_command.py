import pytest
from pcb_tool.commands import WhereCommand
from pcb_tool.command_parser import CommandParser
from pcb_tool.data_model import Board, Component

@pytest.fixture
def sample_board():
    board = Board()
    board.add_component(Component(
        ref="U1", value="ATmega328P", footprint="DIP-28",
        position=(50.0, 40.0), rotation=90.0, locked=True
    ))
    return board

def test_where_command_creation():
    cmd = WhereCommand("U1")
    assert cmd.ref == "U1"

def test_where_command_validate_component_not_found():
    cmd = WhereCommand("NONEXISTENT")
    board = Board()
    error = cmd.validate(board)
    assert error is not None
    assert "not found" in error.lower()

def test_where_command_validate_success(sample_board):
    cmd = WhereCommand("U1")
    error = cmd.validate(sample_board)
    assert error is None

def test_where_command_execute_shows_position(sample_board):
    cmd = WhereCommand("U1")
    result = cmd.execute(sample_board)

    assert "50" in result and "40" in result  # Position
    assert "90" in result  # Rotation

def test_where_command_execute_shows_locked_status(sample_board):
    cmd = WhereCommand("U1")
    result = cmd.execute(sample_board)

    assert "locked" in result.lower() or "LOCKED" in result

def test_parser_can_parse_where_command():
    parser = CommandParser()
    cmd = parser.parse("WHERE U1")

    assert isinstance(cmd, WhereCommand)
    assert cmd.ref == "U1"
