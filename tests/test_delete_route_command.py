import pytest
from pcb_tool.commands import DeleteRouteCommand
from pcb_tool.command_parser import CommandParser
from pcb_tool.data_model import Board, Net, TraceSegment


@pytest.fixture
def sample_board():
    """Create a board with test nets and segments."""
    board = Board()
    net1 = Net(name="GND", code="1", track_width=0.25)
    net2 = Net(name="VCC", code="2", track_width=0.5)
    net3 = Net(name="signal with spaces", code="3", track_width=0.3)

    # Add some segments to GND net
    seg1 = TraceSegment("GND", (10.0, 20.0), (30.0, 40.0), "F.Cu", 0.25)
    seg2 = TraceSegment("GND", (30.0, 40.0), (50.0, 60.0), "F.Cu", 0.25)
    seg3 = TraceSegment("GND", (50.0, 60.0), (70.0, 80.0), "B.Cu", 0.25)
    net1.add_segment(seg1)
    net1.add_segment(seg2)
    net1.add_segment(seg3)

    # Add a segment to VCC net
    seg4 = TraceSegment("VCC", (5.0, 5.0), (15.0, 15.0), "F.Cu", 0.5)
    net2.add_segment(seg4)

    board.add_net(net1)
    board.add_net(net2)
    board.add_net(net3)
    return board


def test_delete_route_command_creation_with_position():
    """Test creating DeleteRouteCommand with position parameter."""
    cmd = DeleteRouteCommand("GND", position=(10.0, 20.0))
    assert cmd.net_name == "GND"
    assert cmd.position == (10.0, 20.0)
    assert cmd.delete_all is False


def test_delete_route_command_creation_with_all_mode():
    """Test creating DeleteRouteCommand with ALL mode."""
    cmd = DeleteRouteCommand("GND", delete_all=True)
    assert cmd.net_name == "GND"
    assert cmd.position is None
    assert cmd.delete_all is True


def test_delete_route_command_validate_net_not_found():
    """Test validation fails when net doesn't exist."""
    cmd = DeleteRouteCommand("NONEXISTENT", position=(10.0, 20.0))
    board = Board()
    error = cmd.validate(board)
    assert error is not None
    assert "ERROR:" in error
    assert "not found" in error.lower()
    assert "NONEXISTENT" in error


def test_delete_route_command_validate_success_with_position(sample_board):
    """Test validation succeeds with valid position."""
    cmd = DeleteRouteCommand("GND", position=(10.0, 20.0))
    error = cmd.validate(sample_board)
    assert error is None


def test_delete_route_command_validate_success_with_all(sample_board):
    """Test validation succeeds with ALL mode."""
    cmd = DeleteRouteCommand("GND", delete_all=True)
    error = cmd.validate(sample_board)
    assert error is None


def test_delete_route_command_execute_delete_by_position(sample_board):
    """Test executing delete at specific position."""
    cmd = DeleteRouteCommand("GND", position=(10.0, 20.0))
    result = cmd.execute(sample_board)

    assert "OK:" in result
    assert "Deleted 1 segment" in result
    assert "GND" in result

    # Verify segment was removed
    net = sample_board.nets["GND"]
    assert len(net.segments) == 2  # Started with 3, removed 1


def test_delete_route_command_execute_delete_by_position_near(sample_board):
    """Test executing delete with position near segment endpoint."""
    # Position is slightly off from exact (10.0, 20.0) but within tolerance
    cmd = DeleteRouteCommand("GND", position=(10.3, 20.4))
    result = cmd.execute(sample_board)

    assert "OK:" in result
    assert "Deleted 1 segment" in result

    net = sample_board.nets["GND"]
    assert len(net.segments) == 2


def test_delete_route_command_execute_no_segment_found():
    """Test error when no segment found near position."""
    board = Board()
    net = Net(name="GND", code="1")
    seg = TraceSegment("GND", (10.0, 20.0), (30.0, 40.0), "F.Cu", 0.25)
    net.add_segment(seg)
    board.add_net(net)

    # Position far from any segment
    cmd = DeleteRouteCommand("GND", position=(100.0, 100.0))
    result = cmd.execute(board)

    assert "ERROR:" in result
    assert "No segment found near" in result


