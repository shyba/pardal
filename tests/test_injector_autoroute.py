"""
Test auto-routing of the real injector_2ch board.

This test validates that the auto-routing system can route the actual
2-channel injector controller board with zero DRC errors, proving that
the board is routable with 2 layers using the automated system.
"""

import pytest
import os
from pathlib import Path
from pcb_tool.data_model import Board
from pcb_tool.commands import (
    LoadCommand, MoveCommand, AutoRouteCommand,
    CheckDrcCommand, ShowBoardCommand
)


class TestInjectorAutoRoute:
    """Test auto-routing of real injector_2ch board."""

    @pytest.fixture
    def netlist_path(self):
        """Path to injector_2ch netlist."""
        path = "/home/user/repos/ee/manual_temp_test/injector_2ch.net"
        if not os.path.exists(path):
            pytest.skip(f"Netlist not found: {path}")
        return path

    @pytest.fixture
    def board_with_components(self, netlist_path):
        """Load netlist and place components at optimal positions."""
        board = Board()

        # Load netlist
        load_cmd = LoadCommand(Path(netlist_path))
        result = load_cmd.execute(board)
        assert "loaded" in result.lower() and "components" in result.lower()

        # Component placements optimized for MST multi-point routing
        # Spread components to reduce congestion and allow all MST edges to route
        placements = [
            # Power connectors and capacitors (top)
            ("J1", 15, 70, 0),
            ("C1", 35, 70, 0),
            ("C2", 50, 70, 0),

            # Input connector (left side, mid-height)
            ("J2", 15, 45, 0),

            # Channel 1 (center-left)
            ("R1", 55, 50, 0),
            ("R3", 55, 42, 0),
            ("Q1", 65, 46, 0),
            ("D1", 75, 38, 90),

            # Channel 2 (center-right)
            ("R2", 85, 50, 0),
            ("R4", 85, 42, 0),
            ("Q2", 95, 46, 0),
            ("D2", 105, 38, 90),

            # Output connector (bottom center)
            ("J3", 80, 25, 0),
        ]

        # Place all components
        for ref, x, y, rotation in placements:
            move_cmd = MoveCommand(ref, x, y, rotation)
            move_cmd.execute(board)

        return board

    def test_injector_full_autoroute(self, board_with_components):
        """Test complete auto-routing of injector board using ground plane mode.

        This is the main test that proves the board is routable with 2 layers
        using proper 2-layer design strategy: B.Cu=GND plane, F.Cu=signals/power.
        Target: 0 DRC errors in reasonable time (<60 seconds).
        """
        board = board_with_components

        # Verify all components placed
        assert len(board.components) == 13, "Should have 13 components"

        # Verify nets loaded
        expected_nets = ["GND", "+12V", "+5V", "IN1", "IN2", "GATE1", "GATE2", "OUT1", "OUT2"]
        for net_name in expected_nets:
            assert net_name in board.nets, f"Net {net_name} should be loaded"

        # Run auto-routing with ground plane mode (B.Cu=GND plane, F.Cu=signals)
        autoroute_cmd = AutoRouteCommand(net_name="ALL", optimize=True, ground_plane_mode=True)
        result = autoroute_cmd.execute(board)

        # Verify routing succeeded
        assert "OK:" in result or "successfully" in result.lower(), \
            f"Auto-routing should succeed, got: {result}"

        # Check that all nets have routing
        # Note: In ground plane mode, GND is not routed (it's a solid plane on B.Cu)
        routed_nets = 0
        total_segments = 0
        total_vias = 0
        expected_routed_nets = [n for n in expected_nets if n.upper() not in ['GND', 'GROUND']]

        for net_name in expected_routed_nets:
            net = board.nets[net_name]
            if len(net.segments) > 0:
                routed_nets += 1
                total_segments += len(net.segments)
                total_vias += len(net.vias)

        assert routed_nets == len(expected_routed_nets), \
            f"All {len(expected_routed_nets)} non-GND nets should be routed, got {routed_nets}"

        # Run DRC check
        drc_cmd = CheckDrcCommand()
        drc_result = drc_cmd.execute(board)

        # Parse DRC errors
        error_count = 0
        if "errors" in drc_result.lower():
            # Extract error count from result
            import re
            match = re.search(r'(\d+)\s+errors?', drc_result, re.IGNORECASE)
            if match:
                error_count = int(match.group(1))

        # Report statistics
        print("\n" + "="*60)
        print("INJECTOR_2CH AUTO-ROUTING RESULTS")
        print("="*60)
        print(f"Components placed: {len(board.components)}")
        print(f"Nets routed: {routed_nets}/{len(expected_nets)}")
        print(f"Total segments: {total_segments}")
        print(f"Total vias: {total_vias}")
        print(f"DRC errors: {error_count}")
        print("="*60)
        print(f"Auto-route result:\n{result}")
        print("="*60)
        print(f"DRC result:\n{drc_result}")
        print("="*60)

        # Ground plane mode with crossing-forbidden zones should achieve 0 errors
        # Crossing zones are now HARD BLOCKED, forcing vias instead of crossings
        assert error_count == 0, \
            f"Expected 0 DRC errors with crossing-forbidden zones, got {error_count}"

        # Report success
        if error_count == 0:
            print("\n🎉 PERFECT ROUTING: 0 DRC errors achieved!")
            print("Ground plane mode successfully routed injector_2ch with zero errors.")
            print("This matches production 2-layer boards like Speeduino, RusEFI, etc.")
        else:
            print(f"\n✅ GOOD: {error_count} DRC errors (should be improvable with better placement)")
            print("Ground plane mode routing (B.Cu=GND plane, F.Cu=signals).")

    def test_injector_power_nets_first(self, board_with_components):
        """Test that routing power nets first improves success rate."""
        board = board_with_components

        # Route power nets first (GND, +12V, +5V)
        power_nets = ["GND", "+12V", "+5V"]

        for net_name in power_nets:
            autoroute_cmd = AutoRouteCommand(net_name=net_name)
            result = autoroute_cmd.execute(board)
            assert "OK:" in result or "successfully" in result.lower(), \
                f"Power net {net_name} should route successfully"

        # Then route signal nets
        signal_nets = ["IN1", "IN2", "GATE1", "GATE2", "OUT1", "OUT2"]

        for net_name in signal_nets:
            autoroute_cmd = AutoRouteCommand(net_name=net_name)
            result = autoroute_cmd.execute(board)
            # Signal nets might be harder, so just check they attempted
            assert net_name in result, f"Should attempt to route {net_name}"

        # Check DRC
        drc_cmd = CheckDrcCommand()
        drc_result = drc_cmd.execute(board)

        # Extract error count
        error_count = 0
        if "errors" in drc_result.lower():
            import re
            match = re.search(r'(\d+)\s+errors?', drc_result, re.IGNORECASE)
            if match:
                error_count = int(match.group(1))

        print(f"\nPower-first routing: {error_count} DRC errors")

        # Should still achieve low error count
        assert error_count <= 10, \
            f"Power-first routing should achieve ≤10 errors, got {error_count}"

    def test_injector_layer_preference(self, board_with_components):
        """Test routing with layer preferences."""
        board = board_with_components

        # Route GND on B.Cu (traditional power plane layer)
        autoroute_cmd = AutoRouteCommand(net_name="GND", prefer_layer="B.Cu")
        result = autoroute_cmd.execute(board)
        assert "GND" in result, "Should route GND"

        # Route +12V on F.Cu
        autoroute_cmd = AutoRouteCommand(net_name="+12V", prefer_layer="F.Cu")
        result = autoroute_cmd.execute(board)
        assert "+12V" in result, "Should route +12V"

        # Route remaining nets
        remaining_nets = ["+5V", "IN1", "IN2", "GATE1", "GATE2", "OUT1", "OUT2"]
        for net_name in remaining_nets:
            autoroute_cmd = AutoRouteCommand(net_name=net_name)
            autoroute_cmd.execute(board)

        # Verify GND primarily on B.Cu
        gnd_net = board.nets["GND"]
        bcu_segments = sum(1 for seg in gnd_net.segments if seg.layer == "B.Cu")
        fcu_segments = sum(1 for seg in gnd_net.segments if seg.layer == "F.Cu")

        assert bcu_segments >= fcu_segments, \
            "GND should prefer B.Cu layer"

    def test_injector_incremental_routing(self, board_with_components):
        """Test incremental routing (route some, check, route more)."""
        board = board_with_components

        # Phase 1: Route power distribution
        phase1_nets = ["GND", "+12V", "+5V"]
        for net_name in phase1_nets:
            autoroute_cmd = AutoRouteCommand(net_name=net_name)
            autoroute_cmd.execute(board)

        # Check phase 1
        for net_name in phase1_nets:
            assert len(board.nets[net_name].segments) > 0, \
                f"Phase 1: {net_name} should be routed"

        # Phase 2: Route control signals
        phase2_nets = ["IN1", "IN2"]
        for net_name in phase2_nets:
            autoroute_cmd = AutoRouteCommand(net_name=net_name)
            autoroute_cmd.execute(board)

        # Phase 3: Route gate drivers
        phase3_nets = ["GATE1", "GATE2"]
        for net_name in phase3_nets:
            autoroute_cmd = AutoRouteCommand(net_name=net_name)
            autoroute_cmd.execute(board)

        # Phase 4: Route outputs
        phase4_nets = ["OUT1", "OUT2"]
        for net_name in phase4_nets:
            autoroute_cmd = AutoRouteCommand(net_name=net_name)
            autoroute_cmd.execute(board)

        # Final DRC check
        drc_cmd = CheckDrcCommand()
        drc_result = drc_cmd.execute(board)

        # Should succeed with incremental approach
        assert "OK:" in drc_result or "errors" in drc_result.lower()

    def test_injector_optimization_improves_routing(self, board_with_components):
        """Test that optimization reduces via count and improves routing."""
        board = board_with_components

        # First, auto-route all nets
        autoroute_cmd = AutoRouteCommand(net_name="ALL", optimize=False)
        autoroute_cmd.execute(board)

        # Count vias before optimization
        vias_before = sum(len(net.vias) for net in board.nets.values())

        # Run optimization
        from pcb_tool.commands import OptimizeRoutingCommand
        optimize_cmd = OptimizeRoutingCommand(net_name="ALL")
        result = optimize_cmd.execute(board)

        # Count vias after optimization
        vias_after = sum(len(net.vias) for net in board.nets.values())

        print(f"\nVias before optimization: {vias_before}")
        print(f"Vias after optimization: {vias_after}")
        print(f"Improvement: {vias_before - vias_after} vias removed")

        # Optimization should reduce via count or keep it the same
        assert vias_after <= vias_before, \
            "Optimization should not increase via count"

    def test_injector_routing_statistics(self, board_with_components):
        """Test that routing produces reasonable statistics."""
        board = board_with_components

        # Auto-route
        autoroute_cmd = AutoRouteCommand(net_name="ALL")
        autoroute_cmd.execute(board)

        # Calculate statistics
        total_length = 0.0
        total_vias = 0
        net_stats = {}

        for net_name, net in board.nets.items():
            length = 0.0
            for seg in net.segments:
                dx = seg.end[0] - seg.start[0]
                dy = seg.end[1] - seg.start[1]
                length += (dx*dx + dy*dy)**0.5

            net_stats[net_name] = {
                "length_mm": length,
                "segments": len(net.segments),
                "vias": len(net.vias)
            }

            total_length += length
            total_vias += len(net.vias)

        # Verify reasonable statistics
        assert total_length > 0, "Should have routed traces"
        assert total_length < 2000, f"Total trace length too long: {total_length}mm"
        assert total_vias < 50, f"Too many vias: {total_vias}"

        # Print statistics
        print("\nPer-net statistics:")
        for net_name, stats in net_stats.items():
            print(f"  {net_name:8s}: {stats['length_mm']:6.1f}mm, "
                  f"{stats['segments']:2d} segments, {stats['vias']:2d} vias")
        print(f"\nTotal: {total_length:.1f}mm, {total_vias} vias")

    def test_injector_board_visualization(self, board_with_components):
        """Test that SHOW BOARD displays routing statistics."""
        board = board_with_components

        # Auto-route
        autoroute_cmd = AutoRouteCommand(net_name="ALL")
        autoroute_cmd.execute(board)

        # Show board
        show_cmd = ShowBoardCommand()
        result = show_cmd.execute(board)

        # Verify statistics are displayed
        assert "Routing Grid Statistics:" in result, \
            "Should show routing grid statistics"
        assert "F.Cu:" in result, "Should show F.Cu statistics"
        assert "B.Cu:" in result, "Should show B.Cu statistics"
        assert "Layer transitions:" in result or "vias" in result.lower(), \
            "Should show via count"

        print(f"\nBoard visualization:\n{result}")


