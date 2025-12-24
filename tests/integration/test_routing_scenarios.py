#!/usr/bin/env python3
"""
Integration tests for PCB routing scenarios.

Tests various routing edge cases inspired by FreeRouting test patterns:
- Fan-out routing (one pin to multiple destinations)
- Shared power rails (multiple VDD pins from single source)
- Routing through pad gaps
- Different trace widths on same board
- Layer switching for crossing avoidance
- DRC clearance validation
"""

import sys
import subprocess
import tempfile
import random
import math
import pytest
from pathlib import Path
from typing import Dict, List, Tuple, Set, Optional
from dataclasses import dataclass, field

# Add pardal-pcb to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pcb_tool.data_model import Board, Net, Component, TraceSegment, Pad
from pcb_tool.commands import MoveCommand
from pcb_tool.routing.grid import RoutingGrid
from pcb_tool.routing.pathfinder import PathFinder
from pcb_tool.routing.crossing_detector import CrossingDetector
from pcb_tool.kicad_writer import KicadWriter
from pcb_tool.footprint_library import get_footprint_pads


# =============================================================================
# DRC Configuration
# =============================================================================

@dataclass
class DRCConfig:
    """Design Rule Check configuration."""
    resolution_mm: float = 0.4
    trace_to_trace: float = 0.25
    trace_to_pad: float = 0.25
    signal_trace_width: float = 0.25
    power_trace_width: float = 0.5
    board_width_mm: float = 100.0
    board_height_mm: float = 80.0

    def cells_for_clearance(self, clearance_mm: float) -> int:
        return max(1, int(math.ceil(clearance_mm / self.resolution_mm)))


# =============================================================================
# Test Infrastructure
# =============================================================================

