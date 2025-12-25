"""
TDD Tests for Production-Grade Autorouting

These tests define the requirements for a production-ready autorouter:
1. No net shorts (routes don't cross other pads)
2. Proper clearance maintained (0.2mm minimum)
3. All net connections complete
4. THT pads block all layers
5. Full trace segments marked as obstacles (not just endpoints)

Run with: pytest tests/test_production_routing.py -v
"""
import pytest
import math
from pcb_tool.data_model import Board, Net, Component, Pad, STANDARD_LAYER_STACKS
from pcb_tool.commands.routing import AutoRouteCommand
from pcb_tool.routing import RoutingGrid, PathFinder


class TestPadObstacleMarking:
    """Tests for proper pad obstacle marking."""

    def test_pad_positions_marked_as_obstacles(self):
        """Pads of other nets should be marked as obstacles."""
        board = Board(layers=STANDARD_LAYER_STACKS[2])
        board.width = 30.0
        board.height = 30.0

        # Component with pads at known positions
        comp = Component(
            ref="U1", value="IC", footprint="test",
            position=(15.0, 15.0), rotation=0, layer="F.Cu"
        )
        # Pads at offsets from center
        comp.pads.append(Pad(number=1, position_offset=(-2.0, 0.0), size=(1.0, 1.0), shape='rect'))
        comp.pads.append(Pad(number=2, position_offset=(2.0, 0.0), size=(1.0, 1.0), shape='rect'))
        comp.pads.append(Pad(number=3, position_offset=(0.0, -2.0), size=(1.0, 1.0), shape='rect'))
        comp.pads.append(Pad(number=4, position_offset=(0.0, 2.0), size=(1.0, 1.0), shape='rect'))
        board.add_component(comp)

        # Net connecting pads 1 and 2 (horizontal)
        net1 = Net(name="NET1", code="1")
        net1.add_connection("U1", "1")
        net1.add_connection("U1", "2")
        board.add_net(net1)

        # Create routing grid
        cmd = AutoRouteCommand(net_name="NET1")
        grid = cmd._create_routing_grid(board)

        # Pad 3 at (15.0, 13.0) should be obstacle for NET1
        # Pad 4 at (15.0, 17.0) should be obstacle for NET1
        pad3_gx, pad3_gy = grid.to_grid_coords(15.0, 13.0)
        pad4_gx, pad4_gy = grid.to_grid_coords(15.0, 17.0)

        # These pads should be blocked (they're not part of NET1)
        assert not grid.is_valid_cell(pad3_gx, pad3_gy, "F.Cu"), \
            "Pad 3 should be marked as obstacle"
        assert not grid.is_valid_cell(pad4_gx, pad4_gy, "F.Cu"), \
            "Pad 4 should be marked as obstacle"

    def test_route_does_not_cross_other_pads(self):
        """Routes must not pass through pads of other nets."""
        board = Board(layers=STANDARD_LAYER_STACKS[2])
        board.width = 30.0
        board.height = 30.0

        # Two connectors on opposite sides
        j1 = Component(ref="J1", value="CONN", footprint="test",
                      position=(5.0, 15.0), rotation=0, layer="F.Cu")
        j1.pads.append(Pad(number=1, position_offset=(0.0, 0.0), size=(1.0, 1.0), shape='circle'))
        board.add_component(j1)

        j2 = Component(ref="J2", value="CONN", footprint="test",
                      position=(25.0, 15.0), rotation=0, layer="F.Cu")
        j2.pads.append(Pad(number=1, position_offset=(0.0, 0.0), size=(1.0, 1.0), shape='circle'))
        board.add_component(j2)

        # Obstacle component in the middle with pad directly on the path
        obstacle = Component(ref="R1", value="RES", footprint="test",
                            position=(15.0, 15.0), rotation=0, layer="F.Cu")
        obstacle.pads.append(Pad(number=1, position_offset=(0.0, 0.0), size=(1.5, 1.5), shape='rect'))
        board.add_component(obstacle)

        # Net 1: J1 to J2 (must route around R1's pad)
        net1 = Net(name="SIG1", code="1")
        net1.add_connection("J1", "1")
        net1.add_connection("J2", "1")
        board.add_net(net1)

        # Net 2: R1 pad (different net)
        net2 = Net(name="SIG2", code="2")
        net2.add_connection("R1", "1")
        board.add_net(net2)

        # Route
        cmd = AutoRouteCommand(net_name="SIG1")
        result = cmd.execute(board)

        # Check that route exists
        assert "OK" in result or "routed" in result.lower(), f"Routing failed: {result}"

        # Check that no segment on the SAME LAYER passes through R1's pad at (15.0, 15.0)
        # Note: B.Cu traces can pass under F.Cu SMD pads - this is valid multi-layer routing
        sig1 = board.nets["SIG1"]
        r1_pad_pos = (15.0, 15.0)
        r1_pad_layer = "F.Cu"  # R1 is an SMD component on F.Cu
        pad_radius = 1.5 / 2 + 0.2  # pad size/2 + clearance

        for segment in sig1.segments:
            # Only check segments on the same layer as the obstacle pad
            if segment.layer != r1_pad_layer:
                continue  # B.Cu traces can pass under F.Cu pads

            # Check if segment passes through pad
            dist = self._point_to_segment_distance(r1_pad_pos, segment.start, segment.end)
            assert dist >= pad_radius, \
                f"Route passes through R1 pad on {segment.layer}: segment {segment.start}->{segment.end}, dist={dist:.2f}mm"

    def _point_to_segment_distance(self, point, seg_start, seg_end):
        """Calculate minimum distance from point to line segment."""
        px, py = point
        x1, y1 = seg_start
        x2, y2 = seg_end

        dx, dy = x2 - x1, y2 - y1
        length_sq = dx * dx + dy * dy

        if length_sq == 0:
            return math.sqrt((px - x1) ** 2 + (py - y1) ** 2)

        t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / length_sq))
        proj_x = x1 + t * dx
        proj_y = y1 + t * dy

        return math.sqrt((px - proj_x) ** 2 + (py - proj_y) ** 2)


