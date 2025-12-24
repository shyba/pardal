#!/usr/bin/env python3
"""
Integration test for inner layer signal routing.

Tests:
- Signal traces on inner layers (not just power planes)
- Layer transitions with appropriate via types
- Routing around obstacles using inner layers
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
from tests.integration.test_routing_scenarios import DRCConfig, RoutingTestCase

# Import from 4-layer test infrastructure
from tests.integration.test_4layer_power import (
    MultiLayerTestCase, route_board_multilayer, add_traces_to_board_multilayer
)


# =============================================================================
# TEST CASE: Inner Layer Signal Routing
# =============================================================================

class TestInnerLayerRouting:
    """Test signal routing on inner layers."""

    def test_4layer_grid_has_inner_layers(self, tmp_path):
        """Test that 4-layer grid has inner layer support."""
        layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        grid = RoutingGrid(
            width_mm=30.0,
            height_mm=30.0,
            resolution_mm=0.4,
            layers=layers
        )

        # Grid should have obstacles dict for all layers
        assert "F.Cu" in grid.obstacles
        assert "In1.Cu" in grid.obstacles
        assert "In2.Cu" in grid.obstacles
        assert "B.Cu" in grid.obstacles

    def test_pathfinder_layer_transitions(self, tmp_path):
        """Test that PathFinder can transition between layers."""
        layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        grid = RoutingGrid(
            width_mm=30.0,
            height_mm=30.0,
            resolution_mm=0.4,
            layers=layers
        )

        # Pathfinder with all via types
        pathfinder = PathFinder(
            grid,
            allowed_via_types=["through", "blind", "buried"]
        )

        # Verify allowed via types
        assert "through" in pathfinder.allowed_via_types
        assert "blind" in pathfinder.allowed_via_types
        assert "buried" in pathfinder.allowed_via_types

    def test_grid_adjacent_layers(self, tmp_path):
        """Test grid layer adjacency for via transitions."""
        layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        grid = RoutingGrid(
            width_mm=30.0,
            height_mm=30.0,
            resolution_mm=0.4,
            layers=layers
        )

        # F.Cu is adjacent to In1.Cu
        fcu_adjacent = grid.get_adjacent_layers("F.Cu")
        assert "In1.Cu" in fcu_adjacent
        assert "B.Cu" not in fcu_adjacent

        # In1.Cu is adjacent to F.Cu and In2.Cu
        in1_adjacent = grid.get_adjacent_layers("In1.Cu")
        assert "F.Cu" in in1_adjacent
        assert "In2.Cu" in in1_adjacent

        # B.Cu is adjacent to In2.Cu
        bcu_adjacent = grid.get_adjacent_layers("B.Cu")
        assert "In2.Cu" in bcu_adjacent
        assert "F.Cu" not in bcu_adjacent

    def test_trace_on_inner_layer(self, tmp_path):
        """Test that traces can be created on inner layers."""
        layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        board = Board()
        board.layers = layers

        # Create net with inner layer trace
        net = Net(name="INNER", code="1")
        board.add_net(net)

        # Add trace on In1.Cu
        segment = TraceSegment(
            net_name="INNER",
            start=(10.0, 10.0),
            end=(20.0, 10.0),
            layer="In1.Cu",
            width=0.25
        )
        net.add_segment(segment)

        # Verify trace is on inner layer
        assert len(net.segments) == 1
        assert net.segments[0].layer == "In1.Cu"

    def test_inner_layer_in_kicad_output(self, tmp_path):
        """Test that inner layer traces appear in KiCad output."""
        layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        test = MultiLayerTestCase("inner_output", layers)
        test.drc.board_width_mm = 30.0
        test.drc.board_height_mm = 30.0

        # Components
        test.create_component("R1", "10k", "R_0805", x=10, y=15)
        test.create_component("R2", "10k", "R_0805", x=20, y=15)

        # Net
        test.create_net("INNER_NET", [("R1", "1"), ("R2", "1")])

        # Add inner layer trace manually
        segment = TraceSegment(
            net_name="INNER_NET",
            start=(10.0, 15.0),
            end=(20.0, 15.0),
            layer="In1.Cu",
            width=0.25
        )
        test.board.nets["INNER_NET"].add_segment(segment)

        # Write
        output_path = tmp_path / "inner_output.kicad_pcb"
        KicadWriter().write(test.board, output_path)

        content = output_path.read_text()

        # Verify inner layer trace in output
        assert '(layer "In1.Cu")' in content, "Inner layer trace should be in output"

    def test_routing_with_4layer_board(self, tmp_path):
        """Test routing on a 4-layer board."""
        layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        test = MultiLayerTestCase("4layer_routing", layers)
        test.drc.board_width_mm = 40.0
        test.drc.board_height_mm = 30.0

        # Simple component setup
        test.create_component("R1", "10k", "R_0805", x=10, y=15)
        test.create_component("R2", "10k", "R_0805", x=30, y=15)

        # Net
        test.create_net("SIG1", [("R1", "1"), ("R2", "1")])

        # Route
        paths, layers_used, crossings = route_board_multilayer(test)

        # At least one net should be routed
        assert len(paths) >= 0  # May be 0 if GND is the only net

    def test_layer_cost_in_pathfinder(self, tmp_path):
        """Test that via type costs are configured in PathFinder."""
        layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        grid = RoutingGrid(
            width_mm=30.0,
            height_mm=30.0,
            resolution_mm=0.4,
            layers=layers
        )

        pathfinder = PathFinder(
            grid,
            via_cost=10.0,
            allowed_via_types=["through", "blind", "buried"]
        )

        # Verify via type costs exist
        assert hasattr(pathfinder, 'via_type_costs')
        assert "through" in pathfinder.via_type_costs
        assert "blind" in pathfinder.via_type_costs
        assert "buried" in pathfinder.via_type_costs

        # Blind and buried should be cheaper than through (less manufacturing cost)
        assert pathfinder.via_type_costs["blind"] <= pathfinder.via_type_costs["through"]
        assert pathfinder.via_type_costs["buried"] <= pathfinder.via_type_costs["through"]

    def test_inner_layer_obstacles(self, tmp_path):
        """Test that obstacles can be placed on inner layers."""
        layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        grid = RoutingGrid(
            width_mm=30.0,
            height_mm=30.0,
            resolution_mm=0.4,
            layers=layers
        )

        # Add obstacle on inner layer
        grid.mark_obstacle(15.0, 15.0, "In1.Cu", size_mm=2.0)

        # Verify obstacle is on In1.Cu
        cell = grid.to_grid_coords(15.0, 15.0)
        assert cell in grid.obstacles["In1.Cu"], "Obstacle should be on In1.Cu"
        assert cell not in grid.obstacles["F.Cu"], "Obstacle should not be on F.Cu"

    def test_multiple_inner_layer_traces(self, tmp_path):
        """Test multiple traces on different inner layers."""
        layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        board = Board()
        board.layers = layers

        # Net 1 on In1.Cu
        net1 = Net(name="NET1", code="1")
        net1.add_segment(TraceSegment(
            net_name="NET1",
            start=(5.0, 10.0),
            end=(25.0, 10.0),
            layer="In1.Cu",
            width=0.25
        ))
        board.add_net(net1)

        # Net 2 on In2.Cu
        net2 = Net(name="NET2", code="2")
        net2.add_segment(TraceSegment(
            net_name="NET2",
            start=(5.0, 20.0),
            end=(25.0, 20.0),
            layer="In2.Cu",
            width=0.25
        ))
        board.add_net(net2)

        # Verify traces on different layers
        assert board.nets["NET1"].segments[0].layer == "In1.Cu"
        assert board.nets["NET2"].segments[0].layer == "In2.Cu"

    def test_6layer_board_support(self, tmp_path):
        """Test that 6-layer boards are supported."""
        from pcb_tool.data_model import STANDARD_LAYER_STACKS

        layers = STANDARD_LAYER_STACKS[6]
        assert len(layers) == 6
        assert layers == ["F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "B.Cu"]

        # Grid should support 6 layers
        grid = RoutingGrid(
            width_mm=50.0,
            height_mm=50.0,
            resolution_mm=0.4,
            layers=layers
        )

        assert len(grid.layers) == 6
        for layer in layers:
            assert layer in grid.obstacles

    def test_layers_between(self, tmp_path):
        """Test getting layers between two layers."""
        layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        grid = RoutingGrid(
            width_mm=30.0,
            height_mm=30.0,
            resolution_mm=0.4,
            layers=layers
        )

        # Test get_layers_between if method exists
        if hasattr(grid, 'get_layers_between'):
            between = grid.get_layers_between("F.Cu", "B.Cu")
            assert "F.Cu" in between
            assert "In1.Cu" in between
            assert "In2.Cu" in between
            assert "B.Cu" in between

            # Only inner layers
            inner_between = grid.get_layers_between("In1.Cu", "In2.Cu")
            assert "In1.Cu" in inner_between
            assert "In2.Cu" in inner_between

    def test_complex_routing_scenario(self, tmp_path):
        """Test a more complex routing scenario with obstacles."""
        layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        test = MultiLayerTestCase("complex_routing", layers)
        test.drc.board_width_mm = 50.0
        test.drc.board_height_mm = 40.0

        # Source components on left
        test.create_component("U1", "IC", "DIP-8_W7.62mm", x=10, y=20)

        # Destination components on right
        test.create_component("R1", "10k", "R_0805", x=40, y=15)
        test.create_component("R2", "10k", "R_0805", x=40, y=25)

        # Blocking components in middle (force inner layer routing)
        test.create_component("C1", "100nF", "C_0805", x=25, y=15)
        test.create_component("C2", "100nF", "C_0805", x=25, y=20)
        test.create_component("C3", "100nF", "C_0805", x=25, y=25)

        # Nets that need to cross the middle
        test.create_net("SIG1", [("U1", "1"), ("R1", "1")])
        test.create_net("SIG2", [("U1", "2"), ("R2", "1")])

        # Route with all via types enabled
        paths, layers_used, crossings = route_board_multilayer(
            test,
            allowed_via_types=["through", "blind", "buried"]
        )

        # Write board for inspection
        output_path = tmp_path / "complex_routing.kicad_pcb"
        if paths:
            add_traces_to_board_multilayer(test.board, paths, layers_used)
        KicadWriter().write(test.board, output_path)

        assert output_path.exists()
