import pytest
import math
from pcb_tool.commands import ArrangeCommand
from pcb_tool.command_parser import CommandParser
from pcb_tool.data_model import Board, Component


@pytest.fixture
def sample_board():
    """Create a board with multiple test components at various positions."""
    board = Board()
    board.add_component(Component(
        ref="R1", value="10k", footprint="R_0805",
        position=(10.0, 20.0), rotation=0.0
    ))
    board.add_component(Component(
        ref="R2", value="22k", footprint="R_0805",
        position=(15.0, 25.0), rotation=0.0
    ))
    board.add_component(Component(
        ref="C1", value="100nF", footprint="C_0805",
        position=(20.0, 30.0), rotation=0.0
    ))
    board.add_component(Component(
        ref="Q1", value="2N3904", footprint="TO-92",
        position=(25.0, 35.0), rotation=0.0, locked=True
    ))
    board.add_component(Component(
        ref="U1", value="IC", footprint="DIP-8",
        position=(30.0, 40.0), rotation=0.0
    ))
    return board


def test_arrange_command_creation_default():
    """Test creating ArrangeCommand with default pattern and spacing."""
    cmd = ArrangeCommand(["R1", "R2", "C1"])
    assert cmd.component_refs == ["R1", "R2", "C1"]
    assert cmd.pattern == "GRID"
    assert cmd.spacing == 5.0


def test_arrange_command_creation_row_pattern():
    """Test creating ArrangeCommand with ROW pattern."""
    cmd = ArrangeCommand(["R1", "R2"], pattern="ROW")
    assert cmd.pattern == "ROW"
    assert cmd.spacing == 5.0


def test_arrange_command_creation_column_pattern():
    """Test creating ArrangeCommand with COLUMN pattern."""
    cmd = ArrangeCommand(["R1", "R2"], pattern="COLUMN")
    assert cmd.pattern == "COLUMN"


def test_arrange_command_creation_custom_spacing():
    """Test creating ArrangeCommand with custom spacing."""
    cmd = ArrangeCommand(["R1", "R2"], pattern="ROW", spacing=10.0)
    assert cmd.spacing == 10.0


def test_arrange_validate_component_not_found(sample_board):
    """Test validation fails when component doesn't exist."""
    cmd = ArrangeCommand(["R1", "NONEXISTENT"])
    error = cmd.validate(sample_board)
    assert error is not None
    assert "NONEXISTENT" in error
    assert "not found" in error.lower()


def test_arrange_validate_component_locked(sample_board):
    """Test validation fails when any component is locked."""
    cmd = ArrangeCommand(["R1", "Q1"])
    error = cmd.validate(sample_board)
    assert error is not None
    assert "Q1" in error
    assert "locked" in error.lower()


def test_arrange_validate_success(sample_board):
    """Test validation succeeds for valid components."""
    cmd = ArrangeCommand(["R1", "R2", "C1"])
    error = cmd.validate(sample_board)
    assert error is None


def test_arrange_execute_row_two_components(sample_board):
    """Test arranging two components in a row."""
    cmd = ArrangeCommand(["R1", "R2"], pattern="ROW", spacing=5.0)
    result = cmd.execute(sample_board)

    # Check result message
    assert "OK" in result or "Arranged" in result
    assert "2 components" in result
    assert "ROW" in result

    # Check positions: all Y same as first, X spaced
    r1 = sample_board.get_component("R1")
    r2 = sample_board.get_component("R2")
    assert r1.position == (10.0, 20.0)  # First stays put
    assert r2.position == (15.0, 20.0)  # Same Y, X offset by spacing


def test_arrange_execute_row_three_components(sample_board):
    """Test arranging three components in a row."""
    cmd = ArrangeCommand(["R1", "R2", "C1"], pattern="ROW", spacing=10.0)
    result = cmd.execute(sample_board)

    # Check positions
    r1 = sample_board.get_component("R1")
    r2 = sample_board.get_component("R2")
    c1 = sample_board.get_component("C1")
    assert r1.position == (10.0, 20.0)  # First stays put
    assert r2.position == (20.0, 20.0)  # X = 10 + 10
    assert c1.position == (30.0, 20.0)  # X = 10 + 20