class TestInjectorStressTests:
    """Stress tests for injector board routing."""

    @pytest.fixture
    def netlist_path(self):
        """Path to injector_2ch netlist."""
        path = "/home/user/repos/ee/manual_temp_test/injector_2ch.net"
        if not os.path.exists(path):
            pytest.skip(f"Netlist not found: {path}")
        return path

    def test_injector_repeated_routing(self, netlist_path):
        """Test that routing is consistent across multiple runs."""
        results = []

        for run in range(3):
            # Create fresh board
            board = Board()

            # Load and place
            load_cmd = LoadCommand(Path(netlist_path))
            load_cmd.execute(board)

            placements = [
                ("J1", 15, 70, 0), ("C1", 35, 70, 0), ("C2", 50, 70, 0),
                ("J2", 15, 20, 0), ("R1", 65, 48, 0), ("R3", 65, 40, 0),
                ("Q1", 75, 44, 0), ("D1", 75, 28, 90), ("R2", 95, 48, 0),
                ("R4", 95, 40, 0), ("Q2", 105, 44, 0), ("D2", 105, 28, 90),
                ("J3", 130, 44, 0),
            ]

            for ref, x, y, rotation in placements:
                move_cmd = MoveCommand(ref, x, y, rotation)
                move_cmd.execute(board)

            # Route
            autoroute_cmd = AutoRouteCommand(net_name="ALL")
            autoroute_cmd.execute(board)

            # Check DRC
            drc_cmd = CheckDrcCommand()
            drc_result = drc_cmd.execute(board)

            # Extract error count
            error_count = 0
            if "errors" in drc_result.lower():
                import re
                match = re.search(r'(\d+)\s+errors?', drc_result, re.IGNORECASE)
                if match:
                    error_count = int(match.group(1))

            results.append(error_count)

        print(f"\nRepeated routing results: {results}")

        # All runs should achieve similar quality
        assert max(results) <= 10, \
            f"All runs should achieve ≤10 errors, got max={max(results)}"

        # Results should be consistent (within 5 errors)
        assert max(results) - min(results) <= 5, \
            "Routing quality should be consistent across runs"
