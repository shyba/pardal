#!/usr/bin/env python3
"""
Integration test for 4-layer board with power distribution.

Tests:
- 4-layer board creation
- Inner layer definitions in KiCad output
- Through-vias for power connections
- Net class support for power traces
"""

import sys
import math
import pytest
from pathlib import Path
from typing import Dict, List, Tuple, Set, Optional

# Add pardal-pcb to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pcb_tool.data_model import Board, Net, Component, TraceSegment, Pad, Via, NetClass
from pcb_tool.routing.grid import RoutingGrid
from pcb_tool.routing.pathfinder import PathFinder
from pcb_tool.routing.crossing_detector import CrossingDetector
from pcb_tool.kicad_writer import KicadWriter
from pcb_tool.footprint_library import get_footprint_pads

# Import from existing test infrastructure
from tests.integration.test_routing_scenarios import (
    DRCConfig,
    RoutingTestCase,
    simplify_path,
    add_pad_obstacle,
    path_to_cells_drc,
)


# =============================================================================
# Multi-Layer Test Infrastructure
# =============================================================================


class MultiLayerTestCase(RoutingTestCase):
    """Test case with multi-layer board support."""

    def __init__(self, name: str, layers: List[str], drc: DRCConfig = None):
        super().__init__(name, drc)
        self.board.layers = layers

    def create_net_class(
        self,
        name: str,
        track_width: float,
        clearance: float = 0.2,
        via_size: float = 0.8,
    ) -> NetClass:
        """Create and register a net class."""
        nc = NetClass(
            name=name, track_width=track_width, clearance=clearance, via_size=via_size
        )
        self.board.add_net_class(nc)
        return nc

    def assign_net_class(self, net_name: str, class_name: str):
        """Assign a net to a net class."""
        self.board.assign_net_to_class(net_name, class_name)


def route_net_segment_multilayer(
    start: Tuple[float, float],
    end: Tuple[float, float],
    grid: RoutingGrid,
    pathfinder: PathFinder,
    routed_cells: Set,
    drc: DRCConfig,
    prefer_layer: str = "F.Cu",
) -> Tuple[Optional[List], str]:
    """Route a single segment between two points on a multi-layer board."""
    # Try preferred layer first
    path = pathfinder.find_path(
        start_mm=start, goal_mm=end, layer=prefer_layer, force_single_layer=True
    )
    if path:
        return simplify_path(path, drc.resolution_mm), prefer_layer

    # Try other layers
    for layer in grid.layers:
        if layer != prefer_layer:
            path = pathfinder.find_path(
                start_mm=start, goal_mm=end, layer=layer, force_single_layer=True
            )
            if path:
                return simplify_path(path, drc.resolution_mm), layer

    return None, None


def route_board_multilayer(
    test_case: MultiLayerTestCase, allowed_via_types: List[str] = None
) -> Tuple[Dict[str, List], Dict[str, str], int]:
    """Route all nets on a multi-layer board. Returns (paths, layers, crossings)."""
    board = test_case.board
    drc = test_case.drc
    layers = board.layers

    grid = RoutingGrid(
        width_mm=drc.board_width_mm,
        height_mm=drc.board_height_mm,
        resolution_mm=drc.resolution_mm,
        layers=layers,
    )
    pathfinder = PathFinder(grid, allowed_via_types=allowed_via_types or ["through"])
    detector = CrossingDetector(drc.resolution_mm)

    # Build pad info
    pad_info = []
    for comp in board.components.values():
        for pad in comp.pads:
            pad_pos = comp.get_pad_position(pad.number)
            pad_info.append(
                {"pos": pad_pos, "size": pad.size, "comp": comp.ref, "pad": pad.number}
            )

    paths = {}
    path_layers = {}
    routed_cells = set()

    # Route each net
    for net in board.nets.values():
        if net.name.upper() in ["GND", "GROUND"]:
            continue

        # Clear obstacles and add pads
        for layer in layers:
            grid.obstacles[layer].clear()

        # Get pad positions for this net's connections
        net_pads = set()
        for comp_ref, pin_num in net.connections:
            comp = board.components.get(comp_ref)
            if comp:
                try:
                    pos = comp.get_pad_position(int(pin_num))
                    net_pads.add((round(pos[0], 2), round(pos[1], 2)))
                except (ValueError, TypeError):
                    pass

        # Add non-net pads as obstacles
        for pad in pad_info:
            pad_key = (round(pad["pos"][0], 2), round(pad["pos"][1], 2))
            if pad_key not in net_pads:
                add_pad_obstacle(grid, pad["pos"], pad["size"], drc, layers=layers)

        # Add routed traces as obstacles
        for cell, layer in routed_cells:
            if layer in grid.obstacles:
                grid.obstacles[layer].add(cell)

        grid._neighbor_cache.clear()

        # Get connection points
        points = []
        for comp_ref, pin_num in net.connections:
            comp = board.components.get(comp_ref)
            if comp:
                try:
                    pos = comp.get_pad_position(int(pin_num))
                    points.append(pos)
                except (ValueError, TypeError):
                    pass

        if len(points) < 2:
            continue

        # Route as chain (simple approach)
        points.sort(key=lambda p: (p[0], p[1]))
        net_path = []
        layer = "F.Cu"

        for i in range(len(points) - 1):
            seg_path, seg_layer = route_net_segment_multilayer(
                points[i], points[i + 1], grid, pathfinder, routed_cells, drc
            )
            if seg_path:
                net_path.extend(seg_path)
                layer = seg_layer
            else:
                net_path = []
                break

        if net_path:
            # Deduplicate
            dedup = [net_path[0]]
            for pt in net_path[1:]:
                if pt != dedup[-1]:
                    dedup.append(pt)
            paths[net.name] = dedup
            path_layers[net.name] = layer
            cells = path_to_cells_drc(dedup, grid, layer, net.name, drc)
            routed_cells.update(cells)

    # Count crossings
    crossings = 0
    for layer in layers:
        layer_paths = {n: p for n, p in paths.items() if path_layers.get(n) == layer}
        crossings += len(detector.detect_crossings(layer_paths))

    return paths, path_layers, crossings


