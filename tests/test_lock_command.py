# tests/test_lock_command.py
import pytest
from pcb_tool.commands import LockCommand
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

def test_lock_command_creation():
    cmd = LockCommand("U1")
    assert cmd.ref == "U1"

def test_lock_command_validate_component_not_found():
    cmd = LockCommand("NONEXISTENT")
    board = Board()
    error = cmd.validate(board)
    assert error is not None
    assert "not found" in error.lower()

def test_lock_command_validate_success(sample_board):
    cmd = LockCommand("U1")
    error = cmd.validate(sample_board)
    assert error is None

def test_lock_command_execute_locks_component(sample_board):
    cmd = LockCommand("U1")
    comp = sample_board.get_component("U1")
    assert comp.locked is False

    result = cmd.execute(sample_board)

    assert "OK" in result or "Locked" in result
    assert comp.locked is True

def test_lock_command_execute_already_locked(sample_board):
    cmd = LockCommand("R1")
    comp = sample_board.get_component("R1")
    assert comp.locked is True

    result = cmd.execute(sample_board)

    # Should succeed even if already locked
    assert "OK" in result or "Locked" in result
    assert comp.locked is True

def test_parser_can_parse_lock_command():
    parser = CommandParser()
    cmd = parser.parse("LOCK U1")

    assert isinstance(cmd, LockCommand)
    assert cmd.ref == "U1"

def test_lock_command_full_workflow(sample_board):
    parser = CommandParser()
    cmd = parser.parse("LOCK U1")

    assert cmd.validate(sample_board) is None
    result = cmd.execute(sample_board)

    assert "OK" in result or "Locked" in result
    assert sample_board.get_component("U1").locked is True