def test_arrange_execute_column_two_components(sample_board):
    """Test arranging two components in a column."""
    cmd = ArrangeCommand(["R1", "R2"], pattern="COLUMN", spacing=5.0)
    result = cmd.execute(sample_board)

    # Check result message
    assert "COLUMN" in result

    # Check positions: all X same as first, Y spaced
    r1 = sample_board.get_component("R1")
    r2 = sample_board.get_component("R2")
    assert r1.position == (10.0, 20.0)  # First stays put
    assert r2.position == (10.0, 25.0)  # Same X, Y offset by spacing


def test_arrange_execute_column_three_components(sample_board):
    """Test arranging three components in a column."""
    cmd = ArrangeCommand(["R1", "R2", "C1"], pattern="COLUMN", spacing=8.0)
    result = cmd.execute(sample_board)

    # Check positions
    r1 = sample_board.get_component("R1")
    r2 = sample_board.get_component("R2")
    c1 = sample_board.get_component("C1")
    assert r1.position == (10.0, 20.0)  # First stays put
    assert r2.position == (10.0, 28.0)  # Y = 20 + 8
    assert c1.position == (10.0, 36.0)  # Y = 20 + 16


def test_arrange_execute_grid_four_components(sample_board):
    """Test arranging four components in a grid (2x2)."""
    cmd = ArrangeCommand(["R1", "R2", "C1", "U1"], pattern="GRID", spacing=5.0)
    result = cmd.execute(sample_board)

    # Check result message
    assert "GRID" in result

    # Check positions: 2x2 grid
    # Grid size = ceil(sqrt(4)) = 2
    r1 = sample_board.get_component("R1")
    r2 = sample_board.get_component("R2")
    c1 = sample_board.get_component("C1")
    u1 = sample_board.get_component("U1")

    # First row
    assert r1.position == (10.0, 20.0)  # [0,0]
    assert r2.position == (15.0, 20.0)  # [1,0]

    # Second row
    assert c1.position == (10.0, 25.0)  # [0,1]
    assert u1.position == (15.0, 25.0)  # [1,1]


def test_arrange_execute_grid_three_components(sample_board):
    """Test arranging three components in a grid (2x2 with one empty)."""
    cmd = ArrangeCommand(["R1", "R2", "C1"], pattern="GRID", spacing=5.0)
    result = cmd.execute(sample_board)

    # Grid size = ceil(sqrt(3)) = 2
    r1 = sample_board.get_component("R1")
    r2 = sample_board.get_component("R2")
    c1 = sample_board.get_component("C1")

    assert r1.position == (10.0, 20.0)  # [0,0]
    assert r2.position == (15.0, 20.0)  # [1,0]
    assert c1.position == (10.0, 25.0)  # [0,1]


def test_arrange_execute_grid_nine_components():
    """Test arranging nine components in a grid (3x3)."""
    board = Board()
    for i in range(9):
        board.add_component(Component(
            ref=f"R{i+1}", value="10k", footprint="R_0805",
            position=(i * 10.0, i * 10.0), rotation=0.0
        ))

    refs = [f"R{i+1}" for i in range(9)]
    cmd = ArrangeCommand(refs, pattern="GRID", spacing=10.0)
    result = cmd.execute(board)

    # Grid size = ceil(sqrt(9)) = 3
    # Check a few key positions
    r1 = board.get_component("R1")
    r3 = board.get_component("R3")
    r9 = board.get_component("R9")

    assert r1.position == (0.0, 0.0)    # [0,0]
    assert r3.position == (20.0, 0.0)   # [2,0]
    assert r9.position == (20.0, 20.0)  # [2,2]


