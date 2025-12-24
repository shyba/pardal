# tests/test_routing_data_model.py
"""Tests for MVP2 routing data model extensions."""

import pytest
from pcb_tool.data_model import Net, TraceSegment, Via


class TestTraceSegment:
    """Tests for TraceSegment dataclass."""

    def test_trace_segment_creation(self):
        """Test creating a trace segment with valid data."""
        segment = TraceSegment(
            net_name="GND",
            start=(10.0, 20.0),
            end=(30.0, 40.0),
            layer="F.Cu",
            width=0.25
        )
        assert segment.net_name == "GND"
        assert segment.start == (10.0, 20.0)
        assert segment.end == (30.0, 40.0)
        assert segment.layer == "F.Cu"
        assert segment.width == 0.25

    def test_trace_segment_back_copper(self):
        """Test trace segment on back copper layer."""
        segment = TraceSegment(
            net_name="VCC",
            start=(0.0, 0.0),
            end=(10.0, 10.0),
            layer="B.Cu",
            width=0.5
        )
        assert segment.layer == "B.Cu"

    def test_trace_segment_invalid_width_zero(self):
        """Test that zero width raises ValueError."""
        with pytest.raises(ValueError, match="width must be positive"):
            TraceSegment(
                net_name="GND",
                start=(0.0, 0.0),
                end=(10.0, 10.0),
                layer="F.Cu",
                width=0.0
            )

    def test_trace_segment_invalid_width_negative(self):
        """Test that negative width raises ValueError."""
        with pytest.raises(ValueError, match="width must be positive"):
            TraceSegment(
                net_name="GND",
                start=(0.0, 0.0),
                end=(10.0, 10.0),
                layer="F.Cu",
                width=-0.25
            )

    def test_trace_segment_invalid_layer(self):
        """Test that invalid layer name raises ValueError."""
        with pytest.raises(ValueError, match="layer must be a valid copper layer"):
            TraceSegment(
                net_name="GND",
                start=(0.0, 0.0),
                end=(10.0, 10.0),
                layer="Invalid.Layer",
                width=0.25
            )

    def test_trace_segment_inner_layer(self):
        """Test trace segment on inner copper layer (multi-layer support)."""
        segment = TraceSegment(
            net_name="SIG1",
            start=(0.0, 0.0),
            end=(10.0, 10.0),
            layer="In1.Cu",
            width=0.25
        )
        assert segment.layer == "In1.Cu"

    def test_trace_segment_inner_layer_2(self):
        """Test trace segment on second inner copper layer."""
        segment = TraceSegment(
            net_name="SIG2",
            start=(0.0, 0.0),
            end=(10.0, 10.0),
            layer="In2.Cu",
            width=0.25
        )
        assert segment.layer == "In2.Cu"

    def test_trace_segment_equality(self):
        """Test that two identical segments are equal."""
        seg1 = TraceSegment("GND", (0.0, 0.0), (10.0, 10.0), "F.Cu", 0.25)
        seg2 = TraceSegment("GND", (0.0, 0.0), (10.0, 10.0), "F.Cu", 0.25)
        assert seg1 == seg2


