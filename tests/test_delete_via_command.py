import pytest
from pcb_tool.commands import DeleteViaCommand
from pcb_tool.command_parser import CommandParser
from pcb_tool.data_model import Board, Net, Via


@pytest.fixture
def sample_board():
    """Create a board with test nets and vias."""
    board = Board()
    net1 = Net(name="GND", code="1", via_size=0.8, via_drill=0.4)
    net2 = Net(name="VCC", code="2", via_size=1.0, via_drill=0.6)
    net3 = Net(name="signal with spaces", code="3", via_size=0.8, via_drill=0.4)

    # Add some vias to GND net
    via1 = Via("GND", (10.0, 20.0), 0.8, 0.4, ("F.Cu", "B.Cu"))
    via2 = Via("GND", (30.0, 40.0), 0.8, 0.4, ("F.Cu", "B.Cu"))
    via3 = Via("GND", (50.0, 60.0), 1.0, 0.5, ("F.Cu", "B.Cu"))
    net1.add_via(via1)
    net1.add_via(via2)
    net1.add_via(via3)

    # Add a via to VCC net
    via4 = Via("VCC", (5.0, 5.0), 1.0, 0.6, ("F.Cu", "B.Cu"))
    net2.add_via(via4)

    board.add_net(net1)
    board.add_net(net2)
    board.add_net(net3)
    return board


def test_delete_via_command_creation_with_position():
    """Test creating DeleteViaCommand with position parameter."""
    cmd = DeleteViaCommand("GND", position=(10.0, 20.0))
    assert cmd.net_name == "GND"
    assert cmd.position == (10.0, 20.0)
    assert cmd.delete_all is False


def test_delete_via_command_creation_with_all_mode():
    """Test creating DeleteViaCommand with ALL mode."""
    cmd = DeleteViaCommand("GND", delete_all=True)
    assert cmd.net_name == "GND"
    assert cmd.position is None
    assert cmd.delete_all is True


def test_delete_via_command_validate_net_not_found():
    """Test validation fails when net doesn't exist."""
    cmd = DeleteViaCommand("NONEXISTENT", position=(10.0, 20.0))
    board = Board()
    error = cmd.validate(board)
    assert error is not None
    assert "ERROR:" in error
    assert "not found" in error.lower()
    assert "NONEXISTENT" in error


def test_delete_via_command_validate_success_with_position(sample_board):
    """Test validation succeeds with valid position."""
    cmd = DeleteViaCommand("GND", position=(10.0, 20.0))
    error = cmd.validate(sample_board)
    assert error is None


def test_delete_via_command_validate_success_with_all(sample_board):
    """Test validation succeeds with ALL mode."""
    cmd = DeleteViaCommand("GND", delete_all=True)
    error = cmd.validate(sample_board)
    assert error is None


def test_delete_via_command_execute_delete_by_position(sample_board):
    """Test executing delete at specific position."""
    cmd = DeleteViaCommand("GND", position=(10.0, 20.0))
    result = cmd.execute(sample_board)

    assert "OK:" in result
    assert "Deleted via from net" in result
    assert "GND" in result
    assert "(10" in result or "10.0" in result

    # Verify via was removed
    net = sample_board.nets["GND"]
    assert len(net.vias) == 2  # Started with 3, removed 1


def test_delete_via_command_execute_delete_by_position_near(sample_board):
    """Test executing delete with position near via center."""
    # Position is slightly off from exact (10.0, 20.0) but within tolerance
    cmd = DeleteViaCommand("GND", position=(10.05, 20.05))
    result = cmd.execute(sample_board)

    assert "OK:" in result
    assert "Deleted via" in result

    net = sample_board.nets["GND"]
    assert len(net.vias) == 2


def test_delete_via_command_execute_no_via_found():
    """Test error when no via found at position."""
    board = Board()
    net = Net(name="GND", code="1")
    via = Via("GND", (10.0, 20.0), 0.8, 0.4, ("F.Cu", "B.Cu"))
    net.add_via(via)
    board.add_net(net)

    # Position far from any via
    cmd = DeleteViaCommand("GND", position=(100.0, 100.0))
    result = cmd.execute(board)

    assert "ERROR:" in result
    assert "No via found at" in result


