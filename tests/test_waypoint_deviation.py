"""
Tests for waypoint deviation detection in RouteCommand.

Tests the _check_waypoint_deviation() method which warns users when
coordinate-based routing deviates significantly (>1mm) from intended positions.
"""

import pytest
from io import StringIO
import sys
from pcb_tool.commands import RouteCommand
from pcb_tool.data_model import Board, Net, Component, Pad


@pytest.fixture
def sample_board_with_components():
    """Create a board with components and nets for testing waypoint routing."""
    board = Board()

    # Create nets
    board.add_net(Net(name="GND", code="1", track_width=0.25))
    board.add_net(Net(name="VCC", code="2", track_width=0.25))

    # Create component with pads on GND net
    comp1 = Component(ref="C1", value="10uF", footprint="CAP-0805", position=(10.0, 20.0), rotation=0)
    comp1.pads = [
        Pad(number=1, position_offset=(-0.95, 0), size=(1.3, 1.5), net_name="GND"),
        Pad(number=2, position_offset=(0.95, 0), size=(1.3, 1.5), net_name="VCC")
    ]
    board.add_component(comp1)

    # Add connection to nets
    board.nets["GND"].connections.append(("C1", "1"))
    board.nets["VCC"].connections.append(("C1", "2"))

    # Create another component
    comp2 = Component(ref="R1", value="10k", footprint="RES-0805", position=(30.0, 20.0), rotation=0)
    comp2.pads = [
        Pad(number=1, position_offset=(-0.95, 0), size=(1.3, 1.5), net_name="GND"),
        Pad(number=2, position_offset=(0.95, 0), size=(1.3, 1.5), net_name="VCC")
    ]
    board.add_component(comp2)

    board.nets["GND"].connections.append(("R1", "1"))
    board.nets["VCC"].connections.append(("R1", "2"))

    return board


def capture_stdout(func):
    """Decorator to capture stdout during function execution."""
    def wrapper(*args, **kwargs):
        old_stdout = sys.stdout
        sys.stdout = captured_output = StringIO()
        try:
            result = func(*args, **kwargs)
            output = captured_output.getvalue()
            return result, output
        finally:
            sys.stdout = old_stdout
    return wrapper


def test_component_pin_notation_does_not_trigger_warning(sample_board_with_components):
    """Component.pin notation should NOT trigger waypoint deviation warnings.

    When using component.pin notation like "C1.1", the system directly resolves
    to the pad position, so there's no deviation to warn about.
    """
    cmd = RouteCommand("GND", "C1.1", "R1.1", layer="F.Cu")

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


def test_coordinate_tuple_small_deviation_no_warning(sample_board_with_components):
    """Coordinate tuples with <1mm deviation should NOT trigger warnings.

    When coordinate-based routing results in <1mm deviation from intended position,
    this is considered acceptable and no warning should be shown.
    """
    # C1.1 is at (10 - 0.95, 20) = (9.05, 20.0)
    # Specify coordinates very close to actual pad: (9.1, 20.0) - only 0.05mm deviation
    cmd = RouteCommand("GND", (9.1, 20.0), (29.05, 20.0), layer="F.Cu")

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


def test_coordinate_tuple_exact_match_no_warning(sample_board_with_components):
    """Coordinate tuples that exactly match pad positions should NOT trigger warnings."""
    # C1.1 is at (9.05, 20.0) - specify exact coordinates
    cmd = RouteCommand("GND", (9.05, 20.0), (29.05, 20.0), layer="F.Cu")

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


def test_coordinate_tuple_large_deviation_triggers_warning(sample_board_with_components):
    """Coordinate tuples with >1mm deviation SHOULD trigger warnings.

    When coordinate-based routing deviates significantly from intended position,
    user should be warned that waypoint routing may not be working as expected.
    """
    # C1.1 is at (9.05, 20.0)
    # Specify coordinates 5mm away: (14.0, 20.0) - 5mm deviation
    cmd = RouteCommand("GND", (14.0, 20.0), (29.05, 20.0), layer="F.Cu")

    old_stdout = sys.stdout
    sys.stdout = captured_output = StringIO()

    try:
        result = cmd.execute(sample_board_with_components)
        output = captured_output.getvalue()
    finally:
        sys.stdout = old_stdout

    # Should succeed but with warning
    assert "OK:" in result
    assert "WARNING" in output
    assert "deviation" in output.lower()
    assert "start" in output.lower()  # Should indicate start position


def test_warning_message_format_includes_required_info(sample_board_with_components):
    """Warning message should include all required information for debugging.

    The warning should show:
    - Intended coordinates
    - Actual coordinates
    - Deviation magnitude and components (ΔX, ΔY)
    - Net name
    - Layer
    - Helpful tip about using component.pin notation
    """
    # Create significant deviation at start position
    cmd = RouteCommand("GND", (15.0, 25.0), (29.05, 20.0), layer="F.Cu")

    old_stdout = sys.stdout
    sys.stdout = captured_output = StringIO()

    try:
        result = cmd.execute(sample_board_with_components)
        output = captured_output.getvalue()
    finally:
        sys.stdout = old_stdout

    # Verify warning contains all required elements
    assert "WARNING" in output
    assert "Intended:" in output
    assert "(15.00, 25.00)" in output  # Intended coordinates
    assert "Actual:" in output
    assert "(9.05, 20.00)" in output  # Actual pad position
    assert "Deviation:" in output
    assert "mm" in output
    assert "ΔX=" in output or "delta" in output.lower()
    assert "ΔY=" in output or "delta" in output.lower()
    assert "GND" in output  # Net name
    assert "F.Cu" in output  # Layer
    assert "TIP:" in output or "component.pin" in output  # Helpful tip


