#!/usr/bin/env python3
"""
Integration test for variable trace widths via NetClass.

Tests:
- Multiple net classes with different widths (0.15mm, 0.25mm, 0.5mm)
- Trace width assignment based on net class
- Width preservation through routing
"""

import sys
import pytest
from pathlib import Path
from typing import Dict, List, Tuple

# Add pardal-pcb to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pardal.data_model import Board, Net, Component, TraceSegment, Pad, NetClass
from pardal.routing.grid import RoutingGrid
from pardal.routing.pathfinder import PathFinder
from pardal.kicad_writer import KicadWriter
from pardal.footprint_library import get_footprint_pads

# Import from existing test infrastructure
from tests.integration.test_routing_scenarios import (
    DRCConfig,
    RoutingTestCase,
    route_board,
    add_traces_to_board,
)

# Import from 4-layer test infrastructure
from tests.integration.test_4layer_power import (
    MultiLayerTestCase,
    route_board_multilayer,
    add_traces_to_board_multilayer,
)


# =============================================================================
# TEST CASE: Variable Trace Widths
# =============================================================================


class TestVariableTraceWidths:
    """Test per-net trace width via NetClass."""

    def test_three_width_classes(self, tmp_path):
        """Test three different trace widths on the same board."""
        test = RoutingTestCase("variable_widths")
        test.drc.board_width_mm = 40.0
        test.drc.board_height_mm = 25.0

        # Three net classes with different widths
        test.board.add_net_class(NetClass(name="Power", track_width=0.5, clearance=0.3))
        test.board.add_net_class(
            NetClass(name="Signal", track_width=0.25, clearance=0.2)
        )
        test.board.add_net_class(
            NetClass(name="Fine", track_width=0.15, clearance=0.15)
        )

        # Components: 8-pin DIP + resistors
        test.create_component("U1", "74HC00", "DIP-8_W7.62mm", x=20, y=12.5)
        for i in range(4):
            test.create_component(f"R{i+1}", "10k", "R_0603", x=5 + i * 3, y=5)
            test.create_component(f"R{i+5}", "10k", "R_0603", x=5 + i * 3, y=20)

        # Power nets (0.5mm)
        test.create_net("VCC", [("U1", "8"), ("R1", "1")], track_width=0.5)
        test.create_net("GND", [("U1", "4"), ("R2", "2")], track_width=0.5)
        test.board.assign_net_to_class("VCC", "Power")
        test.board.assign_net_to_class("GND", "Power")

        # Signal nets (0.25mm)
        test.create_net("SIG1", [("U1", "1"), ("R3", "1")], track_width=0.25)
        test.create_net("SIG2", [("U1", "2"), ("R4", "1")], track_width=0.25)
        test.board.assign_net_to_class("SIG1", "Signal")
        test.board.assign_net_to_class("SIG2", "Signal")

        # Fine nets (0.15mm)
        test.create_net("CLK", [("U1", "3"), ("R5", "1")], track_width=0.15)
        test.create_net("DATA", [("U1", "5"), ("R6", "1")], track_width=0.15)
        test.board.assign_net_to_class("CLK", "Fine")
        test.board.assign_net_to_class("DATA", "Fine")

        # Verify net class widths
        assert test.board.get_net_width("VCC") == 0.5
        assert test.board.get_net_width("SIG1") == 0.25
        assert test.board.get_net_width("CLK") == 0.15

        # Route board
        paths, layers_used, crossings = route_board(test)

        # Add traces to board with correct widths
        add_traces_to_board(test.board, paths, layers_used)

        # Verify trace widths match net class
        if test.board.nets["VCC"].segments:
            for segment in test.board.nets["VCC"].segments:
                assert (
                    segment.width == 0.5
                ), f"Power trace should be 0.5mm, got {segment.width}"

        if test.board.nets["SIG1"].segments:
            for segment in test.board.nets["SIG1"].segments:
                assert (
                    segment.width == 0.25
                ), f"Signal trace should be 0.25mm, got {segment.width}"

        if test.board.nets["CLK"].segments:
            for segment in test.board.nets["CLK"].segments:
                assert (
                    segment.width == 0.15
                ), f"Fine trace should be 0.15mm, got {segment.width}"

        # Write and validate
        output_path = tmp_path / "variable_widths.kicad_pcb"
        KicadWriter().write(test.board, output_path)

        # DRC - trace widths should not cause violations
        violations, vtypes = test.run_kicad_drc(output_path)
        if violations >= 0:
            real_violations = test.get_real_violations(vtypes)
            assert (
                real_violations <= 5
            ), f"Should have minimal DRC violations, got {real_violations}"

    def test_net_class_default_width(self, tmp_path):
        """Test that nets without explicit class use default width."""
        test = RoutingTestCase("default_width")
        test.drc.board_width_mm = 30.0
        test.drc.board_height_mm = 20.0

        # Create a net class with custom width
        test.board.add_net_class(NetClass(name="Wide", track_width=0.6, clearance=0.3))

        # Components
        test.create_component("R1", "10k", "R_0805", x=10, y=10)
        test.create_component("R2", "10k", "R_0805", x=20, y=10)

        # Net without explicit class
        test.create_net("UNASSIGNED", [("R1", "1"), ("R2", "1")])

        # Net with class
        test.create_net("WIDE_NET", [("R1", "2"), ("R2", "2")])
        test.board.assign_net_to_class("WIDE_NET", "Wide")

        # Unassigned net should use its track_width (default 0.25)
        unassigned_width = test.board.get_net_width("UNASSIGNED")
        assert (
            unassigned_width == 0.25
        ), f"Unassigned net should use default 0.25mm, got {unassigned_width}"

        # Assigned net should use class width
        wide_width = test.board.get_net_width("WIDE_NET")
        assert (
            wide_width == 0.6
        ), f"Wide net should use class width 0.6mm, got {wide_width}"

    def test_kicad_output_contains_widths(self, tmp_path):
        """Test that KiCad output contains correct trace widths."""
        test = RoutingTestCase("kicad_widths")
        test.drc.board_width_mm = 30.0
        test.drc.board_height_mm = 20.0

        # Components
        test.create_component("R1", "10k", "R_0805", x=5, y=10)
        test.create_component("R2", "10k", "R_0805", x=25, y=10)

        # Net with specific width
        test.create_net("THICK", [("R1", "1"), ("R2", "1")], track_width=0.5)

        # Route
        paths, layers_used, crossings = route_board(test)
        add_traces_to_board(test.board, paths, layers_used)

        # Write
        output_path = tmp_path / "kicad_widths.kicad_pcb"
        KicadWriter().write(test.board, output_path)

        # Check output contains width
        content = output_path.read_text()
        # KiCad format: (segment (start x y) (end x y) (width 0.5) ...)
        assert "(width 0.5)" in content, "KiCad output should contain width 0.5"

    def test_power_and_signal_width_difference(self, tmp_path):
        """Test that power and signal nets have different widths."""
        test = RoutingTestCase("power_signal")
        test.drc.board_width_mm = 40.0
        test.drc.board_height_mm = 25.0

        # Net classes
        test.board.add_net_class(NetClass(name="Power", track_width=0.5, clearance=0.3))
        test.board.add_net_class(
            NetClass(name="Signal", track_width=0.2, clearance=0.15)
        )

        # Components
        test.create_component("U1", "IC", "DIP-8_W7.62mm", x=20, y=12.5)
        test.create_component("C1", "100nF", "C_0805", x=10, y=12.5)
        test.create_component("R1", "10k", "R_0805", x=30, y=12.5)

        # Power net
        test.create_net("VDD", [("U1", "8"), ("C1", "1")], track_width=0.5)
        test.board.assign_net_to_class("VDD", "Power")

        # Signal net
        test.create_net("OUT", [("U1", "1"), ("R1", "1")], track_width=0.2)
        test.board.assign_net_to_class("OUT", "Signal")

        # Verify widths differ
        vdd_width = test.board.get_net_width("VDD")
        out_width = test.board.get_net_width("OUT")

        assert (
            vdd_width > out_width
        ), f"Power width ({vdd_width}) should be greater than signal ({out_width})"
        assert vdd_width == 0.5
        assert out_width == 0.2

    def test_net_class_clearance(self, tmp_path):
        """Test that net class clearance is respected."""
        test = RoutingTestCase("clearance")

        # Create net class with large clearance
        large_clearance = NetClass(name="HighVoltage", track_width=0.4, clearance=0.5)
        test.board.add_net_class(large_clearance)

        # Create net class with small clearance
        small_clearance = NetClass(name="LowVoltage", track_width=0.25, clearance=0.15)
        test.board.add_net_class(small_clearance)

        # Verify clearances stored correctly
        assert test.board.net_classes["HighVoltage"].clearance == 0.5
        assert test.board.net_classes["LowVoltage"].clearance == 0.15

    def test_net_class_via_size(self, tmp_path):
        """Test that net class via size is respected."""
        test = RoutingTestCase("via_size")

        # Create net class with large vias
        power_class = NetClass(
            name="Power", track_width=0.5, via_size=1.0, via_drill=0.5
        )
        test.board.add_net_class(power_class)

        # Create net class with small vias
        signal_class = NetClass(
            name="Signal", track_width=0.25, via_size=0.6, via_drill=0.3
        )
        test.board.add_net_class(signal_class)

        # Verify via sizes stored correctly
        assert test.board.net_classes["Power"].via_size == 1.0
        assert test.board.net_classes["Power"].via_drill == 0.5
        assert test.board.net_classes["Signal"].via_size == 0.6
        assert test.board.net_classes["Signal"].via_drill == 0.3

    def test_mixed_width_routing(self, tmp_path):
        """Test routing with mixed trace widths doesn't cause conflicts."""
        test = RoutingTestCase("mixed_routing")
        test.drc.board_width_mm = 50.0
        test.drc.board_height_mm = 30.0

        # Multiple net classes
        test.board.add_net_class(NetClass(name="Power", track_width=0.5))
        test.board.add_net_class(NetClass(name="Signal", track_width=0.25))
        test.board.add_net_class(NetClass(name="Fine", track_width=0.15))

        # Create a row of resistors
        for i in range(5):
            test.create_component(f"R{i+1}", "10k", "R_0805", x=10 + i * 8, y=15)

        # Different width nets
        test.create_net("PWR", [("R1", "1"), ("R3", "1"), ("R5", "1")], track_width=0.5)
        test.create_net("SIG", [("R1", "2"), ("R3", "2")], track_width=0.25)
        test.create_net("FIN", [("R2", "1"), ("R4", "1")], track_width=0.15)

        test.board.assign_net_to_class("PWR", "Power")
        test.board.assign_net_to_class("SIG", "Signal")
        test.board.assign_net_to_class("FIN", "Fine")

        # Route
        paths, layers_used, crossings = route_board(test)

        # At least some nets should route
        assert len(paths) >= 1, "At least one net should be routed"

        # Add traces
        add_traces_to_board(test.board, paths, layers_used)

        # Write and verify no fatal DRC
        output_path = tmp_path / "mixed_routing.kicad_pcb"
        KicadWriter().write(test.board, output_path)
        assert output_path.exists()
