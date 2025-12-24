import pytest
from pcb_tool.commands import UnlockCommand
from pcb_tool.command_parser import CommandParser
from pcb_tool.data_model import Board, Component

@pytest.fixture
def sample_board():
    board = Board()
    board.add_component(Component(
        ref="U1", value="IC", footprint="DIP-8",
        position=(10.0, 20.0), rotation=0.0, locked=False
    ))
    board.add_component(Component(
        ref="R1", value="10k", footprint="R_0805",
        position=(30.0, 40.0), rotation=0.0, locked=True
    ))
    return board

def test_unlock_command_creation():
    cmd = UnlockCommand("R1")
    assert cmd.ref == "R1"

def test_unlock_command_validate_component_not_found():
    cmd = UnlockCommand("NONEXISTENT")
    board = Board()
    error = cmd.validate(board)
    assert error is not None
    assert "not found" in error.lower()

def test_unlock_command_validate_success(sample_board):
    cmd = UnlockCommand("R1")
    error = cmd.validate(sample_board)
    assert error is None

def test_unlock_command_execute_unlocks_component(sample_board):
    cmd = UnlockCommand("R1")
    comp = sample_board.get_component("R1")
    assert comp.locked is True

    result = cmd.execute(sample_board)

    assert "OK" in result or "Unlocked" in result
    assert comp.locked is False

def test_unlock_command_execute_already_unlocked(sample_board):
    cmd = UnlockCommand("U1")
    comp = sample_board.get_component("U1")
    assert comp.locked is False

    result = cmd.execute(sample_board)

    # Should succeed even if already unlocked
    assert "OK" in result or "Unlocked" in result
    assert comp.locked is False

def test_parser_can_parse_unlock_command():
    parser = CommandParser()
    cmd = parser.parse("UNLOCK R1")

    assert isinstance(cmd, UnlockCommand)
    assert cmd.ref == "R1"

def test_unlock_command_full_workflow(sample_board):
    parser = CommandParser()
    cmd = parser.parse("UNLOCK R1")

    assert cmd.validate(sample_board) is None
    result = cmd.execute(sample_board)

    assert "OK" in result or "Unlocked" in result
    assert sample_board.get_component("R1").locked is False

def test_unlock_then_move_workflow(sample_board):
    """Test that unlocking allows subsequent moves"""
    from pcb_tool.commands import MoveCommand

    parser = CommandParser()

    # R1 is locked, try to move (should fail)
    move_cmd = parser.parse("MOVE R1 TO 100 100")
    assert move_cmd.validate(sample_board) is not None  # Should fail

    # Unlock R1
    unlock_cmd = parser.parse("UNLOCK R1")
    unlock_cmd.execute(sample_board)

    # Now move should succeed
    move_cmd2 = parser.parse("MOVE R1 TO 100 100")
    assert move_cmd2.validate(sample_board) is None  # Should succeed
    move_cmd2.execute(sample_board)
    assert sample_board.get_component("R1").position == (100.0, 100.0)