def test_arrange_undo(sample_board):
    """Test undo restores original positions."""
    cmd = ArrangeCommand(["R1", "R2", "C1"], pattern="ROW")

    # Store original positions
    orig_r1 = sample_board.get_component("R1").position
    orig_r2 = sample_board.get_component("R2").position
    orig_c1 = sample_board.get_component("C1").position

    # Execute and then undo
    cmd.execute(sample_board)
    cmd.undo(sample_board)

    # Check positions were restored
    assert sample_board.get_component("R1").position == orig_r1
    assert sample_board.get_component("R2").position == orig_r2
    assert sample_board.get_component("C1").position == orig_c1


def test_arrange_parser_default():
    """Test parser with default GRID pattern."""
    parser = CommandParser()
    cmd = parser.parse("ARRANGE R1 R2 C1")

    assert isinstance(cmd, ArrangeCommand)
    assert cmd.component_refs == ["R1", "R2", "C1"]
    assert cmd.pattern == "GRID"
    assert cmd.spacing == 5.0


def test_arrange_parser_row_pattern():
    """Test parser with ROW pattern."""
    parser = CommandParser()
    cmd = parser.parse("ARRANGE R1 R2 C1 ROW")

    assert isinstance(cmd, ArrangeCommand)
    assert cmd.component_refs == ["R1", "R2", "C1"]
    assert cmd.pattern == "ROW"


def test_arrange_parser_column_pattern():
    """Test parser with COLUMN pattern."""
    parser = CommandParser()
    cmd = parser.parse("ARRANGE R1 R2 COLUMN")

    assert isinstance(cmd, ArrangeCommand)
    assert cmd.component_refs == ["R1", "R2"]
    assert cmd.pattern == "COLUMN"


def test_arrange_parser_grid_explicit():
    """Test parser with explicit GRID pattern."""
    parser = CommandParser()
    cmd = parser.parse("ARRANGE R1 R2 C1 GRID")

    assert isinstance(cmd, ArrangeCommand)
    assert cmd.pattern == "GRID"


def test_arrange_parser_with_spacing():
    """Test parser with custom spacing."""
    parser = CommandParser()
    cmd = parser.parse("ARRANGE R1 R2 ROW SPACING 10.0")

    assert isinstance(cmd, ArrangeCommand)
    assert cmd.pattern == "ROW"
    assert cmd.spacing == 10.0


def test_arrange_parser_spacing_without_pattern():
    """Test parser with spacing but no pattern (defaults to GRID)."""
    parser = CommandParser()
    cmd = parser.parse("ARRANGE R1 R2 C1 SPACING 8.0")

    assert isinstance(cmd, ArrangeCommand)
    assert cmd.pattern == "GRID"
    assert cmd.spacing == 8.0


def test_arrange_parser_pattern_and_spacing():
    """Test parser with both pattern and spacing."""
    parser = CommandParser()
    cmd = parser.parse("ARRANGE R1 R2 R3 COLUMN SPACING 15.0")

    assert isinstance(cmd, ArrangeCommand)
    assert cmd.component_refs == ["R1", "R2", "R3"]
    assert cmd.pattern == "COLUMN"
    assert cmd.spacing == 15.0


def test_arrange_parser_case_insensitive():
    """Test parser is case insensitive."""
    parser = CommandParser()
    cmd = parser.parse("arrange r1 r2 row spacing 5.0")

    assert isinstance(cmd, ArrangeCommand)
    assert cmd.component_refs == ["r1", "r2"]
    assert cmd.pattern == "ROW"


def test_arrange_parser_invalid_no_refs():
    """Test parser returns None when no references provided."""
    parser = CommandParser()
    cmd = parser.parse("ARRANGE ROW")

    assert cmd is None


def test_arrange_full_workflow(sample_board):
    """Test complete workflow from parse to execute."""
    parser = CommandParser()
    cmd = parser.parse("ARRANGE R1 R2 C1 ROW SPACING 10.0")

    assert cmd is not None
    assert cmd.validate(sample_board) is None

    result = cmd.execute(sample_board)

    assert "OK" in result or "Arranged" in result
    assert sample_board.get_component("R1").position == (10.0, 20.0)
    assert sample_board.get_component("R2").position == (20.0, 20.0)
    assert sample_board.get_component("C1").position == (30.0, 20.0)