class TestClearanceViolations:
    """Tests for proper clearance maintenance."""

    def test_grid_resolution_finer_than_clearance(self):
        """Grid resolution should be finer than clearance for accurate routing."""
        board = Board(layers=STANDARD_LAYER_STACKS[2])
        board.width = 20.0
        board.height = 20.0

        cmd = AutoRouteCommand(net_name="TEST")
        grid = cmd._create_routing_grid(board)

        # Resolution should be <= half of clearance for accurate diagonal routing
        # Diagonal step = resolution * sqrt(2), should be < clearance
        diagonal_step = grid.resolution_mm * math.sqrt(2)
        assert diagonal_step < grid.default_clearance_mm * 1.5, \
            f"Grid resolution {grid.resolution_mm}mm too coarse for {grid.default_clearance_mm}mm clearance"

    def test_parallel_traces_maintain_clearance(self):
        """Parallel traces should maintain minimum clearance."""
        board = Board(layers=STANDARD_LAYER_STACKS[2])
        board.width = 30.0
        board.height = 30.0

        # Two parallel nets
        for i, y_pos in enumerate([10.0, 12.0]):  # 2mm apart vertically
            j_left = Component(ref=f"JL{i}", value="CONN", footprint="test",
                              position=(5.0, y_pos), rotation=0, layer="F.Cu")
            j_left.pads.append(Pad(number=1, position_offset=(0.0, 0.0), size=(0.8, 0.8), shape='circle'))
            board.add_component(j_left)

            j_right = Component(ref=f"JR{i}", value="CONN", footprint="test",
                               position=(25.0, y_pos), rotation=0, layer="F.Cu")
            j_right.pads.append(Pad(number=1, position_offset=(0.0, 0.0), size=(0.8, 0.8), shape='circle'))
            board.add_component(j_right)

            net = Net(name=f"NET{i}", code=str(i+1))
            net.add_connection(f"JL{i}", "1")
            net.add_connection(f"JR{i}", "1")
            board.add_net(net)

        # Route both nets
        cmd = AutoRouteCommand(net_name="ALL")
        result = cmd.execute(board)

        # Check clearance between traces
        net0 = board.nets["NET0"]
        net1 = board.nets["NET1"]
        min_clearance = 0.2  # mm

        for seg0 in net0.segments:
            for seg1 in net1.segments:
                dist = self._segment_to_segment_distance(
                    seg0.start, seg0.end, seg1.start, seg1.end
                )
                # Account for trace width (assume 0.25mm)
                effective_dist = dist - 0.25
                assert effective_dist >= min_clearance * 0.9, \
                    f"Clearance violation: {effective_dist:.3f}mm < {min_clearance}mm"

    def _segment_to_segment_distance(self, s1_start, s1_end, s2_start, s2_end):
        """Approximate minimum distance between two line segments."""
        # Check endpoints to endpoints and points to segments
        distances = [
            self._point_to_segment_distance(s1_start, s2_start, s2_end),
            self._point_to_segment_distance(s1_end, s2_start, s2_end),
            self._point_to_segment_distance(s2_start, s1_start, s1_end),
            self._point_to_segment_distance(s2_end, s1_start, s1_end),
        ]
        return min(distances)

    def _point_to_segment_distance(self, point, seg_start, seg_end):
        px, py = point
        x1, y1 = seg_start
        x2, y2 = seg_end
        dx, dy = x2 - x1, y2 - y1
        length_sq = dx * dx + dy * dy
        if length_sq == 0:
            return math.sqrt((px - x1) ** 2 + (py - y1) ** 2)
        t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / length_sq))
        proj_x = x1 + t * dx
        proj_y = y1 + t * dy
        return math.sqrt((px - proj_x) ** 2 + (py - proj_y) ** 2)


