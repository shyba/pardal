import pytest
from pathlib import Path
from pcb_tool.commands import Command, MoveCommand, RotateCommand, UndoCommand, RedoCommand, HistoryCommand
from pcb_tool.command_history import CommandHistory
from pcb_tool.command_parser import CommandParser
from pcb_tool.data_model import Board, Component

@pytest.fixture
def sample_board():
    board = Board()
    board.add_component(Component(ref="U1", value="IC", footprint="DIP-8", position=(10, 20), rotation=0))
    return board

def test_command_history_creation():
    history = CommandHistory()
    assert history is not None
    assert len(history.undo_stack) == 0
    assert len(history.redo_stack) == 0

def test_command_history_add_command():
    history = CommandHistory()
    cmd = MoveCommand("U1", 50, 60)

    history.add(cmd)

    assert len(history.undo_stack) == 1
    assert len(history.redo_stack) == 0

def test_command_history_undo(sample_board):
    history = CommandHistory()
    cmd = MoveCommand("U1", 50, 60)

    cmd.execute(sample_board)
    history.add(cmd)

    assert sample_board.get_component("U1").position == (50, 60)

    undone = history.undo(sample_board)

    assert undone is not None
    assert sample_board.get_component("U1").position == (10, 20)

def test_command_history_redo(sample_board):
    history = CommandHistory()
    cmd = MoveCommand("U1", 50, 60)

    cmd.execute(sample_board)
    history.add(cmd)
    history.undo(sample_board)

    assert sample_board.get_component("U1").position == (10, 20)

    redone = history.redo(sample_board)

    assert redone is not None
    assert sample_board.get_component("U1").position == (50, 60)

def test_command_has_undo_method():
    cmd = MoveCommand("U1", 50, 60)
    assert hasattr(cmd, 'undo')

def test_move_command_undo(sample_board):
    cmd = MoveCommand("U1", 50, 60)

    result = cmd.execute(sample_board)
    assert sample_board.get_component("U1").position == (50, 60)

    undo_result = cmd.undo(sample_board)
    assert sample_board.get_component("U1").position == (10, 20)
    assert "Undo" in undo_result or "Restored" in undo_result

def test_rotate_command_undo(sample_board):
    cmd = RotateCommand("U1", 90)

    cmd.execute(sample_board)
    assert sample_board.get_component("U1").rotation == 90

    cmd.undo(sample_board)
    assert sample_board.get_component("U1").rotation == 0

def test_undo_command_creation():
    cmd = UndoCommand()
    assert cmd is not None

def test_undo_command_with_empty_history(sample_board):
    cmd = UndoCommand()
    cmd.history = CommandHistory()

    result = cmd.execute(sample_board)
    assert "nothing to undo" in result.lower() or "no commands" in result.lower()

def test_redo_command_creation():
    cmd = RedoCommand()
    assert cmd is not None

def test_redo_command_with_empty_history(sample_board):
    cmd = RedoCommand()
    cmd.history = CommandHistory()

    result = cmd.execute(sample_board)
    assert "nothing to redo" in result.lower() or "no commands" in result.lower()

def test_history_command_shows_commands():
    cmd = HistoryCommand()
    cmd.history = CommandHistory()

    move1 = MoveCommand("U1", 50, 60)
    move2 = MoveCommand("U1", 70, 80)
    cmd.history.add(move1)
    cmd.history.add(move2)

    result = cmd.execute(Board())
    assert "MOVE" in result
    assert "2" in result or "two" in result.lower()

def test_parser_can_parse_undo():
    parser = CommandParser()
    cmd = parser.parse("UNDO")
    assert isinstance(cmd, UndoCommand)

def test_parser_can_parse_redo():
    parser = CommandParser()
    cmd = parser.parse("REDO")
    assert isinstance(cmd, RedoCommand)

def test_parser_can_parse_history():
    parser = CommandParser()
    cmd = parser.parse("HISTORY")
    assert isinstance(cmd, HistoryCommand)

def test_full_undo_redo_workflow(sample_board):
    parser = CommandParser()
    history = CommandHistory()

    # Execute move
    move_cmd = parser.parse("MOVE U1 TO 50 60")
    move_cmd.execute(sample_board)
    history.add(move_cmd)
    assert sample_board.get_component("U1").position == (50, 60)

    # Undo
    undo_cmd = parser.parse("UNDO")
    undo_cmd.history = history
    undo_cmd.execute(sample_board)
    assert sample_board.get_component("U1").position == (10, 20)

    # Redo
    redo_cmd = parser.parse("REDO")
    redo_cmd.history = history
    redo_cmd.execute(sample_board)
    assert sample_board.get_component("U1").position == (50, 60)
