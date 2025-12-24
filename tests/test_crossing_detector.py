"""
Tests for Crossing Detector Module

Tests detection of crossing traces between different nets.
"""

import pytest
from pcb_tool.routing.crossing_detector import CrossingDetector, Crossing


def test_x_pattern_horizontal_vertical_crossing():
    """Test X-pattern: horizontal and vertical paths crossing at center."""
    detector = CrossingDetector(resolution_mm=1.0)

    # Horizontal net at y=5 from x=2 to x=8
    # Vertical net at x=5 from y=2 to y=8
    # Should cross at cell (5, 5)
    net_paths = {
        "horizontal": [(2.0, 5.0), (5.0, 5.0), (8.0, 5.0)],
        "vertical": [(5.0, 2.0), (5.0, 5.0), (5.0, 8.0)]
    }

    crossings = detector.detect_crossings(net_paths, layer="F.Cu")

    # Should detect one crossing at (5, 5)
    assert len(crossings) > 0

    # Find the crossing at (5, 5)
    crossing_at_center = [c for c in crossings if c.cell == (5, 5)]
    assert len(crossing_at_center) > 0

    # Verify crossing involves both nets
    c = crossing_at_center[0]
    assert set([c.net1, c.net2]) == {"horizontal", "vertical"}
    assert c.layer == "F.Cu"


def test_parallel_paths_no_crossing():
    """Test parallel paths with no crossing."""
    detector = CrossingDetector(resolution_mm=1.0)

    # Two parallel horizontal paths
    net_paths = {
        "net1": [(2.0, 3.0), (8.0, 3.0)],
        "net2": [(2.0, 7.0), (8.0, 7.0)]
    }

    crossings = detector.detect_crossings(net_paths, layer="F.Cu")

    # Should detect no crossings
    assert len(crossings) == 0


def test_t_junction_same_net_not_crossing():
    """Test T-junction of same net (should NOT be a crossing)."""
    detector = CrossingDetector(resolution_mm=1.0)

    # Single net with T-junction
    # This is NOT a crossing (same net can overlap itself)
    net_paths = {
        "net1": [(2.0, 5.0), (5.0, 5.0), (8.0, 5.0), (5.0, 5.0), (5.0, 8.0)]
    }

    crossings = detector.detect_crossings(net_paths, layer="F.Cu")

    # Should detect no crossings (single net can overlap itself)
    assert len(crossings) == 0


def test_three_nets_crossing_at_same_point():
    """Test three nets crossing at the same point."""
    detector = CrossingDetector(resolution_mm=1.0)

    # Three nets all passing through (5, 5)
    net_paths = {
        "net1": [(2.0, 5.0), (5.0, 5.0), (8.0, 5.0)],
        "net2": [(5.0, 2.0), (5.0, 5.0), (5.0, 8.0)],
        "net3": [(2.0, 2.0), (5.0, 5.0), (8.0, 8.0)]
    }

    crossings = detector.detect_crossings(net_paths, layer="F.Cu")

    # Should detect 3 crossings (one for each pair)
    # Pairs: (net1, net2), (net1, net3), (net2, net3)
    crossing_at_center = [c for c in crossings if c.cell == (5, 5)]
    assert len(crossing_at_center) == 3

    # Verify all pairs are represented
    pairs = {(c.net1, c.net2) for c in crossing_at_center}
    expected_pairs = {
        ("net1", "net2"),
        ("net1", "net3"),
        ("net2", "net3")
    }
    assert pairs == expected_pairs