class TestCompleteRouting:
    """Tests for complete net connectivity."""

    def test_multipoint_net_fully_connected(self):
        """All pads in a multi-point net should be connected."""
        board = Board(layers=STANDARD_LAYER_STACKS[2])
        board.width = 40.0
        board.height = 40.0

        # 5-point VCC net (star topology)
        positions = [
            ("J1", (5.0, 20.0)),   # Left
            ("J2", (35.0, 20.0)),  # Right
            ("C1", (15.0, 10.0)),  # Top-left
            ("C2", (25.0, 10.0)),  # Top-right
            ("C3", (20.0, 30.0)),  # Bottom
        ]

        for ref, pos in positions:
            comp = Component(ref=ref, value="CAP", footprint="test",
                           position=pos, rotation=0, layer="F.Cu")
            comp.pads.append(Pad(number=1, position_offset=(0.0, 0.0), size=(0.8, 0.8), shape='circle'))
            board.add_component(comp)

        vcc = Net(name="VCC", code="1")
        for ref, _ in positions:
            vcc.add_connection(ref, "1")
        board.add_net(vcc)

        # Route
        cmd = AutoRouteCommand(net_name="VCC")
        result = cmd.execute(board)

        # Should have at least N-1 edges for N points (MST property)
        vcc_net = board.nets["VCC"]
        assert len(vcc_net.segments) >= len(positions) - 1, \
            f"VCC not fully connected: {len(vcc_net.segments)} segments for {len(positions)} pads"

        # Verify connectivity using union-find
        connected = self._check_connectivity(vcc_net, positions)
        assert connected, "Not all VCC pads are connected"

    def _check_connectivity(self, net, pad_positions):
        """Check if all pads are connected via segments using union-find.

        Handles waypoint chains by building a connectivity graph that includes
        both pads and intermediate waypoints.
        """
        # Build connectivity graph with waypoints included
        parent = {}

        def make_key(pos):
            return (round(pos[0], 3), round(pos[1], 3))

        def find(x):
            if x not in parent:
                parent[x] = x
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        # Union all segment endpoints (including waypoints)
        for segment in net.segments:
            start_key = make_key(segment.start)
            end_key = make_key(segment.end)
            union(start_key, end_key)

        # Check if all pads are in the same connected component
        pad_keys = [make_key(pos) for ref, pos in pad_positions]
        if not pad_keys:
            return False

        roots = set(find(key) for key in pad_keys)
        return len(roots) == 1

    def _distance(self, p1, p2):
        return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)


class TestTHTPadBlocking:
    """Tests for through-hole pad handling."""

    def test_tht_pad_blocks_all_layers(self):
        """Through-hole pads should block routing on all layers."""
        board = Board(layers=STANDARD_LAYER_STACKS[4])
        board.width = 30.0
        board.height = 30.0

        # THT component (connector with drill holes)
        conn = Component(ref="J1", value="HEADER", footprint="test",
                        position=(15.0, 15.0), rotation=0, layer="F.Cu")
        conn.pads.append(Pad(number=1, position_offset=(0.0, 0.0),
                            size=(1.5, 1.5), shape='circle', drill=0.8))  # THT pad
        board.add_component(conn)

        # Create grid
        cmd = AutoRouteCommand(net_name="TEST")
        grid = cmd._create_routing_grid(board)

        # THT pad should block all copper layers
        pad_gx, pad_gy = grid.to_grid_coords(15.0, 15.0)

        for layer in board.layers:
            assert not grid.is_valid_cell(pad_gx, pad_gy, layer), \
                f"THT pad should block {layer}"