class TestVia:
    """Tests for Via dataclass."""

    def test_via_creation(self):
        """Test creating a via with valid data."""
        via = Via(
            net_name="GND",
            position=(50.0, 60.0),
            size=0.8,
            drill=0.4,
            layers=("F.Cu", "B.Cu")
        )
        assert via.net_name == "GND"
        assert via.position == (50.0, 60.0)
        assert via.size == 0.8
        assert via.drill == 0.4
        assert via.layers == ("F.Cu", "B.Cu")

    def test_via_invalid_size_zero(self):
        """Test that zero size raises ValueError."""
        with pytest.raises(ValueError, match="size must be positive"):
            Via(
                net_name="GND",
                position=(0.0, 0.0),
                size=0.0,
                drill=0.4,
                layers=("F.Cu", "B.Cu")
            )

    def test_via_invalid_size_negative(self):
        """Test that negative size raises ValueError."""
        with pytest.raises(ValueError, match="size must be positive"):
            Via(
                net_name="GND",
                position=(0.0, 0.0),
                size=-0.8,
                drill=0.4,
                layers=("F.Cu", "B.Cu")
            )

    def test_via_invalid_drill_zero(self):
        """Test that zero drill raises ValueError."""
        with pytest.raises(ValueError, match="drill must be positive"):
            Via(
                net_name="GND",
                position=(0.0, 0.0),
                size=0.8,
                drill=0.0,
                layers=("F.Cu", "B.Cu")
            )

    def test_via_invalid_drill_negative(self):
        """Test that negative drill raises ValueError."""
        with pytest.raises(ValueError, match="drill must be positive"):
            Via(
                net_name="GND",
                position=(0.0, 0.0),
                size=0.8,
                drill=-0.4,
                layers=("F.Cu", "B.Cu")
            )

    def test_via_drill_larger_than_size(self):
        """Test that drill larger than size raises ValueError."""
        with pytest.raises(ValueError, match="drill must be smaller than size"):
            Via(
                net_name="GND",
                position=(0.0, 0.0),
                size=0.4,
                drill=0.8,
                layers=("F.Cu", "B.Cu")
            )

    def test_via_drill_equal_to_size(self):
        """Test that drill equal to size raises ValueError."""
        with pytest.raises(ValueError, match="drill must be smaller than size"):
            Via(
                net_name="GND",
                position=(0.0, 0.0),
                size=0.8,
                drill=0.8,
                layers=("F.Cu", "B.Cu")
            )

    def test_via_equality(self):
        """Test that two identical vias are equal."""
        via1 = Via("GND", (50.0, 60.0), 0.8, 0.4, ("F.Cu", "B.Cu"))
        via2 = Via("GND", (50.0, 60.0), 0.8, 0.4, ("F.Cu", "B.Cu"))
        assert via1 == via2

    def test_via_through_hole_properties(self):
        """Test through-hole via type properties."""
        via = Via(
            net_name="GND",
            position=(50.0, 60.0),
            size=0.8,
            drill=0.4,
            layers=("F.Cu", "B.Cu"),
            via_type="through"
        )
        assert via.is_through_hole is True
        assert via.is_blind is False
        assert via.is_buried is False
        assert via.start_layer == "F.Cu"
        assert via.end_layer == "B.Cu"

    def test_via_blind_top(self):
        """Test blind via from top to inner layer."""
        via = Via(
            net_name="VCC",
            position=(30.0, 40.0),
            size=0.6,
            drill=0.3,
            layers=("F.Cu", "In1.Cu"),
            via_type="blind"
        )
        assert via.is_through_hole is False
        assert via.is_blind is True
        assert via.is_buried is False
        assert via.start_layer == "F.Cu"
        assert via.end_layer == "In1.Cu"

    def test_via_blind_bottom(self):
        """Test blind via from bottom to inner layer."""
        via = Via(
            net_name="VCC",
            position=(30.0, 40.0),
            size=0.6,
            drill=0.3,
            layers=("In2.Cu", "B.Cu"),
            via_type="blind"
        )
        assert via.is_through_hole is False
        assert via.is_blind is True
        assert via.is_buried is False
        assert via.start_layer == "In2.Cu"
        assert via.end_layer == "B.Cu"

    def test_via_buried(self):
        """Test buried via between inner layers."""
        via = Via(
            net_name="SIG",
            position=(20.0, 30.0),
            size=0.5,
            drill=0.25,
            layers=("In1.Cu", "In2.Cu"),
            via_type="buried"
        )
        assert via.is_through_hole is False
        assert via.is_blind is False
        assert via.is_buried is True
        assert via.start_layer == "In1.Cu"
        assert via.end_layer == "In2.Cu"

    def test_via_4layer_through_hole(self):
        """Test 4-layer through-hole via."""
        via = Via(
            net_name="GND",
            position=(50.0, 60.0),
            size=0.8,
            drill=0.4,
            layers=("F.Cu", "In1.Cu", "In2.Cu", "B.Cu"),
            via_type="through"
        )
        assert via.is_through_hole is True
        assert len(via.layers) == 4

    def test_via_invalid_layer(self):
        """Test that invalid layer name raises ValueError."""
        with pytest.raises(ValueError, match="Invalid via layer"):
            Via(
                net_name="GND",
                position=(0.0, 0.0),
                size=0.8,
                drill=0.4,
                layers=("F.Cu", "Invalid.Layer")
            )

    def test_via_single_layer_invalid(self):
        """Test that single-layer via raises ValueError."""
        with pytest.raises(ValueError, match="must connect at least 2 layers"):
            Via(
                net_name="GND",
                position=(0.0, 0.0),
                size=0.8,
                drill=0.4,
                layers=("F.Cu",)
            )

    def test_via_invalid_type(self):
        """Test that invalid via_type raises ValueError."""
        with pytest.raises(ValueError, match="via_type must be"):
            Via(
                net_name="GND",
                position=(0.0, 0.0),
                size=0.8,
                drill=0.4,
                layers=("F.Cu", "B.Cu"),
                via_type="invalid_type"
            )


