import pytest
from pcb_tool.commands import GroupMoveCommand
from pcb_tool.command_parser import CommandParser
from pcb_tool.data_model import Board, Component


@pytest.fixture
def sample_board():
    """Create a board with multiple test components."""
    board = Board()
    board.add_component(Component(
        ref="R1", value="10k", footprint="R_0805",
        position=(10.0, 20.0), rotation=0.0
    ))
    board.add_component(Component(
        ref="R2", value="22k", footprint="R_0805",
        position=(12.0, 22.0), rotation=0.0
    ))
    board.add_component(Component(
        ref="Q1", value="2N3904", footprint="TO-92",
        position=(14.0, 24.0), rotation=0.0
    ))
    board.add_component(Component(
        ref="C1", value="100nF", footprint="C_0805",
        position=(16.0, 26.0), rotation=0.0, locked=True
    ))
    return board


def test_group_move_command_creation():
    """Test creating a GroupMoveCommand."""
    cmd = GroupMoveCommand(["R1", "R2"], 5.0, 10.0)
    assert cmd.component_refs == ["R1", "R2"]
    assert cmd.dx == 5.0
    assert cmd.dy == 10.0


def test_group_move_command_creation_with_three_refs():
    """Test creating a GroupMoveCommand with three components."""
    cmd = GroupMoveCommand(["R1", "R2", "Q1"], 5.0, 10.0)
    assert cmd.component_refs == ["R1", "R2", "Q1"]
    assert cmd.dx == 5.0
    assert cmd.dy == 10.0


def test_group_move_command_creation_with_negative_offsets():
    """Test creating a GroupMoveCommand with negative offsets."""
    cmd = GroupMoveCommand(["R1"], -3.5, -7.2)
    assert cmd.dx == -3.5
    assert cmd.dy == -7.2


def test_group_move_validate_component_not_found(sample_board):
    """Test validation fails when component doesn't exist."""
    cmd = GroupMoveCommand(["R1", "NONEXISTENT"], 5.0, 10.0)
    error = cmd.validate(sample_board)
    assert error is not None
    assert "NONEXISTENT" in error
    assert "not found" in error.lower()


def test_group_move_validate_component_locked(sample_board):
    """Test validation fails when any component is locked."""
    cmd = GroupMoveCommand(["R1", "C1"], 5.0, 10.0)
    error = cmd.validate(sample_board)
    assert error is not None
    assert "C1" in error
    assert "locked" in error.lower()


def test_group_move_validate_success(sample_board):
    """Test validation succeeds for valid components."""
    cmd = GroupMoveCommand(["R1", "R2", "Q1"], 5.0, 10.0)
    error = cmd.validate(sample_board)
    assert error is None


def test_group_move_execute_two_components(sample_board):
    """Test executing group move on two components."""
    cmd = GroupMoveCommand(["R1", "R2"], 5.0, 10.0)
    result = cmd.execute(sample_board)

    # Check result message format
    assert "OK" in result or "Moved" in result
    assert "2 components" in result
    assert "(5" in result and "10" in result  # offset in message

    # Check positions were updated
    r1 = sample_board.get_component("R1")
    r2 = sample_board.get_component("R2")
    assert r1.position == (15.0, 30.0)
    assert r2.position == (17.0, 32.0)


def test_group_move_execute_three_components(sample_board):
    """Test executing group move on three components."""
    cmd = GroupMoveCommand(["R1", "R2", "Q1"], 5.0, 10.0)
    result = cmd.execute(sample_board)

    # Check result message
    assert "3 components" in result

    # Check all positions were updated
    r1 = sample_board.get_component("R1")
    r2 = sample_board.get_component("R2")
    q1 = sample_board.get_component("Q1")
    assert r1.position == (15.0, 30.0)
    assert r2.position == (17.0, 32.0)
    assert q1.position == (19.0, 34.0)


def test_group_move_execute_with_negative_offset(sample_board):
    """Test executing group move with negative offset."""
    cmd = GroupMoveCommand(["R1", "R2"], -2.0, -3.0)
    result = cmd.execute(sample_board)

    # Check positions were updated correctly
    r1 = sample_board.get_component("R1")
    r2 = sample_board.get_component("R2")
    assert r1.position == (8.0, 17.0)
    assert r2.position == (10.0, 19.0)


