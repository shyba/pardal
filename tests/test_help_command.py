# tests/test_help_command.py
import pytest
from pcb_tool.commands import HelpCommand
from pcb_tool.data_model import Board

def test_help_command_instantiation():
    """Test HelpCommand can be created"""
    cmd = HelpCommand()
    assert cmd is not None

def test_help_command_validate_always_succeeds():
    """Test HelpCommand.validate() always returns None"""
    cmd = HelpCommand()
    board = Board()

    result = cmd.validate(board)

    assert result is None

def test_help_command_execute_returns_help_text():
    """Test HelpCommand.execute() returns help text"""
    cmd = HelpCommand()
    board = Board()

    result = cmd.execute(board)

    assert isinstance(result, str)
    assert len(result) > 0
    assert "LOAD" in result
    assert "SAVE" in result
    assert "MOVE" in result
    assert "LIST" in result

def test_help_command_help_text_format():
    """Test help text includes command descriptions"""
    cmd = HelpCommand()
    board = Board()

    result = cmd.execute(board)

    # Should have multiple lines
    lines = result.split('\n')
    assert len(lines) > 5

    # Should mention basic commands
    text_upper = result.upper()
    assert "HELP" in text_upper
    assert "EXIT" in text_upper or "QUIT" in text_upper
