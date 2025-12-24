#!/usr/bin/env python3
"""
Integration test for via types (through, blind, buried).

Tests:
- Through-hole vias spanning all layers
- Blind vias spanning outer to inner layer
- Buried vias spanning inner to inner layer
- Via layer pair validation
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
from pcb_tool.routing.via_placer import ViaPlacement
from pcb_tool.kicad_writer import KicadWriter
from pcb_tool.footprint_library import get_footprint_pads

# Import from existing test infrastructure
from tests.integration.test_routing_scenarios import DRCConfig, RoutingTestCase

# Import from 4-layer test infrastructure
from tests.integration.test_4layer_power import (
    MultiLayerTestCase, route_board_multilayer, add_traces_to_board_multilayer
)


# =============================================================================
# TEST CASE: Via Types Validation
# =============================================================================

class TestViaTypes:
    """Test through, blind, and buried via creation."""

    def test_through_via_creation(self, tmp_path):
        """Test that through-hole vias span all layers."""
        layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        board = Board()
        board.layers = layers

        # Create a through via
        via = Via(
            net_name="TEST",
            position=(10.0, 10.0),
            size=0.8,
            drill=0.4,
            layers=("F.Cu", "In1.Cu", "In2.Cu", "B.Cu"),
            via_type="through"
        )

        # Verify via properties
        assert via.via_type == "through"
        assert via.layers[0] == "F.Cu"
        assert via.layers[-1] == "B.Cu"
        assert len(via.layers) == 4
        assert via.is_through_hole

    def test_blind_via_top_creation(self, tmp_path):
        """Test that blind vias from top span F.Cu to inner layer."""
        layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        board = Board()
        board.layers = layers

        # Create a blind via from top
        via = Via(
            net_name="TEST",
            position=(10.0, 10.0),
            size=0.6,
            drill=0.3,
            layers=("F.Cu", "In1.Cu"),
            via_type="blind"
        )

        # Verify via properties
        assert via.via_type == "blind"
        assert via.layers[0] == "F.Cu"
        assert via.layers[-1] == "In1.Cu"
        assert len(via.layers) == 2
        assert via.is_blind
        assert not via.is_through_hole
        assert not via.is_buried

    def test_blind_via_bottom_creation(self, tmp_path):
        """Test that blind vias from bottom span inner to B.Cu."""
        layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        board = Board()
        board.layers = layers

        # Create a blind via from bottom
        via = Via(
            net_name="TEST",
            position=(10.0, 10.0),
            size=0.6,
            drill=0.3,
            layers=("In2.Cu", "B.Cu"),
            via_type="blind"
        )

        # Verify via properties
        assert via.via_type == "blind"
        assert via.layers[0] == "In2.Cu"
        assert via.layers[-1] == "B.Cu"
        assert len(via.layers) == 2
        assert via.is_blind
        assert not via.is_through_hole
        assert not via.is_buried

    def test_buried_via_creation(self, tmp_path):
        """Test that buried vias span only inner layers."""
        layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        board = Board()
        board.layers = layers

        # Create a buried via
        via = Via(
            net_name="TEST",
            position=(10.0, 10.0),
            size=0.5,
            drill=0.25,
            layers=("In1.Cu", "In2.Cu"),
            via_type="buried"
        )

        # Verify via properties
        assert via.via_type == "buried"
        assert via.layers[0] == "In1.Cu"
        assert via.layers[-1] == "In2.Cu"
        assert len(via.layers) == 2
        assert via.is_buried
        assert not via.is_through_hole
        assert not via.is_blind

    def test_via_type_detection(self, tmp_path):
        """Test that via type is correctly detected from layers."""
        # Through-hole
        through = Via(
            net_name="T", position=(0, 0), size=0.8, drill=0.4,
            layers=("F.Cu", "B.Cu"), via_type="through"
        )
        assert through.is_through_hole

        # Blind from top
        blind_top = Via(
            net_name="BT", position=(0, 0), size=0.6, drill=0.3,
            layers=("F.Cu", "In1.Cu"), via_type="blind"
        )
        assert blind_top.is_blind
        assert not blind_top.is_through_hole

        # Buried
        buried = Via(
            net_name="BU", position=(0, 0), size=0.5, drill=0.25,
            layers=("In1.Cu", "In2.Cu"), via_type="buried"
        )
        assert buried.is_buried
        assert not buried.is_blind
        assert not buried.is_through_hole

    def test_via_in_kicad_output(self, tmp_path):
        """Test that vias are correctly written to KiCad output."""
        test = RoutingTestCase("via_output")
        test.drc.board_width_mm = 30.0
        test.drc.board_height_mm = 30.0

        # Components
        test.create_component("R1", "10k", "R_0805", x=10, y=15)
        test.create_component("R2", "10k", "R_0805", x=20, y=15)

        # Net with via
        test.create_net("VIA_TEST", [("R1", "1"), ("R2", "1")])

        # Add a via manually
        via = Via(
            net_name="VIA_TEST",
            position=(15.0, 15.0),
            size=0.8,
            drill=0.4,
            layers=("F.Cu", "B.Cu"),
            via_type="through"
        )
        test.board.nets["VIA_TEST"].add_via(via)

        # Write
        output_path = tmp_path / "via_output.kicad_pcb"
        KicadWriter().write(test.board, output_path)

        # Check output
        content = output_path.read_text()
        assert "(via" in content, "KiCad output should contain via"
        assert "(at 15" in content, "Via position should be in output"

    def test_via_placer_layer_support(self, tmp_path):
        """Test that ViaPlacement supports multi-layer boards."""
        layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        grid = RoutingGrid(
            width_mm=30.0,
            height_mm=30.0,
            resolution_mm=0.4,
            layers=layers
        )

        via_placer = ViaPlacement(grid)

        # Test get_via_layers for through via
        through_layers = via_placer.get_via_layers("F.Cu", "B.Cu", "through")
        assert through_layers == tuple(layers), f"Through via should span all layers, got {through_layers}"

        # Test get_via_layers for blind via
        blind_layers = via_placer.get_via_layers("F.Cu", "In1.Cu", "blind")
        assert "F.Cu" in blind_layers
        assert "In1.Cu" in blind_layers
        assert "B.Cu" not in blind_layers

    def test_via_placer_determine_type(self, tmp_path):
        """Test that ViaPlacement correctly determines via type."""
        layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        grid = RoutingGrid(
            width_mm=30.0,
            height_mm=30.0,
            resolution_mm=0.4,
            layers=layers
        )

        via_placer = ViaPlacement(grid)

        # Through via
        via_type = via_placer.determine_via_type(("F.Cu", "In1.Cu", "In2.Cu", "B.Cu"))
        assert via_type == "through"

        # Blind via (top)
        via_type = via_placer.determine_via_type(("F.Cu", "In1.Cu"))
        assert via_type == "blind"

        # Blind via (bottom)
        via_type = via_placer.determine_via_type(("In2.Cu", "B.Cu"))
        assert via_type == "blind"

        # Buried via
        via_type = via_placer.determine_via_type(("In1.Cu", "In2.Cu"))
        assert via_type == "buried"

    def test_pathfinder_allowed_via_types(self, tmp_path):
        """Test that PathFinder respects allowed via types."""
        layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        grid = RoutingGrid(
            width_mm=30.0,
            height_mm=30.0,
            resolution_mm=0.4,
            layers=layers
        )

        # Through-only pathfinder
        pf_through = PathFinder(grid, allowed_via_types=["through"])
        assert "through" in pf_through.allowed_via_types
        assert "blind" not in pf_through.allowed_via_types

        # All via types
        pf_all = PathFinder(grid, allowed_via_types=["through", "blind", "buried"])
        assert "through" in pf_all.allowed_via_types
        assert "blind" in pf_all.allowed_via_types
        assert "buried" in pf_all.allowed_via_types

    def test_via_layer_pair_output(self, tmp_path):
        """Test that KiCad output has correct layer pairs for vias."""
        test = RoutingTestCase("via_layer_pair")
        test.drc.board_width_mm = 30.0
        test.drc.board_height_mm = 30.0

        # Component
        test.create_component("R1", "10k", "R_0805", x=15, y=15)

        # Net
        test.create_net("NET1", [("R1", "1"), ("R1", "2")])

        # Add through via
        through_via = Via(
            net_name="NET1",
            position=(15.0, 10.0),
            size=0.8,
            drill=0.4,
            layers=("F.Cu", "B.Cu"),
            via_type="through"
        )
        test.board.nets["NET1"].add_via(through_via)

        # Write
        output_path = tmp_path / "via_layer_pair.kicad_pcb"
        KicadWriter().write(test.board, output_path)

        content = output_path.read_text()

        # KiCad format for via layers: (layers "F.Cu" "B.Cu")
        assert '(layers "F.Cu" "B.Cu")' in content, "Via should have F.Cu/B.Cu layer pair"

    def test_4layer_board_with_multiple_via_types(self, tmp_path):
        """Test a 4-layer board with different via types."""
        layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        test = MultiLayerTestCase("multi_via_types", layers)
        test.drc.board_width_mm = 40.0
        test.drc.board_height_mm = 40.0

        # Components on top
        test.create_component("R1", "10k", "R_0805", x=10, y=20)
        test.create_component("R2", "10k", "R_0805", x=30, y=20)

        # Nets
        test.create_net("NET1", [("R1", "1"), ("R2", "1")])
        test.create_net("NET2", [("R1", "2"), ("R2", "2")])

        # Add different via types manually
        # Through via
        test.board.nets["NET1"].add_via(Via(
            net_name="NET1",
            position=(15.0, 20.0),
            size=0.8,
            drill=0.4,
            layers=("F.Cu", "In1.Cu", "In2.Cu", "B.Cu"),
            via_type="through"
        ))

        # Blind via (F.Cu to In1.Cu)
        test.board.nets["NET2"].add_via(Via(
            net_name="NET2",
            position=(25.0, 20.0),
            size=0.6,
            drill=0.3,
            layers=("F.Cu", "In1.Cu"),
            via_type="blind"
        ))

        # Write
        output_path = tmp_path / "multi_via_types.kicad_pcb"
        KicadWriter().write(test.board, output_path)

        content = output_path.read_text()

        # Verify inner layers in output
        assert '"In1.Cu"' in content
        assert '"In2.Cu"' in content

        # Verify vias present
        assert "(via" in content

    def test_via_properties(self, tmp_path):
        """Test Via dataclass properties."""
        # Test start_layer and end_layer properties if they exist
        via = Via(
            net_name="TEST",
            position=(10.0, 10.0),
            size=0.8,
            drill=0.4,
            layers=("F.Cu", "In1.Cu", "In2.Cu", "B.Cu"),
            via_type="through"
        )

        # Check properties exist
        assert hasattr(via, 'layers')
        assert hasattr(via, 'via_type')
        assert hasattr(via, 'is_through_hole')
        assert hasattr(via, 'is_blind')
        assert hasattr(via, 'is_buried')

        # Verify start/end layers accessible
        assert via.layers[0] == "F.Cu"
        assert via.layers[-1] == "B.Cu"
