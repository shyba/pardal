# tests/test_command_parser_registration.py
import pytest
from pcb_tool.command_parser import CommandParser
from pcb_tool.commands import Command
from pcb_tool.data_model import Board

class DummyCommand(Command):
    """Test command for registration testing"""
    def __init__(self, arg: str = ""):
        self.arg = arg

    def validate(self, board: Board) -> str | None:
        return None

    def execute(self, board: Board) -> str:
        return f"Executed with {self.arg}"

def test_parser_can_register_commands():
    """Test that parser can register command factories"""
    parser = CommandParser()

    # Register a command factory
    parser.register("TEST", lambda args: DummyCommand(args[0] if args else ""))

    assert "TEST" in parser.commands

def test_parser_parse_registered_command():
    """Test parser can parse and create registered commands"""
    parser = CommandParser()

    parser.register("TEST", lambda args: DummyCommand(args[0] if args else ""))

    cmd = parser.parse("TEST hello")

    assert cmd is not None
    assert isinstance(cmd, DummyCommand)
    assert cmd.arg == "hello"

def test_parser_parse_unregistered_command_returns_none():
    """Test parser returns None for unregistered commands"""
    parser = CommandParser()

    cmd = parser.parse("UNREGISTERED arg1 arg2")

    assert cmd is None

def test_parser_case_insensitive_lookup():
    """Test command lookup is case insensitive"""
    parser = CommandParser()

    parser.register("TEST", lambda args: DummyCommand())

    cmd1 = parser.parse("test")
    cmd2 = parser.parse("TEST")
    cmd3 = parser.parse("TeSt")

    assert all(isinstance(c, DummyCommand) for c in [cmd1, cmd2, cmd3])
