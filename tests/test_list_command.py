import pytest
from pcb_tool.commands import ListComponentsCommand
from pcb_tool.command_parser import CommandParser
from pcb_tool.data_model import Board, Component

@pytest.fixture
def sample_board():
    """Create a board with components for testing"""
    board = Board()

    board.add_component(Component(
        ref="U1",
        value="ATmega328P",
        footprint="Package_DIP:DIP-28_W7.62mm",
        position=(50.0, 40.0),
        rotation=0.0
    ))

    board.add_component(Component(
        ref="R1",
        value="10k",
        footprint="Resistor_SMD:R_0805_2012Metric",
        position=(60.0, 50.0),
        rotation=90.0,
        locked=True
    ))

    board.add_component(Component(
        ref="C1",
        value="100n",
        footprint="Capacitor_SMD:C_0805_2012Metric",
        position=(70.0, 30.0),
        rotation=180.0
    ))

    return board

def test_list_components_command_creation():
    """Test ListComponentsCommand can be instantiated"""
    cmd = ListComponentsCommand()
    assert cmd is not None

def test_list_components_validate_always_succeeds():
    """Test validation always succeeds"""
    cmd = ListComponentsCommand()
    board = Board()

    error = cmd.validate(board)

    assert error is None

def test_list_components_execute_empty_board():
    """Test execute on empty board"""
    cmd = ListComponentsCommand()
    board = Board()

    result = cmd.execute(board)

    assert "0 components" in result.lower() or "no components" in result.lower()

def test_list_components_execute_shows_all_components(sample_board):
    """Test execute shows all components"""
    cmd = ListComponentsCommand()

    result = cmd.execute(sample_board)

    assert "U1" in result
    assert "R1" in result
    assert "C1" in result
    assert "ATmega328P" in result
    assert "10k" in result
    assert "100n" in result

def test_list_components_shows_positions(sample_board):
    """Test output includes component positions"""
    cmd = ListComponentsCommand()

    result = cmd.execute(sample_board)

    assert "50" in result and "40" in result  # U1 position
    assert "60" in result and "50" in result  # R1 position
    assert "70" in result and "30" in result  # C1 position

def test_list_components_shows_rotations(sample_board):
    """Test output includes rotation angles"""
    cmd = ListComponentsCommand()

    result = cmd.execute(sample_board)

    assert "90" in result   # R1 rotation
    assert "180" in result  # C1 rotation

def test_list_components_shows_locked_status(sample_board):
    """Test output indicates locked components"""
    cmd = ListComponentsCommand()

    result = cmd.execute(sample_board)

    # R1 is locked, should be indicated somehow
    result_lower = result.lower()
    assert "lock" in result_lower or "[L]" in result or "*" in result

def test_list_components_shows_layer(sample_board):
    """Test output includes layer info"""
    cmd = ListComponentsCommand()

    result = cmd.execute(sample_board)

    # Should show layer per USAGE.md format: REF: Value @ (x, y) rot° Layer
    assert "F.Cu" in result

def test_parser_can_parse_list_components():
    """Test CommandParser can parse LIST COMPONENTS"""
    parser = CommandParser()

    cmd = parser.parse("LIST COMPONENTS")

    assert isinstance(cmd, ListComponentsCommand)

def test_parser_handles_list_variations():
    """Test parser handles case variations"""
    parser = CommandParser()

    cmd1 = parser.parse("list components")
    cmd2 = parser.parse("LIST COMPONENTS")
    cmd3 = parser.parse("List Components")

    assert all(isinstance(c, ListComponentsCommand) for c in [cmd1, cmd2, cmd3])

def test_list_components_full_workflow(sample_board):
    """Test complete LIST workflow: parse -> validate -> execute"""
    parser = CommandParser()

    # Parse
    cmd = parser.parse("LIST COMPONENTS")
    assert cmd is not None

    # Validate
    error = cmd.validate(sample_board)
    assert error is None

    # Execute
    result = cmd.execute(sample_board)

    # Verify output has all components
    assert all(ref in result for ref in ["U1", "R1", "C1"])
