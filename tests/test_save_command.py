import pytest
from pathlib import Path
from pcb_tool.commands import SaveCommand
from pcb_tool.command_parser import CommandParser
from pcb_tool.data_model import Board, Component

@pytest.fixture
def sample_board():
    board = Board()
    board.add_component(Component(
        ref="U1", value="IC", footprint="DIP-8",
        position=(50.0, 40.0), rotation=0.0
    ))
    return board

def test_save_command_creation(tmp_path):
    output = tmp_path / "test.kicad_pcb"
    cmd = SaveCommand(output)
    assert cmd.path == output

def test_save_command_validate_empty_board():
    """Empty board should not be saveable"""
    cmd = SaveCommand(Path("test.kicad_pcb"))
    board = Board()
    error = cmd.validate(board)
    assert error is not None
    assert "empty" in error.lower()

def test_save_command_validate_always_succeeds(sample_board):
    cmd = SaveCommand(Path("test.kicad_pcb"))
    error = cmd.validate(sample_board)
    assert error is None

def test_save_command_execute_creates_file(sample_board, tmp_path):
    output = tmp_path / "output.kicad_pcb"
    cmd = SaveCommand(output)

    result = cmd.execute(sample_board)

    assert "OK" in result or "Saved" in result
    assert output.exists()

def test_save_command_execute_has_kicad_content(sample_board, tmp_path):
    output = tmp_path / "output.kicad_pcb"
    cmd = SaveCommand(output)
    cmd.execute(sample_board)

    content = output.read_text()
    assert "(kicad_pcb" in content
    assert "U1" in content

def test_parser_can_parse_save_command():
    parser = CommandParser()
    cmd = parser.parse("SAVE output.kicad_pcb")

    assert isinstance(cmd, SaveCommand)
    assert cmd.path == Path("output.kicad_pcb")

def test_save_command_full_workflow(sample_board, tmp_path):
    output = tmp_path / "test.kicad_pcb"
    parser = CommandParser()

    cmd = parser.parse(f"SAVE {output}")
    assert cmd.validate(sample_board) is None
    result = cmd.execute(sample_board)

    assert "OK" in result or "Saved" in result
    assert output.exists()
