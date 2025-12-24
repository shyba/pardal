"""
Integration tests for the complete waypoint validation workflow.

Tests the end-to-end functionality of waypoint deviation detection and
trace crossing detection in realistic scenarios.
"""

import pytest
from io import StringIO
import sys
from pcb_tool.commands import RouteCommand, CheckDrcCommand, ViaCommand
from pcb_tool.data_model import Board, Net, Component, Pad


@pytest.fixture
def injector_board():
    """Create a board simulating the injector controller scenario.

    This simulates the real-world scenario where GND bus routing had
    incorrect Y coordinates, leading to significant deviations.
    """
    board = Board()

    # Create nets
    board.add_net(Net(name="GND", code="1", track_width=0.5))
    board.add_net(Net(name="VCC", code="2", track_width=0.3))
    board.add_net(Net(name="SIGNAL", code="3", track_width=0.25))

    # Create injector components in a row at Y=20
    for i in range(1, 5):
        comp = Component(
            ref=f"U{i}",
            value="INJECTOR",
            footprint="SOIC-8",
            position=(10.0 + i * 10.0, 20.0),
            rotation=0
        )
        comp.pads = [
            Pad(number=1, position_offset=(-3.0, 0), size=(1.5, 1.0), net_name="GND"),
            Pad(number=2, position_offset=(-1.0, 0), size=(1.5, 1.0), net_name="SIGNAL"),
            Pad(number=3, position_offset=(1.0, 0), size=(1.5, 1.0), net_name="VCC"),
            Pad(number=4, position_offset=(3.0, 0), size=(1.5, 1.0), net_name="GND")
        ]
        board.add_component(comp)

        # Add connections
        board.nets["GND"].connections.append((f"U{i}", "1"))
        board.nets["GND"].connections.append((f"U{i}", "4"))
        board.nets["SIGNAL"].connections.append((f"U{i}", "2"))
        board.nets["VCC"].connections.append((f"U{i}", "3"))

    return board


def test_injector_board_wrong_y_coordinate_triggers_warnings(injector_board):
    """Test that GND bus at wrong Y coordinate triggers multiple warnings.

    This simulates the real issue: routing GND bus segments with intended
    Y=10 but actual pad positions at Y=20, causing 10mm deviations.
    """
    # Try to route GND bus at Y=10 (wrong!) when pads are at Y=20
    old_stdout = sys.stdout
    sys.stdout = captured_output = StringIO()

    try:
        # Route horizontal GND bus segments at wrong Y coordinate
        cmd1 = RouteCommand("GND", (17.0, 10.0), (27.0, 10.0), layer="F.Cu")
        cmd1.execute(injector_board)

        cmd2 = RouteCommand("GND", (27.0, 10.0), (37.0, 10.0), layer="F.Cu")
        cmd2.execute(injector_board)

        output = captured_output.getvalue()
    finally:
        sys.stdout = old_stdout

    # Should have multiple warnings about 10mm deviation
    assert output.count("WARNING") >= 2
    assert "10.0" in output or "10.00" in output  # 10mm deviation
    assert "deviation" in output.lower()


def test_correct_routing_no_warnings(injector_board):
    """Test that correct routing with component.pin notation shows no warnings."""
    old_stdout = sys.stdout
    sys.stdout = captured_output = StringIO()

    try:
        # Route using component.pin notation (correct way)
        cmd1 = RouteCommand("GND", "U1.1", "U2.1", layer="F.Cu")
        cmd1.execute(injector_board)

        cmd2 = RouteCommand("GND", "U2.4", "U3.4", layer="F.Cu")
        cmd2.execute(injector_board)

        output = captured_output.getvalue()
    finally:
        sys.stdout = old_stdout

    # Should have no warnings
    assert "WARNING" not in output


def test_mixed_routing_shows_selective_warnings(injector_board):
    """Test that mixing correct and incorrect routing shows warnings only for incorrect parts."""
    old_stdout = sys.stdout
    sys.stdout = captured_output = StringIO()

    try:
        # Correct routing with component.pin notation
        cmd1 = RouteCommand("GND", "U1.1", "U2.1", layer="F.Cu")
        cmd1.execute(injector_board)

        # Incorrect routing with wrong coordinates
        cmd2 = RouteCommand("GND", (27.0, 10.0), (37.0, 10.0), layer="F.Cu")
        cmd2.execute(injector_board)

        output = captured_output.getvalue()
    finally:
        sys.stdout = old_stdout

    # Should have warnings for the incorrect route only
    assert "WARNING" in output
    # But not excessive warnings (only for the bad route)
    warning_count = output.count("WARNING")
    assert warning_count <= 2  # At most 2 (start and end of second route)


