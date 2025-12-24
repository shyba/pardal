"""
Tests for multi-segment routing with VIA waypoints.

Tests the enhanced ROUTE command that supports multiple VIA waypoints
for creating routing paths that avoid obstacles.
"""

import pytest
from io import StringIO
import sys
from pcb_tool.commands import RouteCommand
from pcb_tool.command_parser import CommandParser
from pcb_tool.data_model import Board, Net, Component, Pad


@pytest.fixture
def sample_board():
    """Create a board with test nets for routing."""
    board = Board()
    net1 = Net(name="GND", code="1", track_width=0.25)
    net2 = Net(name="VCC", code="2", track_width=0.5)
    board.add_net(net1)
    board.add_net(net2)
    return board


@pytest.fixture
def sample_board_with_components():
    """Create a board with components and nets for pin-based routing."""
    board = Board()

    # Create nets
    board.add_net(Net(name="GND", code="1", track_width=0.25))
    board.add_net(Net(name="VCC", code="2", track_width=0.25))

    # Create components with pads
    comp1 = Component(ref="J1", value="CONN", footprint="HDR-1x3", position=(10.0, 5.0), rotation=0)
    comp1.pads = [
        Pad(number=1, position_offset=(0, 0), size=(1.5, 1.5), net_name="VCC"),
        Pad(number=2, position_offset=(2.54, 0), size=(1.5, 1.5), net_name="GND"),
        Pad(number=3, position_offset=(5.08, 0), size=(1.5, 1.5), net_name="GND")
    ]
    board.add_component(comp1)

    comp2 = Component(ref="C1", value="10uF", footprint="CAP-0805", position=(60.0, 10.0), rotation=0)
    comp2.pads = [
        Pad(number=1, position_offset=(-0.95, 0), size=(1.3, 1.5), net_name="VCC"),
        Pad(number=2, position_offset=(0.95, 0), size=(1.3, 1.5), net_name="GND")
    ]
    board.add_component(comp2)

    # Add connections to nets
    board.nets["GND"].connections.append(("J1", "3"))
    board.nets["GND"].connections.append(("C1", "2"))
    board.nets["VCC"].connections.append(("J1", "1"))
    board.nets["VCC"].connections.append(("C1", "1"))

    return board


# ============================================================================
# Parser Tests
# ============================================================================

def test_parser_extracts_single_via():
    """Test parser can extract a single VIA waypoint."""
    parser = CommandParser()
    cmd = parser.parse("ROUTE NET GND FROM 0 0 VIA (25, 5) TO 50 10")

    assert isinstance(cmd, RouteCommand)
    assert cmd.net_name == "GND"
    assert cmd.start_pos == (0.0, 0.0)
    assert cmd.end_pos == (50.0, 10.0)
    assert cmd.waypoints is not None
    assert len(cmd.waypoints) == 1
    assert cmd.waypoints[0] == (25.0, 5.0)


def test_parser_extracts_multiple_vias():
    """Test parser can extract multiple VIA waypoints."""
    parser = CommandParser()
    cmd = parser.parse("ROUTE NET GND FROM 0 0 VIA (25, 5) VIA (40, 5) VIA (55, 10) TO 70 15")

    assert isinstance(cmd, RouteCommand)
    assert cmd.waypoints is not None
    assert len(cmd.waypoints) == 3
    assert cmd.waypoints[0] == (25.0, 5.0)
    assert cmd.waypoints[1] == (40.0, 5.0)
    assert cmd.waypoints[2] == (55.0, 10.0)


def test_parser_extracts_vias_with_decimals():
    """Test parser handles VIA coordinates with decimal values."""
    parser = CommandParser()
    cmd = parser.parse("ROUTE NET VCC FROM 10.5 20.3 VIA (35.75, 12.25) TO 60.0 5.5")

    assert cmd.waypoints is not None
    assert len(cmd.waypoints) == 1
    assert cmd.waypoints[0] == (35.75, 12.25)