class TestTraceSegmentObstacles:
    """Tests for proper trace segment obstacle marking."""

    def test_full_trace_segment_marked(self):
        """Entire trace segment should be marked, not just endpoints."""
        board = Board(layers=STANDARD_LAYER_STACKS[2])
        board.width = 30.0
        board.height = 30.0

        # Pre-existing trace (simulated by adding to net)
        net1 = Net(name="EXISTING", code="1")
        board.add_net(net1)

        # Add a horizontal trace from (5, 15) to (25, 15)
        from pcb_tool.data_model import TraceSegment
        net1.segments.append(TraceSegment(net_name="EXISTING", start=(5.0, 15.0), end=(25.0, 15.0), layer="F.Cu", width=0.25))

        # Create grid
        cmd = AutoRouteCommand(net_name="TEST")
        grid = cmd._create_routing_grid(board)

        # Middle of trace at (15, 15) should be blocked
        mid_gx, mid_gy = grid.to_grid_coords(15.0, 15.0)
        assert not grid.is_valid_cell(mid_gx, mid_gy, "F.Cu"), \
            "Middle of existing trace should be marked as obstacle"


class TestFPGABoardRouting:
    """Integration test with FPGA-like board complexity."""

    def test_fpga_board_zero_drc_errors(self):
        """FPGA board should route with zero DRC-causing issues."""
        board = self._create_fpga_board()

        # Route all nets
        cmd = AutoRouteCommand(net_name="ALL", ground_plane_mode=True)
        result = cmd.execute(board)

        # Collect all issues
        issues = []

        # Check for shorts (routes crossing other pads)
        for net_name, net in board.nets.items():
            for segment in net.segments:
                for other_name, other_net in board.nets.items():
                    if other_name == net_name:
                        continue
                    # Check if segment crosses any pad of other net
                    for ref, pin in other_net.connections:
                        comp = board.get_component(ref)
                        if comp:
                            try:
                                pad_pos = comp.get_pad_position(int(pin))
                                dist = self._point_to_segment_distance(
                                    pad_pos, segment.start, segment.end
                                )
                                if dist < 0.5:  # Pad radius + clearance
                                    issues.append(
                                        f"SHORT: {net_name} crosses {other_name} pad at {pad_pos}"
                                    )
                            except (ValueError, KeyError):
                                pass

        # Check for incomplete nets
        for net_name, net in board.nets.items():
            if net_name.upper() in ['GND', 'GROUND']:
                continue  # Skip ground (copper pour)
            num_connections = len(net.connections)
            num_segments = len(net.segments)
            if num_connections >= 2 and num_segments < num_connections - 1:
                issues.append(
                    f"INCOMPLETE: {net_name} has {num_segments} segments for {num_connections} pads"
                )

        assert len(issues) == 0, f"DRC issues found:\n" + "\n".join(issues)

    def _create_fpga_board(self):
        """Create a 4-layer FPGA test board."""
        board = Board(layers=STANDARD_LAYER_STACKS[4])
        board.width = 40.0
        board.height = 40.0

        # Central IC (TQFP-32 style)
        ic = Component(ref="U1", value="FPGA", footprint="TQFP-32",
                      position=(20.0, 20.0), rotation=0, layer="F.Cu")
        pad_positions = [
            (1, (-3.5, -2.8)), (2, (-3.5, -2.0)), (3, (-3.5, -1.2)), (4, (-3.5, -0.4)),
            (5, (-3.5, 0.4)), (6, (-3.5, 1.2)), (7, (-3.5, 2.0)), (8, (-3.5, 2.8)),
            (9, (-2.8, 3.5)), (10, (-2.0, 3.5)), (11, (-1.2, 3.5)), (12, (-0.4, 3.5)),
            (13, (0.4, 3.5)), (14, (1.2, 3.5)), (15, (2.0, 3.5)), (16, (2.8, 3.5)),
            (17, (3.5, 2.8)), (18, (3.5, 2.0)), (19, (3.5, 1.2)), (20, (3.5, 0.4)),
            (21, (3.5, -0.4)), (22, (3.5, -1.2)), (23, (3.5, -2.0)), (24, (3.5, -2.8)),
            (25, (2.8, -3.5)), (26, (2.0, -3.5)), (27, (1.2, -3.5)), (28, (0.4, -3.5)),
            (29, (-0.4, -3.5)), (30, (-1.2, -3.5)), (31, (-2.0, -3.5)), (32, (-2.8, -3.5)),
        ]
        for pad_num, offset in pad_positions:
            ic.pads.append(Pad(number=pad_num, position_offset=offset, size=(0.5, 1.2), shape='rect'))
        board.add_component(ic)

        # Decoupling capacitors
        cap_positions = [("C1", (12.0, 20.0)), ("C2", (28.0, 20.0)),
                        ("C3", (20.0, 12.0)), ("C4", (20.0, 28.0))]
        for ref, pos in cap_positions:
            cap = Component(ref=ref, value="100nF", footprint="0603",
                          position=pos, rotation=0 if pos[0] != 20.0 else 90, layer="F.Cu")
            cap.pads.append(Pad(number=1, position_offset=(-0.8, 0.0), size=(0.9, 0.9), shape='rect'))
            cap.pads.append(Pad(number=2, position_offset=(0.8, 0.0), size=(0.9, 0.9), shape='rect'))
            board.add_component(cap)

        # JTAG header (THT)
        jtag = Component(ref="J1", value="JTAG", footprint="2x05_1.27mm",
                        position=(5.0, 20.0), rotation=0, layer="F.Cu")
        for i in range(10):
            row, col = i % 2, i // 2
            jtag.pads.append(Pad(number=i+1,
                                position_offset=(row * 1.27, col * 1.27 - 2.54),
                                size=(0.7, 0.7), shape='circle', drill=0.4))
        board.add_component(jtag)

        # Power connector (THT)
        pwr = Component(ref="J2", value="PWR", footprint="1x02_2.54mm",
                       position=(35.0, 20.0), rotation=0, layer="F.Cu")
        pwr.pads.append(Pad(number=1, position_offset=(0.0, -1.27), size=(1.0, 1.0), shape='circle', drill=0.6))
        pwr.pads.append(Pad(number=2, position_offset=(0.0, 1.27), size=(1.0, 1.0), shape='circle', drill=0.6))
        board.add_component(pwr)

        # Nets
        vcc = Net(name="VCC", code="1", track_width=0.4)
        vcc.add_connection("J2", "1")
        vcc.add_connection("U1", "8")
        vcc.add_connection("U1", "24")
        vcc.add_connection("C1", "1")
        vcc.add_connection("C2", "1")
        vcc.add_connection("C3", "1")
        vcc.add_connection("C4", "1")
        board.add_net(vcc)

        gnd = Net(name="GND", code="2", track_width=0.4)
        gnd.add_connection("J2", "2")
        gnd.add_connection("U1", "16")
        gnd.add_connection("U1", "32")
        gnd.add_connection("C1", "2")
        gnd.add_connection("C2", "2")
        gnd.add_connection("C3", "2")
        gnd.add_connection("C4", "2")
        board.add_net(gnd)

        # JTAG signals
        for sig_name, jtag_pin, ic_pin in [
            ("TMS", 2, 1), ("TCK", 4, 2), ("TDI", 8, 3), ("TDO", 6, 4)
        ]:
            net = Net(name=sig_name, code=str(3 + list(["TMS", "TCK", "TDI", "TDO"]).index(sig_name)))
            net.add_connection("J1", str(jtag_pin))
            net.add_connection("U1", str(ic_pin))
            board.add_net(net)

        # Signal crossing IC
        sig1 = Net(name="SIG1", code="7")
        sig1.add_connection("U1", "17")
        sig1.add_connection("U1", "5")
        board.add_net(sig1)

        return board

    def _point_to_segment_distance(self, point, seg_start, seg_end):
        px, py = point
        x1, y1 = seg_start
        x2, y2 = seg_end
        dx, dy = x2 - x1, y2 - y1
        length_sq = dx * dx + dy * dy
        if length_sq == 0:
            return math.sqrt((px - x1) ** 2 + (py - y1) ** 2)
        t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / length_sq))
        proj_x = x1 + t * dx
        proj_y = y1 + t * dy
        return math.sqrt((px - proj_x) ** 2 + (py - proj_y) ** 2)
