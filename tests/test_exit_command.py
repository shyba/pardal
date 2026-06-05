import pytest
from pardal.commands import ExitCommand
from pardal.command_parser import CommandParser
from pardal.data_model import Board


def test_exit_command_creation():
    cmd = ExitCommand()
    assert cmd is not None


def test_exit_command_validate_always_succeeds():
    cmd = ExitCommand()
    board = Board()
    error = cmd.validate(board)
    assert error is None


def test_exit_command_execute():
    cmd = ExitCommand()
    board = Board()
    result = cmd.execute(board)

    assert (
        "exit" in result.lower()
        or "goodbye" in result.lower()
        or "bye" in result.lower()
    )


def test_parser_can_parse_exit_command():
    parser = CommandParser()

    cmd1 = parser.parse("EXIT")
    cmd2 = parser.parse("QUIT")

    assert isinstance(cmd1, ExitCommand)
    assert isinstance(cmd2, ExitCommand)