def test_delete_route_command_execute_delete_all(sample_board):
    """Test executing delete all segments."""
    cmd = DeleteRouteCommand("GND", delete_all=True)
    result = cmd.execute(sample_board)

    assert "OK:" in result
    assert "Deleted 3 segments" in result
    assert "GND" in result

    # Verify all segments were removed
    net = sample_board.nets["GND"]
    assert len(net.segments) == 0


def test_delete_route_command_execute_delete_all_no_segments():
    """Test delete all when net has no segments."""
    board = Board()
    net = Net(name="EMPTY", code="99")
    board.add_net(net)

    cmd = DeleteRouteCommand("EMPTY", delete_all=True)
    result = cmd.execute(board)

    assert "OK:" in result
    assert "Deleted 0 segments" in result


def test_delete_route_command_undo_single_segment(sample_board):
    """Test undo restores single deleted segment."""
    cmd = DeleteRouteCommand("GND", position=(10.0, 20.0))
    cmd.execute(sample_board)

    net = sample_board.nets["GND"]
    assert len(net.segments) == 2

    result = cmd.undo(sample_board)
    assert "OK:" in result
    assert len(net.segments) == 3


def test_delete_route_command_undo_all_segments(sample_board):
    """Test undo restores all deleted segments."""
    cmd = DeleteRouteCommand("GND", delete_all=True)
    cmd.execute(sample_board)

    net = sample_board.nets["GND"]
    assert len(net.segments) == 0

    result = cmd.undo(sample_board)
    assert "OK:" in result
    assert len(net.segments) == 3

    # Verify segments are restored correctly
    assert net.segments[0].start == (10.0, 20.0)
    assert net.segments[1].start == (30.0, 40.0)
    assert net.segments[2].start == (50.0, 60.0)


def test_parser_can_parse_delete_route_at():
    """Test parser handles DELETE_ROUTE with AT syntax."""
    parser = CommandParser()
    cmd = parser.parse("DELETE_ROUTE NET GND AT 10 20")

    assert isinstance(cmd, DeleteRouteCommand)
    assert cmd.net_name == "GND"
    assert cmd.position == (10.0, 20.0)
    assert cmd.delete_all is False


def test_parser_can_parse_delete_route_all():
    """Test parser handles DELETE_ROUTE with ALL syntax."""
    parser = CommandParser()
    cmd = parser.parse("DELETE_ROUTE NET GND ALL")

    assert isinstance(cmd, DeleteRouteCommand)
    assert cmd.net_name == "GND"
    assert cmd.position is None
    assert cmd.delete_all is True


def test_parser_can_parse_delete_route_quoted_name():
    """Test parser handles quoted net names."""
    parser = CommandParser()
    cmd = parser.parse('DELETE_ROUTE NET "signal with spaces" AT 50 60')

    assert isinstance(cmd, DeleteRouteCommand)
    assert cmd.net_name == "signal with spaces"


def test_delete_route_command_full_workflow(sample_board):
    """Test complete workflow: parse, validate, execute, undo."""
    parser = CommandParser()
    cmd = parser.parse("DELETE_ROUTE NET GND AT 30 40")

    assert cmd is not None
    assert cmd.validate(sample_board) is None

    result = cmd.execute(sample_board)
    assert "OK:" in result

    net = sample_board.nets["GND"]
    assert len(net.segments) == 2

    # Undo
    cmd.undo(sample_board)
    assert len(net.segments) == 3


def test_delete_route_command_multiple_deletes(sample_board):
    """Test deleting multiple segments one by one."""
    net = sample_board.nets["GND"]
    assert len(net.segments) == 3

    cmd1 = DeleteRouteCommand("GND", position=(10.0, 20.0))
    cmd1.execute(sample_board)
    assert len(net.segments) == 2

    cmd2 = DeleteRouteCommand("GND", position=(30.0, 40.0))
    cmd2.execute(sample_board)
    assert len(net.segments) == 1

    cmd3 = DeleteRouteCommand("GND", position=(50.0, 60.0))
    cmd3.execute(sample_board)
    assert len(net.segments) == 0