def test_parser_no_via_returns_none_waypoints():
    """Test parser returns None for waypoints when no VIA clauses present."""
    parser = CommandParser()
    cmd = parser.parse("ROUTE NET GND FROM 0 0 TO 50 10")

    assert isinstance(cmd, RouteCommand)
    assert cmd.waypoints is None


def test_parser_via_with_layer_and_width():
    """Test parser handles VIA waypoints with LAYER and WIDTH parameters."""
    parser = CommandParser()
    cmd = parser.parse("ROUTE NET GND FROM 0 0 VIA (25, 5) VIA (40, 5) TO 60 10 LAYER B.Cu WIDTH 1.0")

    assert cmd.waypoints is not None
    assert len(cmd.waypoints) == 2
    assert cmd.layer == "B.Cu"
    assert cmd.width == 1.0


def test_parser_via_with_component_pin_notation():
    """Test parser handles VIA waypoints with component.pin start/end positions."""
    parser = CommandParser()
    cmd = parser.parse("ROUTE NET GND FROM J1.3 VIA (25, 5) VIA (40, 5) VIA (55, 10) TO C1.2")

    assert cmd.start_pos == "J1.3"
    assert cmd.end_pos == "C1.2"
    assert cmd.waypoints is not None
    assert len(cmd.waypoints) == 3


# ============================================================================
# Segment Creation Tests
# ============================================================================

def test_route_with_waypoints_creates_segments(sample_board):
    """Test that waypoints create N+1 segments for N waypoints."""
    cmd = RouteCommand("GND", (0.0, 0.0), (60.0, 10.0), waypoints=[(20.0, 5.0), (40.0, 5.0)])
    result = cmd.execute(sample_board)

    assert "OK:" in result
    assert "3 segments" in result  # N+1 = 2+1 = 3 segments

    net = sample_board.nets["GND"]
    assert len(net.segments) == 3


def test_route_with_single_waypoint_creates_two_segments(sample_board):
    """Test that 1 waypoint creates 2 segments."""
    cmd = RouteCommand("GND", (0.0, 0.0), (50.0, 10.0), waypoints=[(25.0, 5.0)])
    cmd.execute(sample_board)

    net = sample_board.nets["GND"]
    assert len(net.segments) == 2


def test_route_with_five_waypoints_creates_six_segments(sample_board):
    """Test that 5 waypoints create 6 segments."""
    waypoints = [(10.0, 5.0), (20.0, 5.0), (30.0, 5.0), (40.0, 5.0), (50.0, 5.0)]
    cmd = RouteCommand("GND", (0.0, 0.0), (60.0, 10.0), waypoints=waypoints)
    cmd.execute(sample_board)

    net = sample_board.nets["GND"]
    assert len(net.segments) == 6


def test_segment_connectivity_with_waypoints(sample_board):
    """Test that segments connect properly through waypoints."""
    waypoints = [(20.0, 5.0), (40.0, 5.0)]
    cmd = RouteCommand("GND", (0.0, 0.0), (60.0, 10.0), waypoints=waypoints)
    cmd.execute(sample_board)

    net = sample_board.nets["GND"]
    segments = net.segments

    # Verify segment chain: start -> wp1 -> wp2 -> end
    assert segments[0].start == (0.0, 0.0)
    assert segments[0].end == (20.0, 5.0)

    assert segments[1].start == (20.0, 5.0)
    assert segments[1].end == (40.0, 5.0)

    assert segments[2].start == (40.0, 5.0)
    assert segments[2].end == (60.0, 10.0)


def test_all_segments_use_same_layer_and_width(sample_board):
    """Test that all segments in multi-segment route use the same layer and width."""
    waypoints = [(20.0, 5.0), (40.0, 5.0)]
    cmd = RouteCommand("GND", (0.0, 0.0), (60.0, 10.0), layer="B.Cu", width=0.5, waypoints=waypoints)
    cmd.execute(sample_board)

    net = sample_board.nets["GND"]
    for segment in net.segments:
        assert segment.layer == "B.Cu"
        assert segment.width == 0.5


