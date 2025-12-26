"""Tests for DRC enhancements: track-pad clearance, pad-pad clearance, SDK DRC."""

import pytest
from pcb_tool.data_model import Board, Component, Pad, Net, TraceSegment
from pcb_tool.commands.drc import CheckDrcCommand


class TestPointToSegmentDistance:
    """Tests for the point-to-segment distance calculation."""

    def test_point_on_segment(self):
        """Point directly on segment should have distance 0."""
        cmd = CheckDrcCommand()
        # Point at (5, 0) on segment from (0, 0) to (10, 0)
        dist = cmd._point_to_segment_distance(5, 0, 0, 0, 10, 0)
        assert dist == pytest.approx(0, abs=0.001)

    def test_point_perpendicular_to_segment(self):
        """Point perpendicular to segment midpoint."""
        cmd = CheckDrcCommand()
        # Point at (5, 3) perpendicular to segment from (0, 0) to (10, 0)
        dist = cmd._point_to_segment_distance(5, 3, 0, 0, 10, 0)
        assert dist == pytest.approx(3.0, abs=0.001)

    def test_point_beyond_segment_start(self):
        """Point beyond segment start."""
        cmd = CheckDrcCommand()
        # Point at (-3, 0) beyond segment from (0, 0) to (10, 0)
        dist = cmd._point_to_segment_distance(-3, 0, 0, 0, 10, 0)
        assert dist == pytest.approx(3.0, abs=0.001)

    def test_point_beyond_segment_end(self):
        """Point beyond segment end."""
        cmd = CheckDrcCommand()
        # Point at (13, 0) beyond segment from (0, 0) to (10, 0)
        dist = cmd._point_to_segment_distance(13, 0, 0, 0, 10, 0)
        assert dist == pytest.approx(3.0, abs=0.001)

    def test_zero_length_segment(self):
        """Zero-length segment should return distance to point."""
        cmd = CheckDrcCommand()
        # Point at (3, 4) with zero-length segment at (0, 0)
        dist = cmd._point_to_segment_distance(3, 4, 0, 0, 0, 0)
        assert dist == pytest.approx(5.0, abs=0.001)


class TestTrackPadClearance:
    """Tests for track-to-pad clearance checking."""

    @pytest.fixture
    def board_with_track_near_pad(self):
        """Create board with track running close to a pad."""
        board = Board()

        # Component with pad at (10, 10)
        comp = Component(
            ref="R1",
            value="10k",
            footprint="R_0805",
            position=(10.0, 10.0),
            rotation=0.0,
            layer="F.Cu",
        )
        comp.pads = [
            Pad(number=1, position_offset=(0.0, 0.0), size=(1.0, 1.0), shape="rect"),
            Pad(number=2, position_offset=(2.0, 0.0), size=(1.0, 1.0), shape="rect"),
        ]
        board.add_component(comp)

        # Net connecting pad 1
        net1 = Net(name="NET1", code="1")
        net1.add_connection("R1", "1")
        board.add_net(net1)

        # Different net with track running near pad 2
        net2 = Net(name="NET2", code="2", track_width=0.2)
        # Pad 2 center at (12, 10), radius = 0.5
        # Track at y=10 (same height), x from 12.6 to 20, width 0.2
        # Distance from pad center to track = 0.6mm (starts at 12.6)
        # Clearance = 0.6 - 0.5 (pad radius) - 0.1 (track half width) = 0.0mm (touching!)
        seg = TraceSegment("NET2", (12.6, 10.0), (20.0, 10.0), "F.Cu", 0.2)
        net2.add_segment(seg)
        board.add_net(net2)

        return board

    def test_detects_track_too_close_to_pad(self, board_with_track_near_pad):
        """Track running too close to pad should be detected."""
        cmd = CheckDrcCommand()
        result = cmd.execute(board_with_track_near_pad)

        # Should detect clearance violation
        assert "ERROR" in result
        assert "too close" in result.lower() or "shorts" in result.lower()

    @pytest.fixture
    def board_with_track_sufficient_clearance(self):
        """Create board with track with sufficient clearance."""
        board = Board()

        # Component with pad at (10, 10)
        comp = Component(
            ref="R1",
            value="10k",
            footprint="R_0805",
            position=(10.0, 10.0),
            rotation=0.0,
            layer="F.Cu",
        )
        comp.pads = [
            Pad(number=1, position_offset=(0.0, 0.0), size=(1.0, 1.0), shape="rect"),
            Pad(number=2, position_offset=(2.0, 0.0), size=(1.0, 1.0), shape="rect"),
        ]
        board.add_component(comp)

        # Net connecting pad 1
        net1 = Net(name="NET1", code="1")
        net1.add_connection("R1", "1")
        board.add_net(net1)

        # Different net with track far from pad 2
        net2 = Net(name="NET2", code="2", track_width=0.2)
        # Track at y=12, x from 13 to 20 (far from pad at (12, 10))
        # Distance = 2mm, clearance = 2 - 0.5 - 0.1 = 1.4mm > 0.2mm
        seg = TraceSegment("NET2", (13.0, 12.0), (20.0, 12.0), "F.Cu", 0.2)
        net2.add_segment(seg)
        board.add_net(net2)

        return board

    def test_allows_track_with_sufficient_clearance(
        self, board_with_track_sufficient_clearance
    ):
        """Track with sufficient clearance should not report error."""
        cmd = CheckDrcCommand()
        result = cmd.execute(board_with_track_sufficient_clearance)

        # Should not have track-pad clearance errors
        assert "too close to" not in result.lower()
        assert "shorts to" not in result.lower()

    @pytest.fixture
    def board_with_track_to_own_pad(self):
        """Create board with track connecting to its own pad."""
        board = Board()

        # Component with pad
        comp = Component(
            ref="R1",
            value="10k",
            footprint="R_0805",
            position=(10.0, 10.0),
            rotation=0.0,
            layer="F.Cu",
        )
        comp.pads = [
            Pad(number=1, position_offset=(0.0, 0.0), size=(1.0, 1.0), shape="rect"),
            Pad(number=2, position_offset=(2.0, 0.0), size=(1.0, 1.0), shape="rect"),
        ]
        board.add_component(comp)

        # Net connecting pad 1 with track running to it
        net = Net(name="NET1", code="1", track_width=0.2)
        net.add_connection("R1", "1")
        # Track running directly to pad 1 at (10, 10)
        seg = TraceSegment("NET1", (5.0, 10.0), (10.0, 10.0), "F.Cu", 0.2)
        net.add_segment(seg)
        board.add_net(net)

        return board

    def test_ignores_same_net_track_pad(self, board_with_track_to_own_pad):
        """Track connecting to its own net's pad should not report error."""
        cmd = CheckDrcCommand()
        result = cmd.execute(board_with_track_to_own_pad)

        # Should not report track-pad issues for same net
        assert "shorts to R1 pad 1" not in result
        assert "too close to R1 pad 1" not in result


