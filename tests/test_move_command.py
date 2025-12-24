import pytest
from pcb_tool.commands import MoveCommand
from pcb_tool.command_parser import CommandParser
from pcb_tool.data_model import Board, Component

@pytest.fixture
def sample_board():
    board = Board()
    board.add_component(Component(
        ref="U1", value="IC", footprint="DIP-8",
        position=(10.0, 20.0), rotation=0.0
    ))
    board.add_component(Component(
        ref="R1", value="10k", footprint="R_0805",
        position=(30.0, 40.0), rotation=0.0, locked=True
    ))
    return board

def test_move_command_creation():
    cmd = MoveCommand("U1", 50.0, 60.0)
    assert cmd.ref == "U1"
    assert cmd.x == 50.0
    assert cmd.y == 60.0

def test_move_command_validate_component_not_found():
    cmd = MoveCommand("NONEXISTENT", 50.0, 60.0)
    board = Board()
    error = cmd.validate(board)
    assert error is not None
    assert "not found" in error.lower()

def test_move_command_validate_component_locked(sample_board):
    cmd = MoveCommand("R1", 50.0, 60.0)
    error = cmd.validate(sample_board)
    assert error is not None
    assert "locked" in error.lower()

def test_move_command_validate_success(sample_board):
    cmd = MoveCommand("U1", 50.0, 60.0)
    error = cmd.validate(sample_board)
    assert error is None

def test_move_command_execute(sample_board):
    cmd = MoveCommand("U1", 50.0, 60.0)
    result = cmd.execute(sample_board)

    assert "OK" in result or "Moved" in result
    comp = sample_board.get_component("U1")
    assert comp.position == (50.0, 60.0)

def test_parser_can_parse_move_command():
    parser = CommandParser()
    cmd = parser.parse("MOVE U1 TO 50 60")

    assert isinstance(cmd, MoveCommand)
    assert cmd.ref == "U1"
    assert cmd.x == 50.0
    assert cmd.y == 60.0

def test_move_command_full_workflow(sample_board):
    parser = CommandParser()
    cmd = parser.parse("MOVE U1 TO 50 60")
    assert cmd.validate(sample_board) is None
    result = cmd.execute(sample_board)
    assert "OK" in result or "Moved" in result
    assert sample_board.get_component("U1").position == (50.0, 60.0)