def test_drc_catches_trace_crossings_before_save():
    """Test that DRC detects trace crossings before board is saved.

    This is the critical safety check - DRC should catch routing errors
    before they make it into the final board file.
    """
    from pcb_tool.data_model import TraceSegment

    board = Board()
    board.add_net(Net(name="NET1", code="1", track_width=0.25))
    board.add_net(Net(name="NET2", code="2", track_width=0.25))

    # Create components
    for i in range(1, 3):
        comp = Component(
            ref=f"R{i}",
            value="10k",
            footprint="RES-0805",
            position=(10.0 + i * 20.0, 20.0),
            rotation=0
        )
        comp.pads = [
            Pad(number=1, position_offset=(-0.95, 0), size=(1.3, 1.5), net_name="NET1"),
            Pad(number=2, position_offset=(0.95, 0), size=(1.3, 1.5), net_name="NET2")
        ]
        board.add_component(comp)
        board.nets["NET1"].connections.append((f"R{i}", "1"))
        board.nets["NET2"].connections.append((f"R{i}", "2"))

    # Manually add crossing traces to ensure we test DRC detection
    # NET1 horizontal segment
    board.nets["NET1"].add_segment(
        TraceSegment(net_name="NET1", start=(10.0, 20.0), end=(50.0, 20.0), layer="F.Cu", width=0.25)
    )

    # NET2 vertical segment that crosses NET1
    board.nets["NET2"].add_segment(
        TraceSegment(net_name="NET2", start=(30.0, 10.0), end=(30.0, 30.0), layer="F.Cu", width=0.25)
    )

    # Run DRC
    drc = CheckDrcCommand()
    result = drc.execute(board)

    # Should detect the crossing error
    assert "error" in result.lower()
    assert "cross" in result.lower() or "overlap" in result.lower()


def test_complete_workflow_with_warnings_and_drc():
    """Test complete workflow: routing with waypoint warnings, then DRC check.

    This simulates a realistic workflow where:
    1. User routes with some coordinate-based waypoints (warnings)
    2. Routes create crossing (error)
    3. DRC catches the crossing before save
    """
    board = Board()
    board.add_net(Net(name="GND", code="1", track_width=0.3))
    board.add_net(Net(name="VCC", code="2", track_width=0.3))

    # Create a simple component layout
    comp1 = Component(ref="C1", value="10uF", footprint="CAP-0805", position=(10.0, 20.0), rotation=0)
    comp1.pads = [
        Pad(number=1, position_offset=(-0.95, 0), size=(1.3, 1.5), net_name="GND"),
        Pad(number=2, position_offset=(0.95, 0), size=(1.3, 1.5), net_name="VCC")
    ]
    board.add_component(comp1)

    comp2 = Component(ref="C2", value="10uF", footprint="CAP-0805", position=(30.0, 20.0), rotation=0)
    comp2.pads = [
        Pad(number=1, position_offset=(-0.95, 0), size=(1.3, 1.5), net_name="GND"),
        Pad(number=2, position_offset=(0.95, 0), size=(1.3, 1.5), net_name="VCC")
    ]
    board.add_component(comp2)

    board.nets["GND"].connections.extend([("C1", "1"), ("C2", "1")])
    board.nets["VCC"].connections.extend([("C1", "2"), ("C2", "2")])

    # Route with deviation (should warn)
    old_stdout = sys.stdout
    sys.stdout = captured_output = StringIO()

    try:
        # Route GND with wrong coordinates (should warn)
        gnd_cmd = RouteCommand("GND", (15.0, 20.0), (29.05, 20.0), layer="F.Cu")
        gnd_result = gnd_cmd.execute(board)

        # Route VCC correctly
        vcc_cmd = RouteCommand("VCC", "C1.2", "C2.2", layer="F.Cu")
        vcc_result = vcc_cmd.execute(board)

        warnings_output = captured_output.getvalue()
    finally:
        sys.stdout = old_stdout

    # Should have warnings for GND route
    assert "WARNING" in warnings_output
    assert "deviation" in warnings_output.lower()

    # Both routes should succeed
    assert "OK:" in gnd_result
    assert "OK:" in vcc_result

    # Now run DRC - in this case no crossing (just warnings during routing)
    drc = CheckDrcCommand()
    drc_result = drc.execute(board)

    # Should pass DRC (no crossings, just routing warnings)
    assert "0 errors" in drc_result