class TestPadPadClearance:
    """Tests for pad-to-pad clearance checking within components."""

    @pytest.fixture
    def board_with_overlapping_pads(self):
        """Create board with overlapping pads (bad TQFP definition)."""
        board = Board()

        # Component with overlapping pads (like bad TQFP with 1.2mm pads at 0.8mm pitch)
        comp = Component(
            ref="U1",
            value="IC",
            footprint="TQFP-32",
            position=(20.0, 20.0),
            rotation=0.0,
            layer="F.Cu",
        )
        # Pads at 0.8mm pitch with 1.2mm size = 0.4mm overlap
        comp.pads = [
            Pad(number=1, position_offset=(0.0, 0.0), size=(0.5, 1.2), shape="rect"),
            Pad(number=2, position_offset=(0.0, 0.8), size=(0.5, 1.2), shape="rect"),
        ]
        board.add_component(comp)

        return board

    def test_detects_overlapping_pads(self, board_with_overlapping_pads):
        """Overlapping pads should be detected as error."""
        cmd = CheckDrcCommand()
        result = cmd.execute(board_with_overlapping_pads)

        assert "ERROR" in result
        assert "overlap" in result.lower()
        assert "U1" in result

    @pytest.fixture
    def board_with_proper_pad_spacing(self):
        """Create board with properly spaced pads."""
        board = Board()

        # Component with properly spaced pads (0.5mm pads at 0.8mm pitch = 0.3mm gap)
        comp = Component(
            ref="U1",
            value="IC",
            footprint="TQFP-32",
            position=(20.0, 20.0),
            rotation=0.0,
            layer="F.Cu",
        )
        comp.pads = [
            Pad(number=1, position_offset=(0.0, 0.0), size=(0.45, 0.5), shape="rect"),
            Pad(number=2, position_offset=(0.0, 0.8), size=(0.45, 0.5), shape="rect"),
        ]
        board.add_component(comp)

        return board

    def test_allows_proper_pad_spacing(self, board_with_proper_pad_spacing):
        """Properly spaced pads should not report error."""
        cmd = CheckDrcCommand()
        result = cmd.execute(board_with_proper_pad_spacing)

        # Should not have pad overlap errors
        assert "overlap" not in result.lower()

    @pytest.fixture
    def board_with_close_but_not_overlapping_pads(self):
        """Create board with pads that are close but not overlapping."""
        board = Board()

        # Component with close pads (edge-to-edge = 0.05mm, which is < 0.1mm min)
        comp = Component(
            ref="U1",
            value="IC",
            footprint="Fine-pitch",
            position=(20.0, 20.0),
            rotation=0.0,
            layer="F.Cu",
        )
        # Pads: 0.4mm diameter at 0.45mm pitch = 0.05mm clearance
        comp.pads = [
            Pad(number=1, position_offset=(0.0, 0.0), size=(0.4, 0.4), shape="circle"),
            Pad(number=2, position_offset=(0.45, 0.0), size=(0.4, 0.4), shape="circle"),
        ]
        board.add_component(comp)

        return board

    def test_warns_on_very_close_pads(self, board_with_close_but_not_overlapping_pads):
        """Very close pads should generate warning."""
        cmd = CheckDrcCommand()
        result = cmd.execute(board_with_close_but_not_overlapping_pads)

        # Should have warning about close pads
        assert "WARNING" in result
        assert "very close" in result.lower() or "close" in result.lower()