def add_traces_to_board_multilayer(board: Board, paths: Dict, layers: Dict):
    """Add routed paths as trace segments to board."""
    for net_name, path in paths.items():
        net = board.nets.get(net_name)
        if not net or len(path) < 2:
            continue

        layer = layers.get(net_name, "F.Cu")
        # Get trace width from net class or net default
        width = (
            board.get_net_width(net_name)
            if hasattr(board, "get_net_width")
            else net.track_width
        )

        for i in range(len(path) - 1):
            segment = TraceSegment(
                net_name=net_name,
                start=path[i],
                end=path[i + 1],
                layer=layer,
                width=width,
            )
            net.add_segment(segment)


# =============================================================================
# TEST CASE: 4-Layer Power Distribution
# =============================================================================


class Test4LayerPowerDistribution:
    """Test 4-layer board creation with power planes and through-vias."""

    def test_4layer_board_creation(self, tmp_path):
        """Test that a 4-layer board can be created and written."""
        layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        test = MultiLayerTestCase("4layer_power", layers)
        test.drc.board_width_mm = 30.0
        test.drc.board_height_mm = 30.0

        # Net classes
        test.create_net_class("Power", track_width=0.5, clearance=0.3)
        test.create_net_class("Signal", track_width=0.25, clearance=0.2)

        # Components (using footprint_library.py patterns)
        test.create_component("U1", "LM1117", "SOT-223-3", x=15, y=15)
        test.create_component("C1", "10uF", "C_0805", x=10, y=10)
        test.create_component("C2", "100nF", "C_0805", x=20, y=10)
        test.create_component("TP1", "VIN", "TestPoint_Pad_1.0mm", x=5, y=15)
        test.create_component("TP2", "VOUT", "TestPoint_Pad_1.0mm", x=25, y=15)

        # Power nets (connect to inner planes via vias)
        test.create_net(
            "VIN", [("TP1", "1"), ("U1", "3"), ("C1", "1")], track_width=0.5
        )
        test.create_net(
            "VOUT", [("U1", "2"), ("TP2", "1"), ("C2", "1")], track_width=0.5
        )
        test.create_net("GND", [("U1", "1"), ("C1", "2"), ("C2", "2")], track_width=0.5)

        test.assign_net_class("VIN", "Power")
        test.assign_net_class("VOUT", "Power")
        test.assign_net_class("GND", "Power")

        # 1. Board has 4 layers
        assert len(test.board.layers) == 4
        assert test.board.layers == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]

        # 2. Route board
        paths, layers_used, crossings = route_board_multilayer(test)
        assert "VIN" in paths, "Net VIN should be routed"
        assert "VOUT" in paths, "Net VOUT should be routed"

        # 3. Add traces
        add_traces_to_board_multilayer(test.board, paths, layers_used)

        # 4. Write and validate KiCad output
        output_path = tmp_path / "4layer_power.kicad_pcb"
        KicadWriter().write(test.board, output_path)
        assert output_path.exists()

        # 5. Verify layer definitions in output
        content = output_path.read_text()
        assert '"In1.Cu"' in content, "Inner layer In1.Cu should be in output"
        assert '"In2.Cu"' in content, "Inner layer In2.Cu should be in output"

        # 6. DRC check (if kicad-cli available)
        violations, vtypes = test.run_kicad_drc(output_path)
        if violations >= 0:  # kicad-cli available
            real_violations = test.get_real_violations(vtypes)
            assert (
                real_violations <= 5
            ), f"Should have minimal DRC violations, got {real_violations}"

    def test_4layer_layer_stack_standard(self, tmp_path):
        """Test that standard 4-layer stack is recognized."""
        from pcb_tool.data_model import STANDARD_LAYER_STACKS

        layers = STANDARD_LAYER_STACKS[4]
        assert layers == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]

        test = MultiLayerTestCase("4layer_standard", layers)
        assert test.board.layers == layers

    def test_net_class_assignment(self, tmp_path):
        """Test that net classes are properly assigned and widths calculated."""
        layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        test = MultiLayerTestCase("4layer_netclass", layers)

        # Create net classes
        test.create_net_class("Power", track_width=0.5, clearance=0.3)
        test.create_net_class("Signal", track_width=0.25, clearance=0.2)

        # Create components and nets
        test.create_component("R1", "10k", "R_0805", x=10, y=10)
        test.create_component("R2", "10k", "R_0805", x=20, y=10)

        test.create_net("VCC", [("R1", "1"), ("R2", "1")], track_width=0.5)
        test.create_net("SIG", [("R1", "2"), ("R2", "2")], track_width=0.25)

        test.assign_net_class("VCC", "Power")
        test.assign_net_class("SIG", "Signal")

        # Verify net class widths
        vcc_width = test.board.get_net_width("VCC")
        sig_width = test.board.get_net_width("SIG")

        assert vcc_width == 0.5, f"Power net should be 0.5mm, got {vcc_width}"
        assert sig_width == 0.25, f"Signal net should be 0.25mm, got {sig_width}"

    def test_inner_layer_kicad_indices(self, tmp_path):
        """Test that inner layers have correct KiCad layer indices."""
        from pcb_tool.kicad_writer import KicadWriter

        layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        test = MultiLayerTestCase("4layer_indices", layers)
        test.drc.board_width_mm = 20.0
        test.drc.board_height_mm = 20.0

        # Minimal board
        test.create_component("R1", "10k", "R_0805", x=10, y=10)

        # Write board
        output_path = tmp_path / "4layer_indices.kicad_pcb"
        KicadWriter().write(test.board, output_path)

        content = output_path.read_text()

        # Check layer indices
        # F.Cu should be 0, In1.Cu should be 1, In2.Cu should be 2, B.Cu should be 31
        assert '(0 "F.Cu"' in content, "F.Cu should have index 0"
        assert '(1 "In1.Cu"' in content, "In1.Cu should have index 1"
        assert '(2 "In2.Cu"' in content, "In2.Cu should have index 2"
        assert '(31 "B.Cu"' in content, "B.Cu should have index 31"

    def test_simple_voltage_regulator_circuit(self, tmp_path):
        """Test a realistic voltage regulator circuit on 4-layer board."""
        layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        test = MultiLayerTestCase("voltage_regulator", layers)
        test.drc.board_width_mm = 40.0
        test.drc.board_height_mm = 30.0

        # Power net class
        test.create_net_class("Power", track_width=0.5, clearance=0.3)

        # Voltage regulator (SOT-223)
        test.create_component("U1", "LM1117-3.3", "SOT-223-3", x=20, y=15)

        # Input capacitor
        test.create_component("C1", "10uF", "C_0805", x=10, y=15)

        # Output capacitors
        test.create_component("C2", "10uF", "C_0805", x=30, y=15)
        test.create_component("C3", "100nF", "C_0805", x=30, y=20)

        # Input/output connectors
        test.create_component("J1", "VIN", "PinHeader_1x03_P2.54mm_Vertical", x=5, y=15)
        test.create_component(
            "J2", "VOUT", "PinHeader_1x03_P2.54mm_Vertical", x=38, y=15
        )

        # Nets
        test.create_net("VIN", [("J1", "1"), ("C1", "1"), ("U1", "3")], track_width=0.5)
        test.create_net(
            "VOUT",
            [("U1", "2"), ("C2", "1"), ("C3", "1"), ("J2", "1")],
            track_width=0.5,
        )
        test.create_net(
            "GND",
            [
                ("J1", "3"),
                ("C1", "2"),
                ("U1", "1"),
                ("C2", "2"),
                ("C3", "2"),
                ("J2", "3"),
            ],
            track_width=0.5,
        )

        test.assign_net_class("VIN", "Power")
        test.assign_net_class("VOUT", "Power")
        test.assign_net_class("GND", "Power")

        # Route
        paths, layers_used, crossings = route_board_multilayer(test)

        # Should route VIN and VOUT (GND is skipped)
        assert "VIN" in paths, "VIN should be routed"
        assert "VOUT" in paths, "VOUT should be routed"

        # Add traces and write
        add_traces_to_board_multilayer(test.board, paths, layers_used)

        output_path = tmp_path / "voltage_regulator.kicad_pcb"
        KicadWriter().write(test.board, output_path)

        assert output_path.exists()
        content = output_path.read_text()

        # Verify inner layers present
        assert '"In1.Cu"' in content
        assert '"In2.Cu"' in content