def test_multi_segment_route_with_component_pins(sample_board_with_components):
    """Test multi-segment routing from component.pin to component.pin with waypoints."""
    waypoints = [(25.0, 5.0), (40.0, 5.0), (55.0, 10.0)]
    cmd = RouteCommand("GND", "J1.3", "C1.2", waypoints=waypoints)
    result = cmd.execute(sample_board_with_components)

    assert "OK:" in result
    net = sample_board_with_components.nets["GND"]
    assert len(net.segments) == 4  # 3 waypoints = 4 segments


# ============================================================================
# Backward Compatibility Tests
# ============================================================================

def test_route_without_waypoints_still_works(sample_board):
    """Test that routes without waypoints still work (backward compatibility)."""
    cmd = RouteCommand("GND", (0.0, 0.0), (50.0, 10.0))
    result = cmd.execute(sample_board)

    assert "OK:" in result
    net = sample_board.nets["GND"]
    assert len(net.segments) == 1
    assert net.segments[0].start == (0.0, 0.0)
    assert net.segments[0].end == (50.0, 10.0)


def test_route_with_none_waypoints_still_works(sample_board):
    """Test that explicitly passing waypoints=None works."""
    cmd = RouteCommand("GND", (0.0, 0.0), (50.0, 10.0), waypoints=None)
    result = cmd.execute(sample_board)

    assert "OK:" in result
    net = sample_board.nets["GND"]
    assert len(net.segments) == 1


def test_route_with_empty_waypoints_list_still_works(sample_board):
    """Test that passing empty waypoints list works as single-segment route."""
    cmd = RouteCommand("GND", (0.0, 0.0), (50.0, 10.0), waypoints=[])
    result = cmd.execute(sample_board)

    assert "OK:" in result
    net = sample_board.nets["GND"]
    assert len(net.segments) == 1


# ============================================================================
# Deviation Warning Tests
# ============================================================================

def test_via_routes_no_deviation_warning(sample_board_with_components):
    """Test that VIA-based routes do NOT trigger waypoint deviation warnings."""
    # J1.3 is at (15.08, 5.0), but we specify different coordinates
    # This would normally trigger deviation warning, but VIA routes should skip it
    waypoints = [(25.0, 5.0), (40.0, 5.0)]
    cmd = RouteCommand("GND", (20.0, 5.0), (65.0, 10.0), waypoints=waypoints)

    # Capture stdout
    old_stdout = sys.stdout
    sys.stdout = captured_output = StringIO()

    try:
        result = cmd.execute(sample_board_with_components)
        output = captured_output.getvalue()
    finally:
        sys.stdout = old_stdout

    # Should succeed without warnings
    assert "OK:" in result
    assert "WARNING" not in output
    assert "deviation" not in output.lower()


def test_via_routes_skip_deviation_logic():
    """Test that VIA-based routes skip deviation detection logic entirely.

    This test verifies that routes with explicit VIA waypoints do not
    invoke the deviation checking code path, regardless of coordinate values.
    """
    board = Board()
    board.add_net(Net(name="GND", code="1", track_width=0.25))

    # Create components (coordinates don't matter for this test since VIA routes skip deviation)
    comp1 = Component(ref="C1", value="10uF", footprint="CAP-0805", position=(10.0, 20.0), rotation=0)
    comp1.pads = [
        Pad(number=1, position_offset=(-0.95, 0), size=(1.3, 1.5), net_name="GND"),
        Pad(number=2, position_offset=(0.95, 0), size=(1.3, 1.5), net_name="VCC")
    ]
    board.add_component(comp1)

    board.nets["GND"].connections.append(("C1", "1"))

    # Create route with VIA waypoints - deviation checking should be skipped
    waypoints = [(25.0, 5.0), (40.0, 5.0)]
    cmd = RouteCommand("GND", (15.0, 20.0), (65.0, 10.0), waypoints=waypoints)

    old_stdout = sys.stdout
    sys.stdout = captured_output = StringIO()

    try:
        result = cmd.execute(board)
        output = captured_output.getvalue()
    finally:
        sys.stdout = old_stdout

    # Verify success without deviation warnings
    assert "OK:" in result
    assert "WARNING" not in output
    assert "deviation" not in output.lower()


