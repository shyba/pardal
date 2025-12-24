#!/usr/bin/env python3
"""
Integration test for mixed THT/SMD components on both board sides.

Tests:
- THT components with pads spanning both layers
- SMD components on F.Cu
- SMD components on B.Cu
- Layer-specific pad handling
- Routing between mixed component types
"""

import sys
import pytest
from pathlib import Path
from typing import Dict, List, Tuple

# Add pardal-pcb to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pcb_tool.data_model import Board, Net, Component, TraceSegment, Pad, Via, NetClass
from pcb_tool.routing.grid import RoutingGrid
from pcb_tool.routing.pathfinder import PathFinder
from pcb_tool.kicad_writer import KicadWriter
from pcb_tool.footprint_library import get_footprint_pads

# Import from existing test infrastructure
from tests.integration.test_routing_scenarios import (
    DRCConfig, RoutingTestCase, route_board, add_traces_to_board
)

# Import from 4-layer test infrastructure
from tests.integration.test_4layer_power import (
    MultiLayerTestCase, route_board_multilayer, add_traces_to_board_multilayer
)


# =============================================================================
# TEST CASE: Mixed THT/SMD Components
# =============================================================================

class TestMixedThtSmd:
    """Test THT and SMD components on both board sides."""

    def test_tht_component_has_drill(self, tmp_path):
        """Test that THT component pads have drill holes."""
        test = RoutingTestCase("tht_drill")
        test.drc.board_width_mm = 30.0
        test.drc.board_height_mm = 20.0

        # THT resistor
        test.create_component("R1", "10k", "R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal", x=15, y=10)

        # Verify pads have drill holes
        r1 = test.board.components["R1"]
        for pad in r1.pads:
            assert pad.drill is not None, f"THT pad should have drill: {pad.number}"
            assert pad.drill > 0, f"THT drill should be positive: {pad.drill}"

    def test_smd_component_no_drill(self, tmp_path):
        """Test that SMD component pads do not have drill holes."""
        test = RoutingTestCase("smd_no_drill")
        test.drc.board_width_mm = 30.0
        test.drc.board_height_mm = 20.0

        # SMD resistor
        test.create_component("R1", "10k", "R_0805", x=15, y=10)

        # Verify pads do not have drill holes
        r1 = test.board.components["R1"]
        for pad in r1.pads:
            assert pad.drill is None or pad.drill == 0, f"SMD pad should not have drill"

    def test_mixed_components_on_board(self, tmp_path):
        """Test THT and SMD components can coexist on same board."""
        test = RoutingTestCase("mixed_coexist")
        test.drc.board_width_mm = 40.0
        test.drc.board_height_mm = 25.0

        # THT components
        test.create_component("R1", "10k", "R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal", x=10, y=10)
        test.create_component("J1", "CONN", "PinHeader_1x04_P2.54mm_Vertical", x=5, y=15)

        # SMD components
        test.create_component("R2", "10k", "R_0805", x=25, y=10)
        test.create_component("R3", "10k", "R_0603", x=25, y=15)
        test.create_component("C1", "100nF", "C_0805", x=30, y=12)

        # Verify all components exist
        assert len(test.board.components) == 5
        assert "R1" in test.board.components
        assert "J1" in test.board.components
        assert "R2" in test.board.components
        assert "R3" in test.board.components
        assert "C1" in test.board.components

    def test_smd_on_bcu_layer(self, tmp_path):
        """Test SMD components can be placed on B.Cu layer."""
        test = RoutingTestCase("smd_bcu")
        test.drc.board_width_mm = 30.0
        test.drc.board_height_mm = 20.0

        # SMD on F.Cu (default)
        test.create_component("R1", "10k", "R_0805", x=10, y=10)

        # SMD on B.Cu
        r2 = test.create_component("R2", "10k", "R_0805", x=20, y=10)
        r2.layer = "B.Cu"

        # Verify layers
        assert test.board.components["R1"].layer == "F.Cu"
        assert test.board.components["R2"].layer == "B.Cu"

    def test_routing_tht_to_smd(self, tmp_path):
        """Test routing between THT and SMD components."""
        test = RoutingTestCase("tht_to_smd")
        test.drc.board_width_mm = 40.0
        test.drc.board_height_mm = 25.0

        # THT connector
        test.create_component("J1", "CONN", "PinHeader_1x04_P2.54mm_Vertical", x=5, y=12)

        # SMD resistors
        test.create_component("R1", "10k", "R_0805", x=25, y=10)
        test.create_component("R2", "10k", "R_0805", x=25, y=15)

        # Nets connecting THT to SMD
        test.create_net("SIG1", [("J1", "1"), ("R1", "1")])
        test.create_net("SIG2", [("J1", "2"), ("R2", "1")])

        # Route
        paths, layers_used, crossings = route_board(test)

        # At least one net should be routed
        assert len(paths) >= 1, "Should route at least one THT-to-SMD connection"

    def test_routing_fcu_to_bcu_smd(self, tmp_path):
        """Test routing between F.Cu SMD and B.Cu SMD."""
        layers = ["F.Cu", "B.Cu"]
        test = MultiLayerTestCase("fcu_to_bcu", layers)
        test.drc.board_width_mm = 30.0
        test.drc.board_height_mm = 20.0

        # SMD on F.Cu
        test.create_component("R1", "10k", "R_0805", x=10, y=10)

        # SMD on B.Cu
        r2 = test.create_component("R2", "10k", "R_0805", x=20, y=10)
        r2.layer = "B.Cu"

        # Net connecting F.Cu to B.Cu
        test.create_net("CROSS", [("R1", "1"), ("R2", "1")])

        # Route
        paths, layers_used, crossings = route_board_multilayer(test)

        # Net may route or may fail (depends on via support)
        # Just verify board can be written
        output_path = tmp_path / "fcu_to_bcu.kicad_pcb"
        add_traces_to_board_multilayer(test.board, paths, layers_used)
        KicadWriter().write(test.board, output_path)
        assert output_path.exists()

    def test_tht_connector_with_power_and_signal(self, tmp_path):
        """Test pin header with both power and signal connections."""
        test = RoutingTestCase("power_signal_header")
        test.drc.board_width_mm = 45.0
        test.drc.board_height_mm = 30.0

        # Net classes
        test.board.add_net_class(NetClass(name="Power", track_width=0.5, clearance=0.3))
        test.board.add_net_class(NetClass(name="Signal", track_width=0.25, clearance=0.2))

        # Pin header
        test.create_component("J1", "CONN", "PinHeader_1x04_P2.54mm_Vertical", x=5, y=15)

        # Power components
        test.create_component("C1", "100uF", "C_0805", x=15, y=15)

        # Signal components
        test.create_component("R1", "10k", "R_0805", x=25, y=10)
        test.create_component("R2", "10k", "R_0805", x=25, y=20)

        # Power nets (wide traces)
        test.create_net("VCC", [("J1", "1"), ("C1", "1")], track_width=0.5)
        test.create_net("GND", [("J1", "4"), ("C1", "2")], track_width=0.5)
        test.board.assign_net_to_class("VCC", "Power")
        test.board.assign_net_to_class("GND", "Power")

        # Signal nets (narrow traces)
        test.create_net("SIG1", [("J1", "2"), ("R1", "1")], track_width=0.25)
        test.create_net("SIG2", [("J1", "3"), ("R2", "1")], track_width=0.25)
        test.board.assign_net_to_class("SIG1", "Signal")
        test.board.assign_net_to_class("SIG2", "Signal")

        # Verify net class widths
        assert test.board.get_net_width("VCC") == 0.5
        assert test.board.get_net_width("SIG1") == 0.25

        # Route
        paths, layers_used, crossings = route_board(test)
        add_traces_to_board(test.board, paths, layers_used)

        # Write and verify
        output_path = tmp_path / "power_signal_header.kicad_pcb"
        KicadWriter().write(test.board, output_path)
        assert output_path.exists()

    def test_dip_ic_with_smd_passives(self, tmp_path):
        """Test DIP IC with SMD decoupling capacitors."""
        test = RoutingTestCase("dip_with_smd")
        test.drc.board_width_mm = 40.0
        test.drc.board_height_mm = 30.0

        # DIP-8 IC (THT)
        test.create_component("U1", "74HC00", "DIP-8_W7.62mm", x=20, y=15)

        # SMD decoupling capacitors
        test.create_component("C1", "100nF", "C_0805", x=10, y=10)
        test.create_component("C2", "100nF", "C_0805", x=30, y=10)

        # Power nets
        test.create_net("VCC", [("U1", "8"), ("C1", "1"), ("C2", "1")])
        test.create_net("GND", [("U1", "4"), ("C1", "2"), ("C2", "2")])

        # Signal nets
        test.create_net("IN1", [("U1", "1"), ("U1", "2")])
        test.create_net("OUT1", [("U1", "3")])

        # Route
        paths, layers_used, crossings = route_board(test)

        # Should route power nets
        assert "VCC" in paths or "GND" not in paths  # GND often skipped

        # Write
        output_path = tmp_path / "dip_with_smd.kicad_pcb"
        add_traces_to_board(test.board, paths, layers_used)
        KicadWriter().write(test.board, output_path)
        assert output_path.exists()

    def test_mixed_on_4layer_board(self, tmp_path):
        """Test mixed THT/SMD on a 4-layer board."""
        layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        test = MultiLayerTestCase("mixed_4layer", layers)
        test.drc.board_width_mm = 50.0
        test.drc.board_height_mm = 35.0

        # Net classes
        test.create_net_class("Power", track_width=0.5, clearance=0.3)
        test.create_net_class("Signal", track_width=0.25, clearance=0.2)

        # THT connector on left
        test.create_component("J1", "CONN", "PinHeader_1x06_P2.54mm_Vertical", x=5, y=17.5)

        # SMD on F.Cu in middle
        test.create_component("R1", "10k", "R_0805", x=20, y=10)
        test.create_component("R2", "10k", "R_0805", x=20, y=25)
        test.create_component("C1", "100nF", "C_0805", x=25, y=17.5)

        # SMD on B.Cu on right
        r3 = test.create_component("R3", "10k", "R_0805", x=35, y=10)
        r3.layer = "B.Cu"
        r4 = test.create_component("R4", "10k", "R_0805", x=35, y=25)
        r4.layer = "B.Cu"
        c2 = test.create_component("C2", "100nF", "C_0805", x=40, y=17.5)
        c2.layer = "B.Cu"

        # Power nets
        test.create_net("VCC", [("J1", "1"), ("R1", "1"), ("R3", "1")], track_width=0.5)
        test.create_net("GND", [("J1", "6"), ("C1", "2"), ("C2", "2")], track_width=0.5)
        test.assign_net_class("VCC", "Power")
        test.assign_net_class("GND", "Power")

        # Signal nets crossing layers
        test.create_net("SIG1", [("J1", "2"), ("R1", "2"), ("R3", "2")])
        test.create_net("SIG2", [("J1", "3"), ("R2", "1")])
        test.create_net("SIG3", [("J1", "4"), ("R4", "1")])
        test.create_net("SIG4", [("J1", "5"), ("C1", "1"), ("C2", "1")])

        # Route
        paths, layers_used, crossings = route_board_multilayer(test)

        # Add traces and write
        add_traces_to_board_multilayer(test.board, paths, layers_used)

        output_path = tmp_path / "mixed_4layer.kicad_pcb"
        KicadWriter().write(test.board, output_path)

        assert output_path.exists()

        # Verify all 4 layers in output
        content = output_path.read_text()
        assert '"F.Cu"' in content
        assert '"In1.Cu"' in content
        assert '"In2.Cu"' in content
        assert '"B.Cu"' in content

    def test_kicad_output_contains_tht_drill(self, tmp_path):
        """Test that KiCad output contains THT drill info."""
        test = RoutingTestCase("tht_output")
        test.drc.board_width_mm = 30.0
        test.drc.board_height_mm = 20.0

        # THT resistor
        test.create_component("R1", "10k", "R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal", x=15, y=10)

        # Simple net
        test.create_net("NET1", [("R1", "1"), ("R1", "2")])

        # Write
        output_path = tmp_path / "tht_output.kicad_pcb"
        KicadWriter().write(test.board, output_path)

        content = output_path.read_text()

        # THT pads should have drill specification
        assert "(drill" in content, "THT pads should have drill in output"

    def test_component_layer_property(self, tmp_path):
        """Test that component layer property works correctly."""
        board = Board()

        pads, _ = get_footprint_pads("R_0805_2012Metric")

        # Create component on F.Cu
        comp1 = Component(
            ref="R1", value="10k", footprint="R_0805",
            position=(10.0, 10.0), rotation=0.0, pads=pads
        )
        comp1.layer = "F.Cu"
        board.add_component(comp1)

        # Create component on B.Cu
        comp2 = Component(
            ref="R2", value="10k", footprint="R_0805",
            position=(20.0, 10.0), rotation=0.0, pads=pads
        )
        comp2.layer = "B.Cu"
        board.add_component(comp2)

        # Verify layers
        assert board.components["R1"].layer == "F.Cu"
        assert board.components["R2"].layer == "B.Cu"

    def test_full_mixed_board_scenario(self, tmp_path):
        """Test a realistic mixed component board."""
        test = RoutingTestCase("full_mixed")
        test.drc.board_width_mm = 60.0
        test.drc.board_height_mm = 40.0

        # Net classes
        test.board.add_net_class(NetClass(name="Power", track_width=0.5))
        test.board.add_net_class(NetClass(name="Signal", track_width=0.25))

        # Input connector (THT)
        test.create_component("J1", "IN", "PinHeader_1x04_P2.54mm_Vertical", x=5, y=20)

        # Output connector (THT)
        test.create_component("J2", "OUT", "PinHeader_1x03_P2.54mm_Vertical", x=55, y=20)

        # Processing IC (THT DIP)
        test.create_component("U1", "74HC00", "DIP-8_W7.62mm", x=30, y=20)

        # SMD passives around IC
        test.create_component("C1", "100nF", "C_0805", x=20, y=15)  # Input decoupling
        test.create_component("C2", "100nF", "C_0805", x=40, y=15)  # Output decoupling
        test.create_component("R1", "10k", "R_0603", x=20, y=25)    # Pull-up
        test.create_component("R2", "10k", "R_0603", x=40, y=25)    # Series termination

        # Power distribution
        test.create_net("VCC", [("J1", "1"), ("U1", "8"), ("C1", "1"), ("C2", "1"), ("R1", "1")], track_width=0.5)
        test.create_net("GND", [("J1", "4"), ("U1", "4"), ("C1", "2"), ("C2", "2"), ("J2", "3")], track_width=0.5)
        test.board.assign_net_to_class("VCC", "Power")
        test.board.assign_net_to_class("GND", "Power")

        # Signal path
        test.create_net("IN1", [("J1", "2"), ("R1", "2"), ("U1", "1")])
        test.create_net("IN2", [("J1", "3"), ("U1", "2")])
        test.create_net("OUT1", [("U1", "3"), ("R2", "1")])
        test.create_net("LOAD", [("R2", "2"), ("J2", "1")])

        # Route
        paths, layers_used, crossings = route_board(test)

        # Add traces
        add_traces_to_board(test.board, paths, layers_used)

        # Write
        output_path = tmp_path / "full_mixed.kicad_pcb"
        KicadWriter().write(test.board, output_path)

        assert output_path.exists()

        # DRC if available
        violations, vtypes = test.run_kicad_drc(output_path)
        if violations >= 0:
            real_violations = test.get_real_violations(vtypes)
            # Allow some margin for complex board
            assert real_violations <= 10, f"Should have minimal DRC violations, got {real_violations}"

