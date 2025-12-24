"""
Tests for trace crossing detection in CheckDrcCommand.

Tests the _check_trace_overlaps() and _segments_intersect() methods which
detect when traces from different nets cross on the same layer.
"""

import pytest
from pcb_tool.commands import CheckDrcCommand
from pcb_tool.data_model import Board, Net, Component, Pad, TraceSegment


@pytest.fixture
def sample_board():
    """Create a basic board with two nets for testing."""
    board = Board()
    board.add_net(Net(name="NET1", code="1", track_width=0.25))
    board.add_net(Net(name="NET2", code="2", track_width=0.25))
    return board


def test_segments_intersect_perpendicular_crossing():
    """Test that perpendicular crossing segments are detected.

    Two segments that cross at right angles should be detected as intersecting.
    """
    drc = CheckDrcCommand()

    # Create horizontal segment from (0, 10) to (20, 10)
    seg1 = TraceSegment(
        net_name="NET1",
        start=(0.0, 10.0),
        end=(20.0, 10.0),
        layer="F.Cu",
        width=0.25
    )

    # Create vertical segment from (10, 0) to (10, 20)
    seg2 = TraceSegment(
        net_name="NET2",
        start=(10.0, 0.0),
        end=(10.0, 20.0),
        layer="F.Cu",
        width=0.25
    )

    intersection = drc._segments_intersect(seg1, seg2)

    assert intersection is not None
    x, y = intersection
    # Should intersect at (10, 10)
    assert abs(x - 10.0) < 0.01
    assert abs(y - 10.0) < 0.01


def test_segments_intersect_diagonal_crossing():
    """Test that diagonal crossing segments are detected."""
    drc = CheckDrcCommand()

    # Create segment from (0, 0) to (20, 20)
    seg1 = TraceSegment(
        net_name="NET1",
        start=(0.0, 0.0),
        end=(20.0, 20.0),
        layer="F.Cu",
        width=0.25
    )

    # Create segment from (0, 20) to (20, 0)
    seg2 = TraceSegment(
        net_name="NET2",
        start=(0.0, 20.0),
        end=(20.0, 0.0),
        layer="F.Cu",
        width=0.25
    )

    intersection = drc._segments_intersect(seg1, seg2)

    assert intersection is not None
    x, y = intersection
    # Should intersect at (10, 10)
    assert abs(x - 10.0) < 0.01
    assert abs(y - 10.0) < 0.01


def test_segments_intersect_parallel_segments_no_intersection():
    """Test that parallel segments return None (no intersection).

    Parallel lines should never intersect, even if they're close together.
    """
    drc = CheckDrcCommand()

    # Create horizontal segment from (0, 10) to (20, 10)
    seg1 = TraceSegment(
        net_name="NET1",
        start=(0.0, 10.0),
        end=(20.0, 10.0),
        layer="F.Cu",
        width=0.25
    )

    # Create parallel horizontal segment from (0, 12) to (20, 12)
    seg2 = TraceSegment(
        net_name="NET2",
        start=(0.0, 12.0),
        end=(20.0, 12.0),
        layer="F.Cu",
        width=0.25
    )

    intersection = drc._segments_intersect(seg1, seg2)

    assert intersection is None


def test_segments_intersect_non_intersecting_perpendicular():
    """Test that perpendicular but non-intersecting segments return None.

    Segments that would intersect if extended, but don't actually cross
    within their defined endpoints, should return None.
    """
    drc = CheckDrcCommand()

    # Create horizontal segment from (0, 10) to (8, 10)
    seg1 = TraceSegment(
        net_name="NET1",
        start=(0.0, 10.0),
        end=(8.0, 10.0),
        layer="F.Cu",
        width=0.25
    )

    # Create vertical segment from (10, 0) to (10, 20)
    # This would intersect at (10, 10) if seg1 extended, but it doesn't
    seg2 = TraceSegment(
        net_name="NET2",
        start=(10.0, 0.0),
        end=(10.0, 20.0),
        layer="F.Cu",
        width=0.25
    )

    intersection = drc._segments_intersect(seg1, seg2)

    assert intersection is None