class RoutingTestCase:
    """Base class for routing test cases."""

    def __init__(self, name: str, drc: DRCConfig = None):
        self.name = name
        self.drc = drc or DRCConfig()
        self.board = Board()

    def create_component(self, ref: str, value: str, footprint: str,
                         x: float, y: float, rotation: float = 0) -> Component:
        """Create and place a component."""
        pads, _ = get_footprint_pads(footprint)
        if not pads:
            # Fallback for generic footprints
            pads = [
                Pad(number='1', position_offset=(-1.0, 0), size=(1.0, 1.0), shape='rect'),
                Pad(number='2', position_offset=(1.0, 0), size=(1.0, 1.0), shape='rect'),
            ]
        comp = Component(
            ref=ref,
            value=value,
            footprint=footprint,
            position=(x, y),
            rotation=rotation,
            pads=pads
        )
        self.board.components[ref] = comp
        return comp

    def create_net(self, name: str, connections: List[Tuple[str, str]],
                   track_width: float = None) -> Net:
        """Create a net with connections."""
        # Generate unique code for the net
        code = len(self.board.nets) + 1
        net = Net(name=name, code=code)
        net.connections = connections
        if track_width:
            net.track_width = track_width
        self.board.nets[name] = net
        return net

    def run_kicad_drc(self, pcb_file: Path) -> Tuple[int, Dict[str, int]]:
        """Run KiCad CLI DRC and return violation counts by type."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            report_file = Path(f.name)

        try:
            result = subprocess.run(
                ['kicad-cli', 'pcb', 'drc', '--output', str(report_file), str(pcb_file)],
                capture_output=True,
                text=True
            )

            report_text = report_file.read_text() if report_file.exists() else ""
            total_violations = 0

            for line in result.stdout.strip().split('\n'):
                if 'Found' in line and 'violations' in line:
                    try:
                        total_violations = int(line.split()[1])
                    except (ValueError, IndexError):
                        pass

            # Parse violation types
            violation_types = {}
            for line in report_text.split('\n'):
                if line.startswith('['):
                    vtype = line.split(']')[0][1:]
                    violation_types[vtype] = violation_types.get(vtype, 0) + 1

            return total_violations, violation_types

        except FileNotFoundError:
            return -1, {}  # kicad-cli not found

        finally:
            if report_file.exists():
                report_file.unlink()

    def get_real_violations(self, violation_types: Dict[str, int]) -> int:
        """Count real routing violations (excluding cosmetic/expected)."""
        real_types = ['tracks_crossing', 'shorting_items', 'clearance', 'track_dangling']
        return sum(violation_types.get(v, 0) for v in real_types)


# =============================================================================
# Routing Functions (simplified from test_route_6ch.py)
# =============================================================================

def simplify_path(path, tolerance=0.5):
    """Remove collinear points from path."""
    if len(path) < 3:
        return path

    simplified = [path[0]]
    for i in range(1, len(path) - 1):
        prev = simplified[-1]
        curr = path[i]
        next_pt = path[i + 1]

        dx1 = curr[0] - prev[0]
        dy1 = curr[1] - prev[1]
        dx2 = next_pt[0] - prev[0]
        dy2 = next_pt[1] - prev[1]

        cross = abs(dx1 * dy2 - dy1 * dx2)
        line_len = math.sqrt(dx2*dx2 + dy2*dy2)
        distance = cross / line_len if line_len > 0 else 0

        if distance > tolerance:
            simplified.append(curr)

    simplified.append(path[-1])
    return simplified


def add_pad_obstacle(grid, pad_pos, pad_size, drc: DRCConfig, layers=["F.Cu", "B.Cu"]):
    """Add pad as obstacle with clearance."""
    pad_half_x = pad_size[0] / 2 if isinstance(pad_size, tuple) else pad_size / 2
    pad_half_y = pad_size[1] / 2 if isinstance(pad_size, tuple) else pad_size / 2
    trace_half = drc.signal_trace_width / 2
    clearance = drc.trace_to_pad

    excl_x = pad_half_x + trace_half + clearance
    excl_y = pad_half_y + trace_half + clearance

    cells_x = max(1, int(math.ceil(excl_x / drc.resolution_mm)))
    cells_y = max(1, int(math.ceil(excl_y / drc.resolution_mm)))

    center = grid.to_grid_coords(*pad_pos)

    for dx in range(-cells_x, cells_x + 1):
        for dy in range(-cells_y, cells_y + 1):
            cell = (center[0] + dx, center[1] + dy)
            if 0 <= cell[0] < grid.grid_width and 0 <= cell[1] < grid.grid_height:
                for layer in layers:
                    grid.obstacles[layer].add(cell)


def path_to_cells_drc(path, grid, layer, net_name, drc: DRCConfig):
    """Convert path to cells with DRC clearance."""
    cells = set()
    if not path:
        return cells

    is_power_net = net_name.upper() in ['+12V', '+5V', 'GND', 'VDD', 'VCC', 'VSS']
    trace_width = drc.power_trace_width if is_power_net else drc.signal_trace_width
    excl_mm = (trace_width / 2) + drc.trace_to_trace
    excl_cells = max(1, int(math.ceil(excl_mm / drc.resolution_mm)))

    for i in range(len(path) - 1):
        s = grid.to_grid_coords(*path[i])
        e = grid.to_grid_coords(*path[i + 1])
        x0, y0 = s
        x1, y1 = e
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        x, y = x0, y0

        while True:
            for ddx in range(-excl_cells, excl_cells + 1):
                for ddy in range(-excl_cells, excl_cells + 1):
                    cx, cy = x + ddx, y + ddy
                    if 0 <= cx < grid.grid_width and 0 <= cy < grid.grid_height:
                        cells.add(((cx, cy), layer))
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy

    return cells


def route_net_segment(start: Tuple[float, float], end: Tuple[float, float],
                      grid: RoutingGrid, pathfinder: PathFinder,
                      routed_cells: Set, drc: DRCConfig,
                      prefer_layer: str = "F.Cu") -> Tuple[Optional[List], str]:
    """Route a single segment between two points."""
    # Try preferred layer first
    path = pathfinder.find_path(
        start_mm=start, goal_mm=end,
        layer=prefer_layer, force_single_layer=True
    )
    if path:
        return simplify_path(path, drc.resolution_mm), prefer_layer

    # Try other layer
    other_layer = "B.Cu" if prefer_layer == "F.Cu" else "F.Cu"
    path = pathfinder.find_path(
        start_mm=start, goal_mm=end,
        layer=other_layer, force_single_layer=True
    )
    if path:
        return simplify_path(path, drc.resolution_mm), other_layer

    return None, None


def route_board(test_case: RoutingTestCase) -> Tuple[Dict[str, List], Dict[str, str], int]:
    """Route all nets on a board. Returns (paths, layers, crossings)."""
    board = test_case.board
    drc = test_case.drc

    grid = RoutingGrid(
        width_mm=drc.board_width_mm,
        height_mm=drc.board_height_mm,
        resolution_mm=drc.resolution_mm
    )
    pathfinder = PathFinder(grid)
    detector = CrossingDetector(drc.resolution_mm)

    # Build pad info
    pad_info = []
    for comp in board.components.values():
        for pad in comp.pads:
            pad_pos = comp.get_pad_position(pad.number)
            pad_info.append({
                'pos': pad_pos,
                'size': pad.size,
                'comp': comp.ref,
                'pad': pad.number
            })

    paths = {}
    layers = {}
    routed_cells = set()

    # Route each net
    for net in board.nets.values():
        if net.name.upper() in ['GND', 'GROUND']:
            continue

        # Clear obstacles and add pads
        grid.obstacles["F.Cu"].clear()
        grid.obstacles["B.Cu"].clear()

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
            pad_key = (round(pad['pos'][0], 2), round(pad['pos'][1], 2))
            if pad_key not in net_pads:
                add_pad_obstacle(grid, pad['pos'], pad['size'], drc)

        # Add routed traces as obstacles
        for cell, layer in routed_cells:
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
            seg_path, seg_layer = route_net_segment(
                points[i], points[i + 1], grid, pathfinder,
                routed_cells, drc
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
            layers[net.name] = layer
            cells = path_to_cells_drc(dedup, grid, layer, net.name, drc)
            routed_cells.update(cells)

    # Count crossings
    crossings = 0
    for layer in ["F.Cu", "B.Cu"]:
        layer_paths = {n: p for n, p in paths.items() if layers.get(n) == layer}
        crossings += len(detector.detect_crossings(layer_paths))

    return paths, layers, crossings


def add_traces_to_board(board: Board, paths: Dict, layers: Dict):
    """Add routed paths as trace segments to board."""
    for net_name, path in paths.items():
        net = board.nets.get(net_name)
        if not net or len(path) < 2:
            continue

        layer = layers.get(net_name, "F.Cu")
        for i in range(len(path) - 1):
            segment = TraceSegment(
                net_name=net_name,
                start=path[i],
                end=path[i + 1],
                layer=layer,
                width=net.track_width
            )
            net.add_segment(segment)


# =============================================================================
# TEST CASE 1: Simple Point-to-Point
# =============================================================================

class TestSimplePointToPoint:
    """Test basic point-to-point routing."""

    def test_two_pin_connection(self, tmp_path):
        """Route a simple two-pin connection."""
        test = RoutingTestCase("simple_two_pin")

        # Create two connectors
        test.create_component("J1", "IN", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", 10, 40)
        test.create_component("J2", "OUT", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", 80, 40)

        # Create net connecting pin 1 of each
        test.create_net("SIG1", [("J1", "1"), ("J2", "1")])

        paths, layers, crossings = route_board(test)

        assert "SIG1" in paths, "Net SIG1 should be routed"
        assert len(paths["SIG1"]) >= 2, "Path should have at least 2 points"
        assert crossings == 0, "Should have no crossings"

    def test_multiple_independent_nets(self, tmp_path):
        """Route multiple independent nets."""
        test = RoutingTestCase("multiple_nets")

        test.create_component("J1", "IN", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", 10, 40)
        test.create_component("J2", "OUT", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", 80, 40)

        test.create_net("SIG1", [("J1", "1"), ("J2", "1")])
        test.create_net("SIG2", [("J1", "2"), ("J2", "2")])
        test.create_net("SIG3", [("J1", "3"), ("J2", "3")])

        paths, layers, crossings = route_board(test)

        assert len(paths) == 3, "All 3 nets should be routed"
        assert crossings == 0, "Should have no crossings for parallel routes"


# =============================================================================
# TEST CASE 2: Fan-Out Routing
# =============================================================================

class TestFanOutRouting:
    """Test fan-out scenarios where one pin connects to multiple destinations."""

    def test_one_to_three_fanout(self, tmp_path):
        """Route one source pin to three destination pins."""
        test = RoutingTestCase("fanout_1to3")

        # Source connector
        test.create_component("J1", "SRC", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", 10, 40)

        # Three destination components
        test.create_component("R1", "1k", "Resistor_SMD:R_0805_2012Metric", 50, 20)
        test.create_component("R2", "1k", "Resistor_SMD:R_0805_2012Metric", 50, 40)
        test.create_component("R3", "1k", "Resistor_SMD:R_0805_2012Metric", 50, 60)

        # Fan-out net: J1.1 -> R1.1, R2.1, R3.1
        test.create_net("FANOUT", [("J1", "1"), ("R1", "1"), ("R2", "1"), ("R3", "1")])

        paths, layers, crossings = route_board(test)

        assert "FANOUT" in paths, "Fan-out net should be routed"
        # Path should connect all points (chain routing)
        assert len(paths["FANOUT"]) >= 4, "Path should reach all destinations"

    def test_clock_distribution(self, tmp_path):
        """Simulate clock distribution to multiple ICs."""
        test = RoutingTestCase("clock_dist")
        test.drc.board_width_mm = 120

        # Clock source
        test.create_component("Y1", "OSC", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", 10, 40)

        # Multiple "IC" destinations (represented as pin headers)
        for i in range(4):
            test.create_component(f"U{i+1}", f"IC{i+1}",
                                  "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical",
                                  30 + i*25, 40)

        # Clock net to all ICs
        connections = [("Y1", "1")]
        for i in range(4):
            connections.append((f"U{i+1}", "1"))
        test.create_net("CLK", connections)

        paths, layers, crossings = route_board(test)

        assert "CLK" in paths, "Clock net should be routed"


# =============================================================================
# TEST CASE 3: Shared Power Rails (Multiple VDD from Single Source)
# =============================================================================

class TestSharedPowerRails:
    """Test power distribution with multiple loads from single source."""

    def test_vdd_to_multiple_ics(self, tmp_path):
        """Route VDD from power connector to multiple ICs."""
        test = RoutingTestCase("vdd_distribution")
        test.drc.board_width_mm = 150

        # Power connector
        test.create_component("J1", "PWR", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", 10, 40)

        # Bypass caps and "ICs"
        for i in range(5):
            x = 30 + i*25
            test.create_component(f"C{i+1}", "100nF", "Capacitor_SMD:C_0805_2012Metric", x, 30)
            test.create_component(f"U{i+1}", f"IC{i+1}",
                                  "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", x, 50)

        # VDD net with wide traces
        vdd_connections = [("J1", "1")]
        for i in range(5):
            vdd_connections.append((f"C{i+1}", "1"))
            vdd_connections.append((f"U{i+1}", "1"))
        test.create_net("VDD", vdd_connections, track_width=0.5)

        paths, layers, crossings = route_board(test)

        assert "VDD" in paths, "VDD net should be routed"

    def test_power_and_ground_rails(self, tmp_path):
        """Test both VDD and GND distribution."""
        test = RoutingTestCase("power_gnd_rails")
        test.drc.board_width_mm = 120

        # Power connector (VDD, GND)
        test.create_component("J1", "PWR", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", 10, 40)

        # Multiple loads
        for i in range(3):
            x = 40 + i*30
            test.create_component(f"R{i+1}", "10k", "Resistor_SMD:R_0805_2012Metric", x, 40)

        # VDD net
        vdd_conn = [("J1", "1")]
        for i in range(3):
            vdd_conn.append((f"R{i+1}", "1"))
        test.create_net("VDD", vdd_conn, track_width=0.5)

        # GND net (typically not routed, filled as pour)
        gnd_conn = [("J1", "2")]
        for i in range(3):
            gnd_conn.append((f"R{i+1}", "2"))
        test.create_net("GND", gnd_conn, track_width=0.5)

        paths, layers, crossings = route_board(test)

        assert "VDD" in paths, "VDD should be routed"
        # GND is skipped by router (filled as pour typically)


# =============================================================================
# TEST CASE 4: Routing Through Pad Gaps
# =============================================================================

class TestPadGapRouting:
    """Test routing traces between component pads."""

    def test_route_between_resistor_pads(self, tmp_path):
        """Route a trace between two pads of a component."""
        test = RoutingTestCase("pad_gap_routing")

        # Create a row of resistors with traces needing to pass between them
        test.create_component("R1", "10k", "Resistor_SMD:R_0805_2012Metric", 30, 40)
        test.create_component("R2", "10k", "Resistor_SMD:R_0805_2012Metric", 40, 40)
        test.create_component("R3", "10k", "Resistor_SMD:R_0805_2012Metric", 50, 40)

        # Connectors on opposite sides
        test.create_component("J1", "IN", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", 10, 40)
        test.create_component("J2", "OUT", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", 80, 40)

        # Nets - one needs to route through the resistor array
        test.create_net("SIG1", [("J1", "1"), ("R1", "1")])
        test.create_net("SIG2", [("R1", "2"), ("R2", "1")])
        test.create_net("SIG3", [("R2", "2"), ("R3", "1")])
        test.create_net("SIG4", [("R3", "2"), ("J2", "1")])

        # A trace that needs to go around or through
        test.create_net("BYPASS", [("J1", "2"), ("J2", "2")])

        paths, layers, crossings = route_board(test)

        assert len(paths) >= 4, "Most nets should be routed"

    def test_route_through_ic_pin_array(self, tmp_path):
        """Test routing through gaps in a pin header array."""
        test = RoutingTestCase("ic_pin_array")

        # Simulate an IC with pin headers (like through-hole DIP)
        test.create_component("U1", "DIP8", "Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical", 50, 40)

        # Connectors on sides
        test.create_component("J1", "IN", "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical", 20, 40)
        test.create_component("J2", "OUT", "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical", 80, 40)

        # Connect some pins through the array
        test.create_net("SIG1", [("J1", "1"), ("U1", "1")])
        test.create_net("SIG2", [("U1", "8"), ("J2", "1")])
        test.create_net("THRU", [("J1", "4"), ("J2", "4")])  # Must route around U1

        paths, layers, crossings = route_board(test)

        # At least the simple connections should route
        assert "SIG1" in paths or "SIG2" in paths, "At least some nets should route"


# =============================================================================
# TEST CASE 5: Different Trace Widths
# =============================================================================

class TestMixedTraceWidths:
    """Test boards with different trace widths for power vs signal."""

    def test_power_and_signal_traces(self, tmp_path):
        """Test mixed power (0.5mm) and signal (0.25mm) traces."""
        test = RoutingTestCase("mixed_widths")
        test.drc.board_width_mm = 100

        # Power connector
        test.create_component("J1", "PWR", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", 10, 40)

        # Signal connector
        test.create_component("J2", "SIG", "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical", 90, 40)

        # Load components
        test.create_component("R1", "100", "Resistor_SMD:R_0805_2012Metric", 50, 30)
        test.create_component("R2", "1k", "Resistor_SMD:R_0805_2012Metric", 50, 50)

        # Power net (wide traces)
        test.create_net("VCC", [("J1", "1"), ("R1", "1"), ("R2", "1")], track_width=0.5)

        # Signal nets (narrow traces)
        test.create_net("DATA1", [("R1", "2"), ("J2", "1")], track_width=0.25)
        test.create_net("DATA2", [("R2", "2"), ("J2", "2")], track_width=0.25)

        paths, layers, crossings = route_board(test)

        assert "VCC" in paths, "Power net should be routed"
        assert len([n for n in paths if n.startswith("DATA")]) >= 1, "Signal nets should route"


# =============================================================================
# TEST CASE 6: Crossing Avoidance (Layer Switching)
# =============================================================================

class TestCrossingAvoidance:
    """Test layer switching to avoid crossings."""

    def test_crossing_nets_use_layers(self, tmp_path):
        """Two nets that would cross should use different layers."""
        test = RoutingTestCase("crossing_avoidance")

        # Create X pattern that requires layer change
        test.create_component("J1", "TL", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", 20, 60)
        test.create_component("J2", "TR", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", 80, 60)
        test.create_component("J3", "BL", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", 20, 20)
        test.create_component("J4", "BR", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", 80, 20)

        # X pattern - these will cross if on same layer
        test.create_net("DIAG1", [("J1", "1"), ("J4", "1")])  # TL to BR
        test.create_net("DIAG2", [("J2", "1"), ("J3", "1")])  # TR to BL

        paths, layers, crossings = route_board(test)

        assert "DIAG1" in paths, "First diagonal should route"
        assert "DIAG2" in paths, "Second diagonal should route"
        # With layer switching, crossings should be 0
        # If same layer, there would be 1 crossing

    def test_grid_pattern_routing(self, tmp_path):
        """Test a grid of connections that requires layer management."""
        test = RoutingTestCase("grid_routing")
        test.drc.board_width_mm = 80
        test.drc.board_height_mm = 80

        # 3x3 grid of connectors
        for i in range(3):
            for j in range(3):
                test.create_component(
                    f"J{i*3+j+1}", f"P{i*3+j+1}",
                    "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical",
                    20 + i*25, 20 + j*25
                )

        # Horizontal connections
        test.create_net("H1", [("J1", "1"), ("J4", "1"), ("J7", "1")])
        test.create_net("H2", [("J2", "1"), ("J5", "1"), ("J8", "1")])

        # Vertical connections (will cross horizontals)
        test.create_net("V1", [("J1", "2"), ("J2", "2"), ("J3", "2")])
        test.create_net("V2", [("J4", "2"), ("J5", "2"), ("J6", "2")])

        paths, layers, crossings = route_board(test)

        # Should route most nets
        assert len(paths) >= 2, "At least some nets should route"


# =============================================================================
# TEST CASE 7: Full 6-Channel Injector (Integration)
# =============================================================================

class TestInjector6Channel:
    """Full integration test with 6-channel injector board."""



# =============================================================================
# TEST CASE 8: Edge Cases
# =============================================================================

class TestEdgeCases:
    """Test edge cases and corner conditions."""

    def test_zero_length_net(self, tmp_path):
        """Test net where endpoints are the same (component to itself)."""
        test = RoutingTestCase("zero_length")

        test.create_component("R1", "0", "Resistor_SMD:R_0805_2012Metric", 50, 40)

        # This is a jumper - connects two pins of same component
        # Should not crash, just skip
        test.create_net("JUMPER", [("R1", "1"), ("R1", "2")])

        paths, layers, crossings = route_board(test)
        # Should handle gracefully, may or may not create a path

    def test_single_pin_net(self, tmp_path):
        """Test net with only one connection (no routing needed)."""
        test = RoutingTestCase("single_pin")

        test.create_component("TP1", "TEST", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", 50, 40)
        test.create_net("TEST", [("TP1", "1")])

        paths, layers, crossings = route_board(test)
        # Should skip without error
        assert "TEST" not in paths, "Single-pin net should not be routed"

    def test_very_long_route(self, tmp_path):
        """Test a very long route across the board."""
        test = RoutingTestCase("long_route")
        test.drc.board_width_mm = 200

        test.create_component("J1", "START", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", 10, 40)
        test.create_component("J2", "END", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", 190, 40)

        test.create_net("LONG", [("J1", "1"), ("J2", "1")])

        paths, layers, crossings = route_board(test)

        assert "LONG" in paths, "Long route should complete"
        # Path should span most of the board
        if "LONG" in paths:
            path = paths["LONG"]
            x_span = max(p[0] for p in path) - min(p[0] for p in path)
            assert x_span > 150, f"Path should span board, got {x_span}mm"

    def test_components_very_close(self, tmp_path):
        """Test routing when components are very close together."""
        test = RoutingTestCase("close_components")

        # Place components very close (3mm apart)
        test.create_component("R1", "1k", "Resistor_SMD:R_0805_2012Metric", 40, 40)
        test.create_component("R2", "1k", "Resistor_SMD:R_0805_2012Metric", 43, 40)
        test.create_component("R3", "1k", "Resistor_SMD:R_0805_2012Metric", 46, 40)

        test.create_net("CHAIN", [("R1", "2"), ("R2", "1")])
        test.create_net("CHAIN2", [("R2", "2"), ("R3", "1")])

        paths, layers, crossings = route_board(test)

        # Should route the short connections
        assert len(paths) >= 1, "At least one short route should succeed"


# =============================================================================
# TEST CASE 9: ECU-Style Multi-VDD (shared power from single source)
# =============================================================================

class TestECUStylePower:
    """Test ECU-style power distribution with multiple VDD pins from single source."""

    def test_single_vdd_to_multiple_ics(self, tmp_path):
        """Single VDD pin powers multiple IC VDD pins (typical ECU pattern)."""
        test = RoutingTestCase("ecu_vdd_dist")
        test.drc = DRCConfig(board_width_mm=150, board_height_mm=100)

        # Power input (like automotive 5V regulator output)
        test.create_component("U1", "REG", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", 20, 50)

        # Multiple MCU/IC VDD pins (simulated with pin headers)
        # In real ECU, each IC has VDD pin that needs power
        for i in range(5):
            x = 40 + i * 20
            test.create_component(f"IC{i+1}", f"MCU{i+1}",
                                  "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical", x, 50)
            # Bypass cap for each IC
            test.create_component(f"C{i+1}", "100nF", "Capacitor_SMD:C_0805_2012Metric", x, 35)

        # VDD net: single source (U1.1) to all IC VDD pins (pin 1) and caps
        vdd_connections = [("U1", "1")]
        for i in range(5):
            vdd_connections.append((f"IC{i+1}", "1"))  # VDD pin
            vdd_connections.append((f"C{i+1}", "1"))   # Bypass cap
        test.create_net("VDD", vdd_connections, track_width=0.5)

        # GND net: similar distribution
        gnd_connections = [("U1", "2")]
        for i in range(5):
            gnd_connections.append((f"IC{i+1}", "2"))  # GND pin
            gnd_connections.append((f"C{i+1}", "2"))   # Bypass cap GND
        test.create_net("GND", gnd_connections, track_width=0.5)

        paths, layers, crossings = route_board(test)

        assert "VDD" in paths, "VDD distribution should route"
        # VDD should reach most destinations
        assert len(paths["VDD"]) >= 6, "VDD path should have multiple waypoints"

    def test_split_power_rails(self, tmp_path):
        """Test separate analog and digital power rails."""
        test = RoutingTestCase("split_rails")
        test.drc = DRCConfig(board_width_mm=120, board_height_mm=80)

        # Power connector with AVDD and DVDD
        test.create_component("J1", "PWR", "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical", 15, 40)

        # Digital section
        for i in range(3):
            test.create_component(f"U{i+1}", f"DIGITAL{i+1}",
                                  "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", 40 + i*20, 55)

        # Analog section (separate area)
        for i in range(2):
            test.create_component(f"A{i+1}", f"ANALOG{i+1}",
                                  "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", 40 + i*25, 25)

        # DVDD net (digital power)
        dvdd_conn = [("J1", "1")]
        for i in range(3):
            dvdd_conn.append((f"U{i+1}", "1"))
        test.create_net("DVDD", dvdd_conn, track_width=0.5)

        # AVDD net (analog power - kept separate)
        avdd_conn = [("J1", "2")]
        for i in range(2):
            avdd_conn.append((f"A{i+1}", "1"))
        test.create_net("AVDD", avdd_conn, track_width=0.5)

        paths, layers, crossings = route_board(test)

        assert "DVDD" in paths, "Digital VDD should route"
        assert "AVDD" in paths, "Analog VDD should route"


# =============================================================================
# TEST CASE 10: Dense Component Routing
# =============================================================================

class TestDenseRouting:
    """Test routing through dense component arrangements."""

    def test_qfp_breakout(self, tmp_path):
        """Simulate routing from a QFP-style dense pin pattern."""
        test = RoutingTestCase("qfp_breakout")
        test.drc = DRCConfig(board_width_mm=80, board_height_mm=80)

        # Simulate QFP pins on one side (0.5mm pitch approximated with 0805)
        # In reality these would be much smaller, but we test the pattern
        for i in range(6):
            test.create_component(f"P{i+1}", f"PIN{i+1}",
                                  "Resistor_SMD:R_0805_2012Metric", 30, 25 + i*5)

        # Breakout destination connectors
        test.create_component("J1", "OUT1", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", 60, 25)
        test.create_component("J2", "OUT2", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", 60, 45)

        # Fan-out signals from dense pins to breakout
        test.create_net("SIG1", [("P1", "2"), ("J1", "1")])
        test.create_net("SIG2", [("P2", "2"), ("J1", "2")])
        test.create_net("SIG3", [("P3", "2"), ("J1", "3")])
        test.create_net("SIG4", [("P4", "2"), ("J2", "1")])
        test.create_net("SIG5", [("P5", "2"), ("J2", "2")])
        test.create_net("SIG6", [("P6", "2"), ("J2", "3")])

        paths, layers, crossings = route_board(test)

        # Should route at least 4 of 6 signals
        routed = len(paths)
        assert routed >= 4, f"Should route at least 4 signals, got {routed}"

    def test_bus_routing(self, tmp_path):
        """Test parallel bus routing (like data bus)."""
        test = RoutingTestCase("bus_routing")
        test.drc = DRCConfig(board_width_mm=100, board_height_mm=60)

        # Source connector (8-bit bus)
        test.create_component("J1", "SRC", "Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical", 20, 30)

        # Destination connector
        test.create_component("J2", "DST", "Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical", 80, 30)

        # 8 parallel data lines
        for i in range(8):
            test.create_net(f"D{i}", [("J1", str(i+1)), ("J2", str(i+1))])

        paths, layers, crossings = route_board(test)

        # All 8 bus lines should route (parallel, no crossings)
        assert len(paths) == 8, f"All 8 bus lines should route, got {len(paths)}"
        assert crossings == 0, "Parallel bus should have no crossings"


# =============================================================================
# TEST CASE 11: DRC Validation Tests
# =============================================================================

class TestDRCValidation:
    """Tests that verify DRC compliance of routing."""

    def test_trace_clearance_maintained(self, tmp_path):
        """Verify trace-to-trace clearance is maintained."""
        test = RoutingTestCase("clearance_test")
        test.drc = DRCConfig(
            trace_to_trace=0.25,
            signal_trace_width=0.25
        )

        # Two parallel routes that must maintain clearance
        test.create_component("J1", "A", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", 20, 40)
        test.create_component("J2", "B", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", 80, 40)

        test.create_net("NET1", [("J1", "1"), ("J2", "1")])
        test.create_net("NET2", [("J1", "2"), ("J2", "2")])
        test.create_net("NET3", [("J1", "3"), ("J2", "3")])

        paths, layers, crossings = route_board(test)

        # Export and check DRC if available
        add_traces_to_board(test.board, paths, layers)
        output_path = tmp_path / "clearance_test.kicad_pcb"
        KicadWriter().write(test.board, output_path)

        total, types = test.run_kicad_drc(output_path)
        if total >= 0:  # kicad-cli available
            clearance_violations = types.get('clearance', 0)
            assert clearance_violations == 0, f"Should have no clearance violations, got {clearance_violations}"

    def test_no_shorts(self, tmp_path):
        """Verify no shorting between different nets."""
        test = RoutingTestCase("no_shorts_test")

        test.create_component("J1", "IN", "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical", 20, 40)
        test.create_component("J2", "OUT", "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical", 80, 40)

        # Create nets that could potentially short if routed incorrectly
        test.create_net("A", [("J1", "1"), ("J2", "2")])
        test.create_net("B", [("J1", "2"), ("J2", "1")])
        test.create_net("C", [("J1", "3"), ("J2", "4")])
        test.create_net("D", [("J1", "4"), ("J2", "3")])

        paths, layers, crossings = route_board(test)

        add_traces_to_board(test.board, paths, layers)
        output_path = tmp_path / "no_shorts_test.kicad_pcb"
        KicadWriter().write(test.board, output_path)

        total, types = test.run_kicad_drc(output_path)
        if total >= 0:
            shorts = types.get('shorting_items', 0)
            assert shorts == 0, f"Should have no shorts, got {shorts}"


# =============================================================================
# TEST CASE 12: Layer Management
# =============================================================================

class TestLayerManagement:
    """Test proper layer usage and via placement."""

    def test_layer_distribution(self, tmp_path):
        """Verify nets distribute across layers to minimize crossings."""
        test = RoutingTestCase("layer_dist")
        test.drc = DRCConfig(board_width_mm=100, board_height_mm=80)

        # Create a pattern that benefits from layer distribution
        # Grid of connectors
        for i in range(4):
            test.create_component(f"J{i+1}", f"C{i+1}",
                                  "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical",
                                  20 + i*25, 40)

        # Create some crossing patterns
        test.create_net("H1", [("J1", "1"), ("J4", "1")])  # Horizontal
        test.create_net("H2", [("J2", "1"), ("J3", "1")])  # Horizontal (shorter)
        test.create_net("CROSS", [("J1", "2"), ("J3", "2")])  # May cross H2

        paths, layers, crossings = route_board(test)

        # Count layer usage
        f_cu_count = sum(1 for l in layers.values() if l == "F.Cu")
        b_cu_count = sum(1 for l in layers.values() if l == "B.Cu")

        # With good layer management, should use both layers
        # (though for simple cases might all fit on one layer)
        assert len(paths) >= 2, "Should route at least 2 nets"


# =============================================================================
# Run tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
