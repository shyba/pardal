# tests/test_show_board_routing.py
import pytest
from pcb_tool.commands import ShowBoardCommand
from pcb_tool.command_parser import CommandParser
from pcb_tool.data_model import Board, Component, Net, TraceSegment, Via


@pytest.fixture
def board_with_routing():
    """Create a board with components, segments, and vias."""
    board = Board()

    # Add components
    board.add_component(Component(
        ref="U1", value="IC", footprint="DIP-8",
        position=(10.0, 10.0), rotation=0.0
    ))
    board.add_component(Component(
        ref="R1", value="10k", footprint="R_0805",
        position=(30.0, 10.0), rotation=0.0
    ))

    # Add net with routing
    vcc_net = Net(name="VCC", code="1")
    vcc_net.add_connection("U1", "8")
    vcc_net.add_connection("R1", "1")

    # Add segments
    vcc_net.add_segment(TraceSegment(
        net_name="VCC",
        start=(10.0, 10.0),
        end=(30.0, 10.0),
        layer="F.Cu",
        width=0.25
    ))
    vcc_net.add_segment(TraceSegment(
        net_name="VCC",
        start=(30.0, 10.0),
        end=(50.0, 10.0),
        layer="F.Cu",
        width=0.25
    ))

    # Add via
    vcc_net.add_via(Via(
        net_name="VCC",
        position=(30.0, 10.0),
        size=0.8,
        drill=0.4,
        layers=("F.Cu", "B.Cu")
    ))

    board.add_net(vcc_net)

    return board


@pytest.fixture
def board_without_routing():
    """Create a board with components but no routing."""
    board = Board()

    board.add_component(Component(
        ref="U1", value="IC", footprint="DIP-8",
        position=(10.0, 10.0), rotation=0.0
    ))
    board.add_component(Component(
        ref="R1", value="10k", footprint="R_0805",
        position=(30.0, 10.0), rotation=0.0
    ))

    # Add net without routing
    vcc_net = Net(name="VCC", code="1")
    vcc_net.add_connection("U1", "8")
    vcc_net.add_connection("R1", "1")
    board.add_net(vcc_net)

    return board


def test_show_board_command_with_routing_includes_legend(board_with_routing):
    """Test SHOW BOARD includes routing legend when routing exists."""
    cmd = ShowBoardCommand()
    result = cmd.execute(board_with_routing)

    # Should include routing info in legend
    assert "Routing:" in result or "routing" in result.lower()


def test_show_board_command_with_routing_shows_segment_count(board_with_routing):
    """Test routing legend shows segment count."""
    cmd = ShowBoardCommand()
    result = cmd.execute(board_with_routing)

    # Should mention segments
    assert "2 segment" in result or "segments: 2" in result.lower()


def test_show_board_command_with_routing_shows_via_count(board_with_routing):
    """Test routing legend shows via count."""
    cmd = ShowBoardCommand()
    result = cmd.execute(board_with_routing)

    # Should mention vias
    assert "1 via" in result or "vias: 1" in result.lower()


def test_show_board_command_without_routing_no_legend(board_without_routing):
    """Test SHOW BOARD doesn't show routing legend when no routing exists."""
    cmd = ShowBoardCommand()
    result = cmd.execute(board_without_routing)

    # Should not have routing legend, or show 0 segments/vias
    if "Routing:" in result:
        assert "0 segment" in result or "segments: 0" in result.lower()


def test_show_board_command_with_routing_shows_via_markers(board_with_routing):
    """Test vias are shown as markers on the board grid."""
    cmd = ShowBoardCommand()
    result = cmd.execute(board_with_routing)

    # Should include V marker or asterisk for via position
    # The via is at (30.0, 10.0), should be marked somehow
    assert "V" in result or "*" in result


def test_show_board_command_preserves_component_positions(board_with_routing):
    """Test routing overlay doesn't obscure component positions."""
    cmd = ShowBoardCommand()
    result = cmd.execute(board_with_routing)

    # Component references should still be visible
    assert "U1" in result
    assert "R1" in result


def test_show_board_command_empty_board_no_routing():
    """Test SHOW BOARD handles empty board gracefully."""
    board = Board()
    cmd = ShowBoardCommand()
    result = cmd.execute(board)

    assert "No components" in result or "empty board" in result.lower()


def test_show_board_command_multiple_nets_with_routing():
    """Test SHOW BOARD handles multiple nets with routing."""
    board = Board()

    # Add components
    board.add_component(Component(
        ref="U1", value="IC", footprint="DIP-8",
        position=(10.0, 10.0), rotation=0.0
    ))
    board.add_component(Component(
        ref="R1", value="10k", footprint="R_0805",
        position=(30.0, 10.0), rotation=0.0
    ))

    # Net 1 with routing
    vcc_net = Net(name="VCC", code="1")
    vcc_net.add_segment(TraceSegment(
        net_name="VCC",
        start=(10.0, 10.0),
        end=(30.0, 10.0),
        layer="F.Cu",
        width=0.25
    ))
    board.add_net(vcc_net)

    # Net 2 with routing
    gnd_net = Net(name="GND", code="2")
    gnd_net.add_segment(TraceSegment(
        net_name="GND",
        start=(15.0, 15.0),
        end=(25.0, 15.0),
        layer="F.Cu",
        width=0.25
    ))
    gnd_net.add_via(Via(
        net_name="GND",
        position=(20.0, 15.0),
        size=0.8,
        drill=0.4,
        layers=("F.Cu", "B.Cu")
    ))
    board.add_net(gnd_net)

    cmd = ShowBoardCommand()
    result = cmd.execute(board)

    # Should show total counts from both nets (1 + 1 = 2 segments, 0 + 1 = 1 via)
    assert "2 segment" in result or "segments: 2" in result.lower()
    assert "1 via" in result or "vias: 1" in result.lower()


def test_show_board_command_routing_full_workflow(board_with_routing):
    """Test full workflow with parser for board with routing."""
    parser = CommandParser()
    cmd = parser.parse("SHOW BOARD")

    assert isinstance(cmd, ShowBoardCommand)
    assert cmd.validate(board_with_routing) is None

    result = cmd.execute(board_with_routing)

    # Verify all elements are present
    assert "Board:" in result or "board" in result.lower()
    assert "U1" in result
    assert "R1" in result
    # Should show routing info
    assert "segment" in result.lower() or "via" in result.lower()


def test_show_board_command_with_overlapping_routes():
    """Test SHOW BOARD handles overlapping route positions."""
    board = Board()

    # Add component
    board.add_component(Component(
        ref="U1", value="IC", footprint="DIP-8",
        position=(10.0, 10.0), rotation=0.0
    ))

    # Add multiple segments passing through same position
    net = Net(name="VCC", code="1")
    net.add_segment(TraceSegment(
        net_name="VCC",
        start=(10.0, 10.0),
        end=(20.0, 10.0),
        layer="F.Cu",
        width=0.25
    ))
    net.add_segment(TraceSegment(
        net_name="VCC",
        start=(20.0, 10.0),
        end=(30.0, 10.0),
        layer="F.Cu",
        width=0.25
    ))
    board.add_net(net)

    cmd = ShowBoardCommand()
    result = cmd.execute(board)

    # Should not crash and should show component
    assert "U1" in result
    assert "2 segment" in result or "segments: 2" in result.lower()