def test_segments_intersect_touching_at_endpoint():
    """Test segments that touch at an endpoint are detected as intersecting."""
    drc = CheckDrcCommand()

    # Create segment from (0, 0) to (10, 10)
    seg1 = TraceSegment(
        net_name="NET1",
        start=(0.0, 0.0),
        end=(10.0, 10.0),
        layer="F.Cu",
        width=0.25
    )

    # Create segment from (10, 10) to (20, 0)
    # Starts where seg1 ends
    seg2 = TraceSegment(
        net_name="NET2",
        start=(10.0, 10.0),
        end=(20.0, 0.0),
        layer="F.Cu",
        width=0.25
    )

    intersection = drc._segments_intersect(seg1, seg2)

    # Should detect intersection at (10, 10)
    assert intersection is not None
    x, y = intersection
    assert abs(x - 10.0) < 0.01
    assert abs(y - 10.0) < 0.01


def test_segments_intersect_crossing_at_midpoint():
    """Test segments that cross at their midpoints."""
    drc = CheckDrcCommand()

    # Create segment from (5, 0) to (5, 20)
    seg1 = TraceSegment(
        net_name="NET1",
        start=(5.0, 0.0),
        end=(5.0, 20.0),
        layer="F.Cu",
        width=0.25
    )

    # Create segment from (0, 10) to (10, 10)
    seg2 = TraceSegment(
        net_name="NET2",
        start=(0.0, 10.0),
        end=(10.0, 10.0),
        layer="F.Cu",
        width=0.25
    )

    intersection = drc._segments_intersect(seg1, seg2)

    assert intersection is not None
    x, y = intersection
    # Should intersect at (5, 10)
    assert abs(x - 5.0) < 0.01
    assert abs(y - 10.0) < 0.01


def test_segments_intersect_angled_crossing():
    """Test segments that cross at non-perpendicular angles."""
    drc = CheckDrcCommand()

    # Create segment from (0, 5) to (20, 15)
    seg1 = TraceSegment(
        net_name="NET1",
        start=(0.0, 5.0),
        end=(20.0, 15.0),
        layer="F.Cu",
        width=0.25
    )

    # Create segment from (0, 15) to (20, 5)
    seg2 = TraceSegment(
        net_name="NET2",
        start=(0.0, 15.0),
        end=(20.0, 5.0),
        layer="F.Cu",
        width=0.25
    )

    intersection = drc._segments_intersect(seg1, seg2)

    assert intersection is not None
    x, y = intersection
    # Should intersect at (10, 10) - midpoint where slopes cross
    assert abs(x - 10.0) < 0.01
    assert abs(y - 10.0) < 0.01


def test_check_trace_overlaps_detects_crossing_different_nets(sample_board):
    """Test that _check_trace_overlaps() detects crossings between different nets.

    When traces from different nets cross on the same layer, this should be
    reported as an error.
    """
    # Add crossing traces to different nets
    seg1 = TraceSegment(
        net_name="NET1",
        start=(0.0, 10.0),
        end=(20.0, 10.0),
        layer="F.Cu",
        width=0.25
    )
    sample_board.nets["NET1"].add_segment(seg1)

    seg2 = TraceSegment(
        net_name="NET2",
        start=(10.0, 0.0),
        end=(10.0, 20.0),
        layer="F.Cu",
        width=0.25
    )
    sample_board.nets["NET2"].add_segment(seg2)

    drc = CheckDrcCommand()
    issues = drc._check_trace_overlaps(sample_board)

    assert len(issues['errors']) == 1
    error_msg = issues['errors'][0]
    assert "NET1" in error_msg
    assert "NET2" in error_msg
    assert "cross" in error_msg.lower()
    assert "F.Cu" in error_msg
    # Should include approximate crossing coordinates
    assert "(10" in error_msg