def test_group_move_undo(sample_board):
    """Test undo restores original positions."""
    cmd = GroupMoveCommand(["R1", "R2", "Q1"], 5.0, 10.0)

    # Store original positions
    orig_r1 = sample_board.get_component("R1").position
    orig_r2 = sample_board.get_component("R2").position
    orig_q1 = sample_board.get_component("Q1").position

    # Execute and then undo
    cmd.execute(sample_board)
    cmd.undo(sample_board)

    # Check positions were restored
    assert sample_board.get_component("R1").position == orig_r1
    assert sample_board.get_component("R2").position == orig_r2
    assert sample_board.get_component("Q1").position == orig_q1


def test_group_move_parser_basic():
    """Test parser can parse basic GROUP_MOVE command."""
    parser = CommandParser()
    cmd = parser.parse("GROUP_MOVE R1 R2 BY 5.0 10.0")

    assert isinstance(cmd, GroupMoveCommand)
    assert cmd.component_refs == ["R1", "R2"]
    assert cmd.dx == 5.0
    assert cmd.dy == 10.0


def test_group_move_parser_three_refs():
    """Test parser handles three component references."""
    parser = CommandParser()
    cmd = parser.parse("GROUP_MOVE R1 R2 Q1 BY 3.5 -2.5")

    assert isinstance(cmd, GroupMoveCommand)
    assert cmd.component_refs == ["R1", "R2", "Q1"]
    assert cmd.dx == 3.5
    assert cmd.dy == -2.5


def test_group_move_parser_many_refs():
    """Test parser handles many component references."""
    parser = CommandParser()
    cmd = parser.parse("GROUP_MOVE R1 R2 R3 C1 C2 C3 U1 BY 1.0 2.0")

    assert isinstance(cmd, GroupMoveCommand)
    assert cmd.component_refs == ["R1", "R2", "R3", "C1", "C2", "C3", "U1"]
    assert cmd.dx == 1.0
    assert cmd.dy == 2.0


def test_group_move_parser_negative_offsets():
    """Test parser handles negative offsets."""
    parser = CommandParser()
    cmd = parser.parse("GROUP_MOVE R1 R2 BY -5.0 -10.0")

    assert isinstance(cmd, GroupMoveCommand)
    assert cmd.dx == -5.0
    assert cmd.dy == -10.0


def test_group_move_parser_case_insensitive():
    """Test parser is case insensitive."""
    parser = CommandParser()
    cmd = parser.parse("group_move r1 r2 by 5.0 10.0")

    assert isinstance(cmd, GroupMoveCommand)
    assert cmd.component_refs == ["r1", "r2"]


def test_group_move_parser_invalid_missing_by():
    """Test parser returns None when BY keyword is missing."""
    parser = CommandParser()
    cmd = parser.parse("GROUP_MOVE R1 R2 5.0 10.0")

    assert cmd is None


def test_group_move_parser_invalid_missing_offset():
    """Test parser returns None when offset values are missing."""
    parser = CommandParser()
    cmd = parser.parse("GROUP_MOVE R1 R2 BY 5.0")

    assert cmd is None


def test_group_move_parser_invalid_no_refs():
    """Test parser returns None when no references provided."""
    parser = CommandParser()
    cmd = parser.parse("GROUP_MOVE BY 5.0 10.0")

    assert cmd is None


def test_group_move_full_workflow(sample_board):
    """Test complete workflow from parse to execute."""
    parser = CommandParser()
    cmd = parser.parse("GROUP_MOVE R1 R2 Q1 BY 5.0 10.0")

    assert cmd is not None
    assert cmd.validate(sample_board) is None

    result = cmd.execute(sample_board)

    assert "OK" in result or "Moved" in result
    assert sample_board.get_component("R1").position == (15.0, 30.0)
    assert sample_board.get_component("R2").position == (17.0, 32.0)
    assert sample_board.get_component("Q1").position == (19.0, 34.0)
