import pytest
from pcb_tool.commands import ShowBoardCommand
from pcb_tool.command_parser import CommandParser
from pcb_tool.data_model import Board, Component

@pytest.fixture
def sample_board():
    board = Board()
    board.add_component(Component(ref="U1", value="IC", footprint="DIP-8", position=(50, 40), rotation=0))
    board.add_component(Component(ref="R1", value="10k", footprint="R_0805", position=(60, 50), rotation=0))
    board.add_component(Component(ref="C1", value="100n", footprint="C_0805", position=(70, 30), rotation=0))
    return board

def test_show_board_command_creation():
    cmd = ShowBoardCommand()
    assert cmd is not None

def test_show_board_validate_always_succeeds():
    cmd = ShowBoardCommand()
    board = Board()
    assert cmd.validate(board) is None

def test_show_board_execute_empty_board():
    cmd = ShowBoardCommand()
    board = Board()
    result = cmd.execute(board)
    assert "no components" in result.lower() or "empty" in result.lower()

def test_show_board_execute_shows_components(sample_board):
    cmd = ShowBoardCommand()
    result = cmd.execute(sample_board)

    assert "U1" in result
    assert "R1" in result
    assert "C1" in result

def test_show_board_output_has_structure(sample_board):
    cmd = ShowBoardCommand()
    result = cmd.execute(sample_board)

    lines = result.split('\n')
    assert len(lines) > 5  # Should be multi-line output

def test_parser_can_parse_show_board():
    parser = CommandParser()
    cmd = parser.parse("SHOW BOARD")
    assert isinstance(cmd, ShowBoardCommand)

def test_show_board_full_workflow(sample_board):
    parser = CommandParser()
    cmd = parser.parse("SHOW BOARD")
    assert cmd.validate(sample_board) is None
    result = cmd.execute(sample_board)
    assert len(result) > 0