def test_check_trace_overlaps_ignores_same_net_crossings(sample_board):
    """Test that _check_trace_overlaps() ignores crossings within the same net.

    Traces on the same net can cross without issue (this is normal routing).
    Only crossings between different nets are errors.
    """
    # Add crossing traces to the SAME net
    seg1 = TraceSegment(
        net_name="NET1",
        start=(0.0, 10.0),
        end=(20.0, 10.0),
        layer="F.Cu",
        width=0.25
    )
    sample_board.nets["NET1"].add_segment(seg1)

    seg2 = TraceSegment(
        net_name="NET1",  # Same net!
        start=(10.0, 0.0),
        end=(10.0, 20.0),
        layer="F.Cu",
        width=0.25
    )
    sample_board.nets["NET1"].add_segment(seg2)

    drc = CheckDrcCommand()
    issues = drc._check_trace_overlaps(sample_board)

    # Should have no errors - same net can cross itself
    assert len(issues['errors']) == 0


def test_check_trace_overlaps_different_layers_no_error(sample_board):
    """Test that traces on different layers don't trigger crossing errors.

    Traces can cross when they're on different layers - this is not a DRC error.
    """
    # Add crossing traces on different layers
    seg1 = TraceSegment(
        net_name="NET1",
        start=(0.0, 10.0),
        end=(20.0, 10.0),
        layer="F.Cu",  # Front layer
        width=0.25
    )
    sample_board.nets["NET1"].add_segment(seg1)

    seg2 = TraceSegment(
        net_name="NET2",
        start=(10.0, 0.0),
        end=(10.0, 20.0),
        layer="B.Cu",  # Back layer
        width=0.25
    )
    sample_board.nets["NET2"].add_segment(seg2)

    drc = CheckDrcCommand()
    issues = drc._check_trace_overlaps(sample_board)

    # Should have no errors - different layers
    assert len(issues['errors']) == 0


def test_check_trace_overlaps_multiple_crossings(sample_board):
    """Test detection of multiple crossing errors on the same board."""
    # Create multiple crossing pairs
    # First crossing
    seg1 = TraceSegment(
        net_name="NET1",
        start=(0.0, 10.0),
        end=(20.0, 10.0),
        layer="F.Cu",
        width=0.25
    )
    sample_board.nets["NET1"].add_segment(seg1)

    seg2 = TraceSegment(
        net_name="NET2",
        start=(10.0, 0.0),
        end=(10.0, 20.0),
        layer="F.Cu",
        width=0.25
    )
    sample_board.nets["NET2"].add_segment(seg2)

    # Second crossing (different location)
    seg3 = TraceSegment(
        net_name="NET1",
        start=(30.0, 30.0),
        end=(50.0, 30.0),
        layer="F.Cu",
        width=0.25
    )
    sample_board.nets["NET1"].add_segment(seg3)

    seg4 = TraceSegment(
        net_name="NET2",
        start=(40.0, 20.0),
        end=(40.0, 40.0),
        layer="F.Cu",
        width=0.25
    )
    sample_board.nets["NET2"].add_segment(seg4)

    drc = CheckDrcCommand()
    issues = drc._check_trace_overlaps(sample_board)

    # Should detect both crossings
    assert len(issues['errors']) == 2


def test_check_trace_overlaps_no_crossings(sample_board):
    """Test that parallel non-crossing traces don't trigger errors."""
    # Add parallel traces that don't cross
    seg1 = TraceSegment(
        net_name="NET1",
        start=(0.0, 10.0),
        end=(20.0, 10.0),
        layer="F.Cu",
        width=0.25
    )
    sample_board.nets["NET1"].add_segment(seg1)

    seg2 = TraceSegment(
        net_name="NET2",
        start=(0.0, 15.0),
        end=(20.0, 15.0),
        layer="F.Cu",
        width=0.25
    )
    sample_board.nets["NET2"].add_segment(seg2)

    drc = CheckDrcCommand()
    issues = drc._check_trace_overlaps(sample_board)

    assert len(issues['errors']) == 0


def test_check_trace_overlaps_crossing_coordinates_reported(sample_board):
    """Test that the exact crossing coordinates are reported in error messages."""
    # Create traces that cross at a specific known point
    seg1 = TraceSegment(
        net_name="NET1",
        start=(0.0, 25.0),
        end=(50.0, 25.0),
        layer="F.Cu",
        width=0.25
    )
    sample_board.nets["NET1"].add_segment(seg1)

    seg2 = TraceSegment(
        net_name="NET2",
        start=(30.0, 10.0),
        end=(30.0, 40.0),
        layer="F.Cu",
        width=0.25
    )
    sample_board.nets["NET2"].add_segment(seg2)

    drc = CheckDrcCommand()
    issues = drc._check_trace_overlaps(sample_board)

    assert len(issues['errors']) == 1
    error_msg = issues['errors'][0]
    # Should report crossing at (30, 25)
    assert "(30" in error_msg
    assert "25" in error_msg