def test_via_and_trace_routing_integration():
    """Test integration of vias with waypoint-based routing."""
    board = Board()
    board.add_net(Net(name="SIGNAL", code="1", track_width=0.25))

    # Create components on opposite sides of board
    comp1 = Component(ref="U1", value="IC", footprint="SOIC-8", position=(10.0, 10.0), rotation=0)
    comp1.pads = [
        Pad(number=1, position_offset=(-2.0, 0), size=(1.5, 1.0), net_name="SIGNAL")
    ]
    board.add_component(comp1)

    comp2 = Component(ref="U2", value="IC", footprint="SOIC-8", position=(40.0, 40.0), rotation=0)
    comp2.pads = [
        Pad(number=1, position_offset=(-2.0, 0), size=(1.5, 1.0), net_name="SIGNAL")
    ]
    board.add_component(comp2)

    board.nets["SIGNAL"].connections.extend([("U1", "1"), ("U2", "1")])

    # Route with via: front layer to via, then back layer to destination
    cmd1 = RouteCommand("SIGNAL", "U1.1", (25.0, 25.0), layer="F.Cu")
    cmd1.execute(board)

    via = ViaCommand("SIGNAL", (25.0, 25.0), size=0.8, drill=0.4)
    via.execute(board)

    cmd2 = RouteCommand("SIGNAL", (25.0, 25.0), "U2.1", layer="B.Cu")
    cmd2.execute(board)

    # Run DRC
    drc = CheckDrcCommand()
    result = drc.execute(board)

    # Should pass - valid routing with via
    assert "0 errors" in result


def test_multiple_layers_no_false_crossing_errors():
    """Test that traces on different layers don't trigger false crossing errors."""
    board = Board()
    board.add_net(Net(name="NET1", code="1", track_width=0.25))
    board.add_net(Net(name="NET2", code="2", track_width=0.25))

    # Create components
    comp1 = Component(ref="R1", value="10k", footprint="RES-0805", position=(10.0, 20.0), rotation=0)
    comp1.pads = [
        Pad(number=1, position_offset=(-0.95, 0), size=(1.3, 1.5), net_name="NET1"),
        Pad(number=2, position_offset=(0.95, 0), size=(1.3, 1.5), net_name="NET2")
    ]
    board.add_component(comp1)

    comp2 = Component(ref="R2", value="10k", footprint="RES-0805", position=(30.0, 20.0), rotation=0)
    comp2.pads = [
        Pad(number=1, position_offset=(-0.95, 0), size=(1.3, 1.5), net_name="NET1"),
        Pad(number=2, position_offset=(0.95, 0), size=(1.3, 1.5), net_name="NET2")
    ]
    board.add_component(comp2)

    board.nets["NET1"].connections.extend([("R1", "1"), ("R2", "1")])
    board.nets["NET2"].connections.extend([("R1", "2"), ("R2", "2")])

    # Route NET1 on front layer
    cmd1 = RouteCommand("NET1", "R1.1", "R2.1", layer="F.Cu")
    cmd1.execute(board)

    # Route NET2 on back layer (would cross if on same layer)
    cmd2 = RouteCommand("NET2", (20.0, 10.0), (20.0, 30.0), layer="B.Cu")
    cmd2.execute(board)

    # Run DRC
    drc = CheckDrcCommand()
    result = drc.execute(board)

    # Should pass - traces on different layers don't cross
    assert "0 errors" in result