def test_delete_via_command_execute_delete_all(sample_board):
    """Test executing delete all vias."""
    cmd = DeleteViaCommand("GND", delete_all=True)
    result = cmd.execute(sample_board)

    assert "OK:" in result
    assert "Deleted 3 vias" in result
    assert "GND" in result

    # Verify all vias were removed
    net = sample_board.nets["GND"]
    assert len(net.vias) == 0


def test_delete_via_command_execute_delete_all_no_vias():
    """Test delete all when net has no vias."""
    board = Board()
    net = Net(name="EMPTY", code="99")
    board.add_net(net)

    cmd = DeleteViaCommand("EMPTY", delete_all=True)
    result = cmd.execute(board)

    assert "OK:" in result
    assert "Deleted 0 vias" in result


def test_delete_via_command_undo_single_via(sample_board):
    """Test undo restores single deleted via."""
    cmd = DeleteViaCommand("GND", position=(10.0, 20.0))
    cmd.execute(sample_board)

    net = sample_board.nets["GND"]
    assert len(net.vias) == 2

    result = cmd.undo(sample_board)
    assert "OK:" in result
    assert len(net.vias) == 3


def test_delete_via_command_undo_all_vias(sample_board):
    """Test undo restores all deleted vias."""
    cmd = DeleteViaCommand("GND", delete_all=True)
    cmd.execute(sample_board)

    net = sample_board.nets["GND"]
    assert len(net.vias) == 0

    result = cmd.undo(sample_board)
    assert "OK:" in result
    assert len(net.vias) == 3

    # Verify vias are restored correctly
    assert net.vias[0].position == (10.0, 20.0)
    assert net.vias[1].position == (30.0, 40.0)
    assert net.vias[2].position == (50.0, 60.0)


def test_parser_can_parse_delete_via_at():
    """Test parser handles DELETE_VIA with AT syntax."""
    parser = CommandParser()
    cmd = parser.parse("DELETE_VIA NET GND AT 10 20")

    assert isinstance(cmd, DeleteViaCommand)
    assert cmd.net_name == "GND"
    assert cmd.position == (10.0, 20.0)
    assert cmd.delete_all is False


def test_parser_can_parse_delete_via_all():
    """Test parser handles DELETE_VIA with ALL syntax."""
    parser = CommandParser()
    cmd = parser.parse("DELETE_VIA NET GND ALL")

    assert isinstance(cmd, DeleteViaCommand)
    assert cmd.net_name == "GND"
    assert cmd.position is None
    assert cmd.delete_all is True


def test_parser_can_parse_delete_via_quoted_name():
    """Test parser handles quoted net names."""
    parser = CommandParser()
    cmd = parser.parse('DELETE_VIA NET "signal with spaces" AT 50 60')

    assert isinstance(cmd, DeleteViaCommand)
    assert cmd.net_name == "signal with spaces"


def test_delete_via_command_full_workflow(sample_board):
    """Test complete workflow: parse, validate, execute, undo."""
    parser = CommandParser()
    cmd = parser.parse("DELETE_VIA NET GND AT 30 40")

    assert cmd is not None
    assert cmd.validate(sample_board) is None

    result = cmd.execute(sample_board)
    assert "OK:" in result

    net = sample_board.nets["GND"]
    assert len(net.vias) == 2

    # Undo
    cmd.undo(sample_board)
    assert len(net.vias) == 3


def test_delete_via_command_multiple_deletes(sample_board):
    """Test deleting multiple vias one by one."""
    net = sample_board.nets["GND"]
    assert len(net.vias) == 3

    cmd1 = DeleteViaCommand("GND", position=(10.0, 20.0))
    cmd1.execute(sample_board)
    assert len(net.vias) == 2

    cmd2 = DeleteViaCommand("GND", position=(30.0, 40.0))
    cmd2.execute(sample_board)
    assert len(net.vias) == 1

    cmd3 = DeleteViaCommand("GND", position=(50.0, 60.0))
    cmd3.execute(sample_board)
    assert len(net.vias) == 0
