# tests/test_command_pattern.py
import pytest
from pcb_tool.commands import Command
from pcb_tool.data_model import Board, Component
from pcb_tool.command_parser import CommandParser

def test_command_base_class_is_abstract():
    """Test that Command base class cannot be instantiated directly"""
    with pytest.raises(TypeError):
        Command()

def test_command_has_required_methods():
    """Test that Command subclass must implement validate and execute"""

    class IncompleteCommand(Command):
        pass

    with pytest.raises(TypeError):
        IncompleteCommand()

def test_command_validate_execute_pattern():
    """Test complete Command implementation with validate and execute"""

    class TestCommand(Command):
        def __init__(self, value: str):
            self.value = value

        def validate(self, board: Board) -> str | None:
            if not self.value:
                return "Value cannot be empty"
            return None

        def execute(self, board: Board) -> str:
            return f"Executed with {self.value}"

    cmd = TestCommand("test")
    board = Board()

    # Validate should return None for valid command
    error = cmd.validate(board)
    assert error is None

    # Execute should return success message
    result = cmd.execute(board)
    assert result == "Executed with test"

def test_command_validation_failure():
    """Test that validation can return error messages"""

    class TestCommand(Command):
        def __init__(self, value: str):
            self.value = value

        def validate(self, board: Board) -> str | None:
            if not self.value:
                return "Value cannot be empty"
            return None

        def execute(self, board: Board) -> str:
            return "OK"

    cmd = TestCommand("")
    board = Board()

    error = cmd.validate(board)
    assert error == "Value cannot be empty"

def test_command_parser_basic():
    """Test basic CommandParser can be instantiated"""
    parser = CommandParser()
    assert parser is not None

def test_command_parser_empty_input():
    """Test parser handles empty input gracefully"""
    parser = CommandParser()
    result = parser.parse("")
    assert result is None

def test_command_parser_whitespace_only():
    """Test parser handles whitespace-only input"""
    parser = CommandParser()
    result = parser.parse("   \t  \n  ")
    assert result is None

def test_command_parser_unknown_command():
    """Test parser returns None for unknown commands"""
    parser = CommandParser()
    result = parser.parse("UNKNOWN_COMMAND arg1 arg2")
    assert result is None

def test_command_parser_case_insensitive():
    """Test parser handles commands in any case"""
    parser = CommandParser()

    # Register a dummy command handler for testing
    class DummyCommand(Command):
        def validate(self, board: Board) -> str | None:
            return None
        def execute(self, board: Board) -> str:
            return "OK"

    # Parser should handle case-insensitive matching
    # For now, just test that it doesn't crash
    parser.parse("help")
    parser.parse("HELP")
    parser.parse("HeLp")
