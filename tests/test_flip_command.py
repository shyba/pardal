import pytest
from pcb_tool.commands import FlipCommand
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

def test_flip_command_creation():
    cmd = FlipCommand("U1")
    assert cmd.ref == "U1"

def test_flip_command_validate_component_not_found():
    cmd = FlipCommand("NONEXISTENT")
    board = Board()
    error = cmd.validate(board)
    assert error is not None
    assert "not found" in error.lower()

def test_flip_command_validate_component_locked(sample_board):
    cmd = FlipCommand("R1")
    error = cmd.validate(sample_board)
    assert error is not None
    assert "locked" in error.lower()

def test_flip_command_validate_success(sample_board):
    cmd = FlipCommand("U1")
    error = cmd.validate(sample_board)
    assert error is None

def test_flip_command_execute(sample_board):
    cmd = FlipCommand("U1")
    result = cmd.execute(sample_board)

    assert "OK" in result or "Flipped" in result
    # Note: We'll just track flip in result message for MVP1
    # Full implementation would track layer (F.Cu/B.Cu) in Component

def test_parser_can_parse_flip_command():
    parser = CommandParser()
    cmd = parser.parse("FLIP U1")

    assert isinstance(cmd, FlipCommand)
    assert cmd.ref == "U1"

def test_flip_command_full_workflow(sample_board):
    parser = CommandParser()
    cmd = parser.parse("FLIP U1")
    assert cmd.validate(sample_board) is None
    result = cmd.execute(sample_board)
    assert "OK" in result or "Flipped" in result
