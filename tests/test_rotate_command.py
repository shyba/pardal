import pytest
from pcb_tool.commands import RotateCommand
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
        position=(30.0, 40.0), rotation=45.0, locked=True
    ))
    return board

def test_rotate_command_creation():
    cmd = RotateCommand("U1", 90.0)
    assert cmd.ref == "U1"
    assert cmd.angle == 90.0

def test_rotate_command_validate_component_not_found():
    cmd = RotateCommand("NONEXISTENT", 90.0)
    board = Board()
    error = cmd.validate(board)
    assert error is not None
    assert "not found" in error.lower()

def test_rotate_command_validate_component_locked(sample_board):
    cmd = RotateCommand("R1", 90.0)
    error = cmd.validate(sample_board)
    assert error is not None
    assert "locked" in error.lower()

def test_rotate_command_validate_success(sample_board):
    cmd = RotateCommand("U1", 90.0)
    error = cmd.validate(sample_board)
    assert error is None

def test_rotate_command_execute(sample_board):
    cmd = RotateCommand("U1", 90.0)
    result = cmd.execute(sample_board)

    assert "OK" in result or "Rotated" in result
    comp = sample_board.get_component("U1")
    assert comp.rotation == 90.0

def test_rotate_command_adds_to_existing_rotation(sample_board):
    sample_board.get_component("U1").rotation = 45.0
    cmd = RotateCommand("U1", 90.0)
    cmd.execute(sample_board)

    comp = sample_board.get_component("U1")
    assert comp.rotation == 135.0  # 45 + 90

def test_parser_can_parse_rotate_command():
    parser = CommandParser()
    cmd = parser.parse("ROTATE U1 90")

    assert isinstance(cmd, RotateCommand)
    assert cmd.ref == "U1"
    assert cmd.angle == 90.0

def test_rotate_command_full_workflow(sample_board):
    parser = CommandParser()
    cmd = parser.parse("ROTATE U1 90")
    assert cmd.validate(sample_board) is None
    result = cmd.execute(sample_board)
    assert "OK" in result or "Rotated" in result
    assert sample_board.get_component("U1").rotation == 90.0