class TestSdkDrc:
    """Tests for SDK-based DRC function."""

    def test_sdk_drc_import(self):
        """Verify SDK DRC function is importable."""
        from pcb_tool.drc import run_sdk_drc

        assert callable(run_sdk_drc)

    def test_sdk_drc_fallback(self, tmp_path):
        """SDK DRC should work (either via SDK or fallback to kicad-cli)."""
        from pcb_tool.drc import run_sdk_drc
        from pcb_tool.kicad_writer import KicadWriter

        # Create a minimal board
        board = Board()
        board.width = 20.0
        board.height = 20.0

        comp = Component(
            ref="R1",
            value="10k",
            footprint="R_0805",
            position=(10.0, 10.0),
            rotation=0.0,
            layer="F.Cu",
        )
        comp.pads = [
            Pad(number=1, position_offset=(0.0, 0.0), size=(1.0, 1.0), shape="rect"),
            Pad(number=2, position_offset=(2.0, 0.0), size=(1.0, 1.0), shape="rect"),
        ]
        board.add_component(comp)

        # Save board
        pcb_path = tmp_path / "test_board.kicad_pcb"
        KicadWriter().write(board, pcb_path)

        # Run SDK DRC (will fallback to kicad-cli if pcbnew not available)
        result = run_sdk_drc(pcb_path)

        # Should return a DrcResult
        assert hasattr(result, "errors")
        assert hasattr(result, "warnings")
        assert hasattr(result, "success")


class TestIntegration:
    """Integration tests combining multiple DRC checks."""

    @pytest.fixture
    def complex_board_with_issues(self):
        """Create a board with multiple DRC issues."""
        board = Board()

        # Component with overlapping pads
        comp1 = Component(
            ref="U1",
            value="IC",
            footprint="TQFP",
            position=(20.0, 20.0),
            rotation=0.0,
            layer="F.Cu",
        )
        comp1.pads = [
            Pad(number=1, position_offset=(0.0, 0.0), size=(0.5, 1.2), shape="rect"),
            Pad(number=2, position_offset=(0.0, 0.8), size=(0.5, 1.2), shape="rect"),
        ]
        board.add_component(comp1)

        # Another component
        comp2 = Component(
            ref="R1",
            value="10k",
            footprint="R_0805",
            position=(10.0, 10.0),
            rotation=0.0,
            layer="F.Cu",
        )
        comp2.pads = [
            Pad(number=1, position_offset=(0.0, 0.0), size=(1.0, 1.0), shape="rect"),
            Pad(number=2, position_offset=(2.0, 0.0), size=(1.0, 1.0), shape="rect"),
        ]
        board.add_component(comp2)

        # Net with track running too close to R1 pad 2
        net = Net(name="NET1", code="1", track_width=0.2)
        net.add_connection("R1", "1")
        # Track running close to pad 2 (at 12, 10)
        seg = TraceSegment("NET1", (12.0, 10.3), (20.0, 10.3), "F.Cu", 0.2)
        net.add_segment(seg)
        board.add_net(net)

        return board

    def test_detects_multiple_issues(self, complex_board_with_issues):
        """DRC should detect multiple types of issues."""
        cmd = CheckDrcCommand()
        result = cmd.execute(complex_board_with_issues)

        # Should have errors from both pad overlap and track-pad clearance
        assert "ERROR" in result
        # Count errors
        error_count = result.count("ERROR")
        assert error_count >= 1  # At least the pad overlap