def test_check_trace_overlaps_back_layer_crossing(sample_board):
    """Test that crossings on back layer (B.Cu) are also detected."""
    seg1 = TraceSegment(
        net_name="NET1",
        start=(0.0, 10.0),
        end=(20.0, 10.0),
        layer="B.Cu",  # Back layer
        width=0.25
    )
    sample_board.nets["NET1"].add_segment(seg1)

    seg2 = TraceSegment(
        net_name="NET2",
        start=(10.0, 0.0),
        end=(10.0, 20.0),
        layer="B.Cu",  # Back layer
        width=0.25
    )
    sample_board.nets["NET2"].add_segment(seg2)

    drc = CheckDrcCommand()
    issues = drc._check_trace_overlaps(sample_board)

    assert len(issues['errors']) == 1
    error_msg = issues['errors'][0]
    assert "B.Cu" in error_msg


def test_check_trace_overlaps_edge_case_barely_missing():
    """Test segments that come very close but don't quite intersect."""
    board = Board()
    board.add_net(Net(name="NET1", code="1", track_width=0.25))
    board.add_net(Net(name="NET2", code="2", track_width=0.25))

    # Create horizontal segment from (0, 10) to (9.99, 10)
    seg1 = TraceSegment(
        net_name="NET1",
        start=(0.0, 10.0),
        end=(9.99, 10.0),
        layer="F.Cu",
        width=0.25
    )
    board.nets["NET1"].add_segment(seg1)

    # Create vertical segment from (10, 0) to (10, 20)
    # These are very close but don't intersect
    seg2 = TraceSegment(
        net_name="NET2",
        start=(10.0, 0.0),
        end=(10.0, 20.0),
        layer="F.Cu",
        width=0.25
    )
    board.nets["NET2"].add_segment(seg2)

    drc = CheckDrcCommand()
    issues = drc._check_trace_overlaps(board)

    # Should NOT detect crossing - segments don't actually intersect
    assert len(issues['errors']) == 0


def test_check_trace_overlaps_t_junction():
    """Test T-junction where one segment ends on another (different nets)."""
    board = Board()
    board.add_net(Net(name="NET1", code="1", track_width=0.25))
    board.add_net(Net(name="NET2", code="2", track_width=0.25))

    # Horizontal segment across
    seg1 = TraceSegment(
        net_name="NET1",
        start=(0.0, 10.0),
        end=(20.0, 10.0),
        layer="F.Cu",
        width=0.25
    )
    board.nets["NET1"].add_segment(seg1)

    # Vertical segment that ends at the horizontal one (T-junction)
    seg2 = TraceSegment(
        net_name="NET2",
        start=(10.0, 0.0),
        end=(10.0, 10.0),  # Ends exactly on seg1
        layer="F.Cu",
        width=0.25
    )
    board.nets["NET2"].add_segment(seg2)

    drc = CheckDrcCommand()
    issues = drc._check_trace_overlaps(board)

    # Should detect this as a crossing (different nets touching)
    assert len(issues['errors']) == 1


def test_segments_intersect_collinear_overlapping():
    """Test collinear overlapping segments (same line, different nets).

    This is an edge case - segments on the same line that overlap.
    The algorithm should return None (parallel/coincident lines).
    """
    drc = CheckDrcCommand()

    # Two horizontal segments on the same Y coordinate that overlap
    seg1 = TraceSegment(
        net_name="NET1",
        start=(0.0, 10.0),
        end=(15.0, 10.0),
        layer="F.Cu",
        width=0.25
    )

    seg2 = TraceSegment(
        net_name="NET2",
        start=(10.0, 10.0),
        end=(20.0, 10.0),
        layer="F.Cu",
        width=0.25
    )

    intersection = drc._segments_intersect(seg1, seg2)

    # Should return None - these are collinear/coincident
    # (Though this would be a clearance violation in real DRC)
    assert intersection is None