# ============================================================================
# Undo Tests
# ============================================================================

def test_undo_multi_segment_route(sample_board):
    """Test that undo removes all segments from multi-segment route."""
    waypoints = [(20.0, 5.0), (40.0, 5.0)]
    cmd = RouteCommand("GND", (0.0, 0.0), (60.0, 10.0), waypoints=waypoints)
    cmd.execute(sample_board)

    net = sample_board.nets["GND"]
    assert len(net.segments) == 3

    result = cmd.undo(sample_board)
    assert "OK:" in result
    assert len(net.segments) == 0


def test_undo_single_segment_route_backward_compatible(sample_board):
    """Test that undo still works for single-segment routes (backward compatibility)."""
    cmd = RouteCommand("GND", (0.0, 0.0), (50.0, 10.0))
    cmd.execute(sample_board)

    net = sample_board.nets["GND"]
    assert len(net.segments) == 1

    result = cmd.undo(sample_board)
    assert "OK:" in result
    assert len(net.segments) == 0


# ============================================================================
# Integration Tests
# ============================================================================

def test_full_workflow_parser_to_execution(sample_board_with_components):
    """Test complete workflow: parse VIA command, validate, execute."""
    parser = CommandParser()
    cmd = parser.parse("ROUTE NET GND FROM J1.3 VIA (25, 5) VIA (40, 5) VIA (55, 10) TO C1.2 LAYER B.Cu WIDTH 1.0")

    assert cmd is not None
    assert cmd.validate(sample_board_with_components) is None

    result = cmd.execute(sample_board_with_components)
    assert "OK:" in result

    net = sample_board_with_components.nets["GND"]
    assert len(net.segments) == 4  # 3 waypoints = 4 segments

    # Verify all segments on correct layer with correct width
    for segment in net.segments:
        assert segment.layer == "B.Cu"
        assert segment.width == 1.0


def test_multiple_multi_segment_routes_on_same_net(sample_board):
    """Test adding multiple multi-segment routes to the same net."""
    # First route: 2 segments
    cmd1 = RouteCommand("GND", (0.0, 0.0), (30.0, 5.0), waypoints=[(15.0, 2.5)])
    cmd1.execute(sample_board)

    # Second route: 3 segments
    cmd2 = RouteCommand("GND", (40.0, 10.0), (70.0, 15.0), waypoints=[(50.0, 12.0), (60.0, 13.0)])
    cmd2.execute(sample_board)

    net = sample_board.nets["GND"]
    assert len(net.segments) == 5  # 2 + 3 = 5 segments total


def test_validate_net_exists_with_waypoints(sample_board):
    """Test validation fails when net doesn't exist, even with waypoints."""
    cmd = RouteCommand("NONEXISTENT", (0.0, 0.0), (50.0, 10.0), waypoints=[(25.0, 5.0)])
    error = cmd.validate(sample_board)

    assert error is not None
    assert "ERROR:" in error
    assert "not found" in error.lower()


def test_validate_layer_with_waypoints(sample_board):
    """Test validation fails with invalid layer, even with waypoints."""
    cmd = RouteCommand("GND", (0.0, 0.0), (50.0, 10.0), layer="Invalid.Cu", waypoints=[(25.0, 5.0)])
    board = Board()
    board.add_net(Net(name="GND", code="1"))
    error = cmd.validate(board)

    assert error is not None
    assert "ERROR:" in error
    assert "layer" in error.lower()