class TestNetRouting:
    """Tests for Net class routing features."""

    def test_net_default_routing_parameters(self):
        """Test that Net has default routing parameters."""
        net = Net(name="GND", code="1")
        assert net.track_width == 0.25
        assert net.via_size == 0.8
        assert net.via_drill == 0.4
        assert net.segments == []
        assert net.vias == []

    def test_net_custom_routing_parameters(self):
        """Test creating Net with custom routing parameters."""
        net = Net(
            name="VCC",
            code="2",
            track_width=0.5,
            via_size=1.0,
            via_drill=0.6
        )
        assert net.track_width == 0.5
        assert net.via_size == 1.0
        assert net.via_drill == 0.6

    def test_add_segment(self):
        """Test adding a segment to a net."""
        net = Net(name="GND", code="1")
        segment = TraceSegment(
            net_name="GND",
            start=(0.0, 0.0),
            end=(10.0, 10.0),
            layer="F.Cu",
            width=0.25
        )
        net.add_segment(segment)
        assert len(net.segments) == 1
        assert net.segments[0] == segment

    def test_add_multiple_segments(self):
        """Test adding multiple segments to a net."""
        net = Net(name="GND", code="1")
        seg1 = TraceSegment("GND", (0.0, 0.0), (10.0, 10.0), "F.Cu", 0.25)
        seg2 = TraceSegment("GND", (10.0, 10.0), (20.0, 20.0), "F.Cu", 0.25)
        seg3 = TraceSegment("GND", (20.0, 20.0), (30.0, 30.0), "B.Cu", 0.25)

        net.add_segment(seg1)
        net.add_segment(seg2)
        net.add_segment(seg3)

        assert len(net.segments) == 3
        assert seg1 in net.segments
        assert seg2 in net.segments
        assert seg3 in net.segments

    def test_add_via(self):
        """Test adding a via to a net."""
        net = Net(name="GND", code="1")
        via = Via(
            net_name="GND",
            position=(50.0, 60.0),
            size=0.8,
            drill=0.4,
            layers=("F.Cu", "B.Cu")
        )
        net.add_via(via)
        assert len(net.vias) == 1
        assert net.vias[0] == via

    def test_add_multiple_vias(self):
        """Test adding multiple vias to a net."""
        net = Net(name="VCC", code="2")
        via1 = Via("VCC", (10.0, 10.0), 0.8, 0.4, ("F.Cu", "B.Cu"))
        via2 = Via("VCC", (20.0, 20.0), 0.8, 0.4, ("F.Cu", "B.Cu"))
        via3 = Via("VCC", (30.0, 30.0), 1.0, 0.5, ("F.Cu", "B.Cu"))

        net.add_via(via1)
        net.add_via(via2)
        net.add_via(via3)

        assert len(net.vias) == 3
        assert via1 in net.vias
        assert via2 in net.vias
        assert via3 in net.vias

    def test_remove_segment(self):
        """Test removing a segment from a net."""
        net = Net(name="GND", code="1")
        segment = TraceSegment("GND", (0.0, 0.0), (10.0, 10.0), "F.Cu", 0.25)
        net.add_segment(segment)
        assert len(net.segments) == 1

        net.remove_segment(segment)
        assert len(net.segments) == 0

    def test_remove_segment_not_in_net(self):
        """Test removing a segment that's not in the net raises ValueError."""
        net = Net(name="GND", code="1")
        segment = TraceSegment("GND", (0.0, 0.0), (10.0, 10.0), "F.Cu", 0.25)

        with pytest.raises(ValueError, match="Segment not found in net"):
            net.remove_segment(segment)

    def test_remove_via(self):
        """Test removing a via from a net."""
        net = Net(name="GND", code="1")
        via = Via("GND", (50.0, 60.0), 0.8, 0.4, ("F.Cu", "B.Cu"))
        net.add_via(via)
        assert len(net.vias) == 1

        net.remove_via(via)
        assert len(net.vias) == 0

    def test_remove_via_not_in_net(self):
        """Test removing a via that's not in the net raises ValueError."""
        net = Net(name="GND", code="1")
        via = Via("GND", (50.0, 60.0), 0.8, 0.4, ("F.Cu", "B.Cu"))

        with pytest.raises(ValueError, match="Via not found in net"):
            net.remove_via(via)

    def test_find_segment_near_exact_start(self):
        """Test finding segment at exact start position."""
        net = Net(name="GND", code="1")
        segment = TraceSegment("GND", (10.0, 20.0), (30.0, 40.0), "F.Cu", 0.25)
        net.add_segment(segment)

        found = net.find_segment_near(10.0, 20.0, tolerance=0.5)
        assert found == segment

    def test_find_segment_near_exact_end(self):
        """Test finding segment at exact end position."""
        net = Net(name="GND", code="1")
        segment = TraceSegment("GND", (10.0, 20.0), (30.0, 40.0), "F.Cu", 0.25)
        net.add_segment(segment)

        found = net.find_segment_near(30.0, 40.0, tolerance=0.5)
        assert found == segment

    def test_find_segment_near_within_tolerance(self):
        """Test finding segment within tolerance."""
        net = Net(name="GND", code="1")
        segment = TraceSegment("GND", (10.0, 20.0), (30.0, 40.0), "F.Cu", 0.25)
        net.add_segment(segment)

        # Just within tolerance at start
        found = net.find_segment_near(10.3, 20.3, tolerance=0.5)
        assert found == segment

        # Just within tolerance at end
        found = net.find_segment_near(29.7, 39.7, tolerance=0.5)
        assert found == segment

    def test_find_segment_near_outside_tolerance(self):
        """Test that segment outside tolerance is not found."""
        net = Net(name="GND", code="1")
        segment = TraceSegment("GND", (10.0, 20.0), (30.0, 40.0), "F.Cu", 0.25)
        net.add_segment(segment)

        # Too far from start
        found = net.find_segment_near(10.6, 20.6, tolerance=0.5)
        assert found is None

        # Too far from end
        found = net.find_segment_near(29.4, 39.4, tolerance=0.5)
        assert found is None

    def test_find_segment_near_multiple_segments(self):
        """Test finding first matching segment when multiple exist."""
        net = Net(name="GND", code="1")
        seg1 = TraceSegment("GND", (0.0, 0.0), (10.0, 10.0), "F.Cu", 0.25)
        seg2 = TraceSegment("GND", (10.0, 10.0), (20.0, 20.0), "F.Cu", 0.25)
        net.add_segment(seg1)
        net.add_segment(seg2)

        # Should find seg1 at its start
        found = net.find_segment_near(0.0, 0.0, tolerance=0.5)
        assert found == seg1

        # Should find either seg1 or seg2 at shared point (10, 10)
        found = net.find_segment_near(10.0, 10.0, tolerance=0.5)
        assert found in [seg1, seg2]

    def test_find_segment_near_no_segments(self):
        """Test finding segment in empty net returns None."""
        net = Net(name="GND", code="1")
        found = net.find_segment_near(10.0, 20.0, tolerance=0.5)
        assert found is None

    def test_find_via_at_exact_position(self):
        """Test finding via at exact position."""
        net = Net(name="GND", code="1")
        via = Via("GND", (50.0, 60.0), 0.8, 0.4, ("F.Cu", "B.Cu"))
        net.add_via(via)

        found = net.find_via_at(50.0, 60.0, tolerance=0.1)
        assert found == via

    def test_find_via_at_within_tolerance(self):
        """Test finding via within tolerance."""
        net = Net(name="GND", code="1")
        via = Via("GND", (50.0, 60.0), 0.8, 0.4, ("F.Cu", "B.Cu"))
        net.add_via(via)

        # Just within tolerance (distance = 0.07 * sqrt(2) = 0.099)
        found = net.find_via_at(50.07, 60.07, tolerance=0.1)
        assert found == via

    def test_find_via_at_outside_tolerance(self):
        """Test that via outside tolerance is not found."""
        net = Net(name="GND", code="1")
        via = Via("GND", (50.0, 60.0), 0.8, 0.4, ("F.Cu", "B.Cu"))
        net.add_via(via)

        # Too far away
        found = net.find_via_at(50.15, 60.15, tolerance=0.1)
        assert found is None

    def test_find_via_at_multiple_vias(self):
        """Test finding first matching via when multiple exist."""
        net = Net(name="GND", code="1")
        via1 = Via("GND", (10.0, 10.0), 0.8, 0.4, ("F.Cu", "B.Cu"))
        via2 = Via("GND", (20.0, 20.0), 0.8, 0.4, ("F.Cu", "B.Cu"))
        net.add_via(via1)
        net.add_via(via2)

        # Should find via1
        found = net.find_via_at(10.0, 10.0, tolerance=0.1)
        assert found == via1

        # Should find via2
        found = net.find_via_at(20.0, 20.0, tolerance=0.1)
        assert found == via2

    def test_find_via_at_no_vias(self):
        """Test finding via in empty net returns None."""
        net = Net(name="GND", code="1")
        found = net.find_via_at(50.0, 60.0, tolerance=0.1)
        assert found is None

    def test_find_via_custom_tolerance(self):
        """Test finding via with custom tolerance values."""
        net = Net(name="GND", code="1")
        via = Via("GND", (50.0, 60.0), 0.8, 0.4, ("F.Cu", "B.Cu"))
        net.add_via(via)

        # Should not find with small tolerance
        found = net.find_via_at(50.2, 60.2, tolerance=0.1)
        assert found is None

        # Should find with larger tolerance
        found = net.find_via_at(50.2, 60.2, tolerance=0.3)
        assert found == via
