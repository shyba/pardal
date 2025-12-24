import pytest
from io import StringIO
from pcb_tool.repl import REPL
from pcb_tool.data_model import Board

def test_repl_creation():
    repl = REPL()
    assert repl is not None
    assert isinstance(repl.board, Board)

def test_repl_process_help_command():
    repl = REPL()
    result = repl.process_command("HELP")
    assert "LOAD" in result
    assert "SAVE" in result

def test_repl_process_exit_command():
    repl = REPL()
    result = repl.process_command("EXIT")
    assert repl.should_exit
    assert "Goodbye" in result or "exit" in result.lower()

def test_repl_process_invalid_command():
    repl = REPL()
    result = repl.process_command("INVALID_COMMAND")
    assert "unknown" in result.lower() or "invalid" in result.lower() or "error" in result.lower()