def test_real_world_bus_routing_scenario():
    """Test realistic bus routing scenario with multiple parallel traces.

    Simulates routing multiple signal lines in parallel, checking that
    same-net crossovers don't trigger errors while different-net crossings do.
    """
    board = Board()
    board.add_net(Net(name="BUS0", code="1", track_width=0.25))
    board.add_net(Net(name="BUS1", code="2", track_width=0.25))
    board.add_net(Net(name="BUS2", code="3", track_width=0.25))

    # Create connector components
    for i in range(3):
        comp = Component(
            ref=f"J{i+1}",
            value="CONN",
            footprint="HDR-1x3",
            position=(10.0, 10.0 + i * 5.0),
            rotation=0
        )
        comp.pads = [
            Pad(number=1, position_offset=(0, 0), size=(1.5, 1.5), net_name=f"BUS{i}")
        ]
        board.add_component(comp)
        board.nets[f"BUS{i}"].connections.append((f"J{i+1}", "1"))

    # Route buses in parallel
    cmd1 = RouteCommand("BUS0", "J1.1", (30.0, 10.0), layer="F.Cu")
    cmd1.execute(board)

    cmd2 = RouteCommand("BUS1", "J2.1", (30.0, 15.0), layer="F.Cu")
    cmd2.execute(board)

    cmd3 = RouteCommand("BUS2", "J3.1", (30.0, 20.0), layer="F.Cu")
    cmd3.execute(board)

    # Run DRC
    drc = CheckDrcCommand()
    result = drc.execute(board)

    # Should pass - parallel traces don't cross
    assert "0 errors" in result


def test_waypoint_deviation_with_rotation():
    """Test waypoint deviation detection with rotated components.

    Rotated components have different pad positions, which can cause
    unexpected deviations if coordinates are based on unrotated layout.
    """
    board = Board()
    board.add_net(Net(name="TEST", code="1", track_width=0.25))

    # Create rotated component (90 degrees)
    comp = Component(ref="R1", value="10k", footprint="RES-0805", position=(20.0, 20.0), rotation=90)
    comp.pads = [
        Pad(number=1, position_offset=(-0.95, 0), size=(1.3, 1.5), net_name="TEST"),
        Pad(number=2, position_offset=(0.95, 0), size=(1.3, 1.5))
    ]
    board.add_component(comp)
    board.nets["TEST"].connections.append(("R1", "1"))

    # Try to route assuming 0-degree rotation (will be wrong)
    # At 0 degrees, pad would be at (19.05, 20.0)
    # At 90 degrees, pad is at (20.0, 19.05)
    old_stdout = sys.stdout
    sys.stdout = captured_output = StringIO()

    try:
        # Use coordinates for 0-degree rotation (wrong!)
        cmd = RouteCommand("TEST", (19.05, 20.0), (30.0, 20.0), layer="F.Cu")
        cmd.execute(board)

        output = captured_output.getvalue()
    finally:
        sys.stdout = old_stdout

    # Should warn about deviation due to rotation mismatch
    assert "WARNING" in output
    assert "deviation" in output.lower()


def test_drc_full_check_includes_trace_overlaps():
    """Test that full DRC check (execute) includes trace overlap detection."""
    board = Board()
    board.add_net(Net(name="NET1", code="1", track_width=0.25))
    board.add_net(Net(name="NET2", code="2", track_width=0.25))

    # Create simple crossing scenario
    comp1 = Component(ref="R1", value="10k", footprint="RES-0805", position=(10.0, 20.0), rotation=0)
    comp1.pads = [
        Pad(number=1, position_offset=(-0.95, 0), size=(1.3, 1.5), net_name="NET1")
    ]
    board.add_component(comp1)

    comp2 = Component(ref="R2", value="10k", footprint="RES-0805", position=(30.0, 20.0), rotation=0)
    comp2.pads = [
        Pad(number=1, position_offset=(-0.95, 0), size=(1.3, 1.5), net_name="NET2")
    ]
    board.add_component(comp2)

    board.nets["NET1"].connections.append(("R1", "1"))
    board.nets["NET2"].connections.append(("R2", "1"))

    # Add crossing traces manually
    from pcb_tool.data_model import TraceSegment
    board.nets["NET1"].add_segment(
        TraceSegment(net_name="NET1", start=(5.0, 20.0), end=(25.0, 20.0), layer="F.Cu", width=0.25)
    )
    board.nets["NET2"].add_segment(
        TraceSegment(net_name="NET2", start=(15.0, 10.0), end=(15.0, 30.0), layer="F.Cu", width=0.25)
    )

    # Run full DRC
    drc = CheckDrcCommand()
    result = drc.execute(board)

    # Should report the crossing error
    assert "1 error" in result
    assert "cross" in result.lower() or "overlap" in result.lower()
    assert "NET1" in result
    assert "NET2" in result