def test_deviation_1_1mm_triggers_warning(sample_board_with_components):
    """Deviation of exactly 1.1mm should trigger warning (just over threshold)."""
    # C1.1 is at (9.05, 20.0)
    # Place waypoint 1.1mm away
    cmd = RouteCommand("GND", (10.15, 20.0), (29.05, 20.0), layer="F.Cu")

    old_stdout = sys.stdout
    sys.stdout = captured_output = StringIO()

    try:
        result = cmd.execute(sample_board_with_components)
        output = captured_output.getvalue()
    finally:
        sys.stdout = old_stdout

    assert "WARNING" in output
    assert "deviation" in output.lower()


def test_deviation_5mm_triggers_warning(sample_board_with_components):
    """Deviation of 5mm should trigger warning."""
    # C1.1 is at (9.05, 20.0)
    # Place waypoint 5mm away in Y direction
    cmd = RouteCommand("GND", (9.05, 25.0), (29.05, 20.0), layer="F.Cu")

    old_stdout = sys.stdout
    sys.stdout = captured_output = StringIO()

    try:
        result = cmd.execute(sample_board_with_components)
        output = captured_output.getvalue()
    finally:
        sys.stdout = old_stdout

    assert "WARNING" in output
    assert "deviation" in output.lower()
    # Should show approximately 5mm deviation
    assert "5.0" in output or "5.00" in output


def test_deviation_20mm_triggers_warning(sample_board_with_components):
    """Deviation of 20mm should trigger warning (large deviation)."""
    # C1.1 is at (9.05, 20.0), R1.1 is at (29.05, 20.0)
    # Place start waypoint 20mm away from C1.1 in X direction
    cmd = RouteCommand("GND", (29.05, 20.0), (49.05, 20.0), layer="F.Cu")

    old_stdout = sys.stdout
    sys.stdout = captured_output = StringIO()

    try:
        result = cmd.execute(sample_board_with_components)
        output = captured_output.getvalue()
    finally:
        sys.stdout = old_stdout

    assert "WARNING" in output
    assert "deviation" in output.lower()
    # Should show approximately 20mm deviation
    assert "20.0" in output or "20.00" in output


def test_end_position_deviation_triggers_warning(sample_board_with_components):
    """Deviation at END position should also trigger warnings."""
    # R1.1 is at (29.05, 20.0)
    # Use correct start, but wrong end coordinates
    cmd = RouteCommand("GND", "C1.1", (35.0, 20.0), layer="F.Cu")

    old_stdout = sys.stdout
    sys.stdout = captured_output = StringIO()

    try:
        result = cmd.execute(sample_board_with_components)
        output = captured_output.getvalue()
    finally:
        sys.stdout = old_stdout

    assert "WARNING" in output
    assert "end" in output.lower()  # Should indicate end position


def test_both_positions_deviation_triggers_two_warnings(sample_board_with_components):
    """Deviation at both start AND end positions should trigger two warnings."""
    # Both positions significantly off
    cmd = RouteCommand("GND", (15.0, 20.0), (35.0, 20.0), layer="F.Cu")

    old_stdout = sys.stdout
    sys.stdout = captured_output = StringIO()

    try:
        result = cmd.execute(sample_board_with_components)
        output = captured_output.getvalue()
    finally:
        sys.stdout = old_stdout

    # Should have two warnings - one for start, one for end
    warning_count = output.count("WARNING")
    assert warning_count == 2
    assert "start" in output.lower()
    assert "end" in output.lower()


def test_diagonal_deviation_calculated_correctly(sample_board_with_components):
    """Test that diagonal deviation (both X and Y) is calculated correctly using Euclidean distance."""
    # C1.1 is at (9.05, 20.0)
    # Place waypoint with both X and Y deviation: 3mm in X, 4mm in Y
    # Total deviation should be sqrt(3^2 + 4^2) = 5mm
    cmd = RouteCommand("GND", (12.05, 24.0), (29.05, 20.0), layer="F.Cu")

    old_stdout = sys.stdout
    sys.stdout = captured_output = StringIO()

    try:
        result = cmd.execute(sample_board_with_components)
        output = captured_output.getvalue()
    finally:
        sys.stdout = old_stdout

    assert "WARNING" in output
    # Should show total deviation of ~5mm
    assert "5.0" in output or "5.00" in output
    # Should show individual components
    assert "ΔX=3.00" in output or "3.0" in output
    assert "ΔY=4.00" in output or "4.0" in output


def test_back_layer_routing_with_deviation(sample_board_with_components):
    """Deviation warnings should work on back layer (B.Cu) as well."""
    cmd = RouteCommand("GND", (15.0, 20.0), (29.05, 20.0), layer="B.Cu")

    old_stdout = sys.stdout
    sys.stdout = captured_output = StringIO()

    try:
        result = cmd.execute(sample_board_with_components)
        output = captured_output.getvalue()
    finally:
        sys.stdout = old_stdout

    assert "WARNING" in output
    assert "B.Cu" in output  # Should mention back layer


def test_deviation_at_exactly_1mm_no_warning(sample_board_with_components):
    """Deviation of exactly 1.0mm should NOT trigger warning (at threshold)."""
    # C1.1 is at (9.05, 20.0)
    # Place waypoint exactly 1.0mm away
    cmd = RouteCommand("GND", (10.05, 20.0), (29.05, 20.0), layer="F.Cu")

    old_stdout = sys.stdout
    sys.stdout = captured_output = StringIO()

    try:
        result = cmd.execute(sample_board_with_components)
        output = captured_output.getvalue()
    finally:
        sys.stdout = old_stdout

    # Should NOT warn at exactly 1.0mm (threshold is > 1.0)
    assert "WARNING" not in output
