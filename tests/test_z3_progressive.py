"""
Progressive Z3 router tests - start simple, add complexity to isolate UNSAT issues.

Test progression:
1. Simplest: 1 net, 2 pads (single wire)
2. Simple: 2 nets, 2 pads each (parallel wires)
3. Medium: 1 net, 3 pads (MST branching)
4. Complex: 2 nets, one has 3 pads (MST + regular)
"""

import pytest
from pcb_tool.routing.grid import RoutingGrid
from pcb_tool.routing.z3_router import Z3Router, Z3RoutingConfig, RoutingError
from pcb_tool.routing.multi_net_router import NetDefinition


class TestZ3Progressive:
    """Progressive complexity tests to isolate UNSAT issues."""

    def test_01_simplest_single_net_two_pads(self):
        """
        TEST 1: Absolute simplest case
        - 1 net
        - 2 pads
        - No MST branching
        - Expected: SAT (should work)
        """
        print("\n" + "="*80)
        print("TEST 1: Simplest - 1 net, 2 pads")
        print("="*80)

        grid = RoutingGrid(width_mm=20.0, height_mm=20.0, resolution_mm=1.0)

        config = Z3RoutingConfig(
            timeout_ms=10000,
            clearance_cells=0,
            optimize_wire_length=True,
            optimize_vias=False
        )

        router = Z3Router(grid, config)

        # Single net: A→B (horizontal, 10mm apart)
        net1 = NetDefinition(
            name="NET1",
            start=(5.0, 10.0),
            end=(15.0, 10.0),
            layer="F.Cu"
        )

        print(f"  NET1: ({net1.start}) → ({net1.end})")

        result = router.solve_routing([net1])

        assert "NET1" in result
        print(f"  ✓ SAT: NET1 routed with {len(result['NET1'].path)} waypoints")

    def test_02_simple_two_nets_parallel(self):
        """
        TEST 2: Two independent nets
        - 2 nets
        - 2 pads each
        - No conflicts (parallel, spaced apart)
        - Expected: SAT
        """
        print("\n" + "="*80)
        print("TEST 2: Simple - 2 nets, parallel, no conflicts")
        print("="*80)

        grid = RoutingGrid(width_mm=20.0, height_mm=20.0, resolution_mm=1.0)

        config = Z3RoutingConfig(
            timeout_ms=10000,
            clearance_cells=0,
            optimize_wire_length=True,
            optimize_vias=False
        )

        router = Z3Router(grid, config)

        # Two parallel nets, spaced 5mm apart
        net1 = NetDefinition(name="NET1", start=(5.0, 10.0), end=(15.0, 10.0), layer="F.Cu")
        net2 = NetDefinition(name="NET2", start=(5.0, 5.0), end=(15.0, 5.0), layer="F.Cu")

        print(f"  NET1: ({net1.start}) → ({net1.end})")
        print(f"  NET2: ({net2.start}) → ({net2.end})")

        result = router.solve_routing([net1, net2])

        assert "NET1" in result
        assert "NET2" in result
        print(f"  ✓ SAT: NET1 routed with {len(result['NET1'].path)} waypoints")
        print(f"  ✓ SAT: NET2 routed with {len(result['NET2'].path)} waypoints")

    def test_03_medium_single_net_three_pads_mst(self):
        """
        TEST 3: Single net with MST branching
        - 1 net
        - 3 pads
        - MST creates 2 segments sharing common pad
        - THIS IS THE CRITICAL TEST
        - Expected: SAT or UNSAT? Let's find out!
        """
        print("\n" + "="*80)
        print("TEST 3: Medium - 1 net, 3 pads, MST branching")
        print("="*80)

        grid = RoutingGrid(width_mm=30.0, height_mm=30.0, resolution_mm=1.0)

        config = Z3RoutingConfig(
            timeout_ms=10000,
            clearance_cells=0,
            optimize_wire_length=True,
            optimize_vias=False
        )

        router = Z3Router(grid, config)

        # MST for NET1 with 3 pads: A, B, C
        # Optimal MST: A→B, A→C (A is the hub)
        # This creates 2 segments:
        #   Segment 1: A→B
        #   Segment 2: A→C
        # Both segments START at A (POTENTIAL CONFLICT!)

        pad_A = (10.0, 15.0)
        pad_B = (20.0, 15.0)
        pad_C = (10.0, 25.0)

        segment1 = NetDefinition(name="NET1", start=pad_A, end=pad_B, layer="F.Cu")
        segment2 = NetDefinition(name="NET1", start=pad_A, end=pad_C, layer="F.Cu")

        print(f"  Pad A: {pad_A}")
        print(f"  Pad B: {pad_B}")
        print(f"  Pad C: {pad_C}")
        print(f"  Segment 1: A→B")
        print(f"  Segment 2: A→C")
        print(f"  ⚠️  Both segments share starting pad A at {pad_A}")

        try:
            result = router.solve_routing([segment1, segment2])

            # If SAT, both segments should be routed
            assert len(result) > 0
            print(f"  ✓ SAT: {len(result)} segments routed")

            for seg_name, seg_route in result.items():
                print(f"    {seg_name}: {len(seg_route.path)} waypoints")

        except RoutingError as e:
            print(f"  ✗ UNSAT: {e}")
            print(f"  → This confirms the MST conflict hypothesis!")
            raise

    def test_04_complex_two_nets_one_has_mst(self):
        """
        TEST 4: Mix of simple and MST nets
        - 2 nets
        - NET1: 2 pads (simple)
        - NET2: 3 pads (MST)
        - Expected: UNSAT (if TEST 3 fails)
        """
        print("\n" + "="*80)
        print("TEST 4: Complex - 2 nets, one with MST")
        print("="*80)

        grid = RoutingGrid(width_mm=30.0, height_mm=30.0, resolution_mm=1.0)

        config = Z3RoutingConfig(
            timeout_ms=10000,
            clearance_cells=0,
            optimize_wire_length=True,
            optimize_vias=False
        )

        router = Z3Router(grid, config)

        # NET1: Simple 2-pad net
        net1_seg = NetDefinition(name="NET1", start=(5.0, 5.0), end=(15.0, 5.0), layer="F.Cu")

        # NET2: MST with 3 pads
        pad_A = (10.0, 15.0)
        pad_B = (20.0, 15.0)
        pad_C = (10.0, 25.0)

        net2_seg1 = NetDefinition(name="NET2", start=pad_A, end=pad_B, layer="F.Cu")
        net2_seg2 = NetDefinition(name="NET2", start=pad_A, end=pad_C, layer="F.Cu")

        print(f"  NET1: Simple 2-pad")
        print(f"  NET2: MST 3-pad (shares pad A)")

        try:
            result = router.solve_routing([net1_seg, net2_seg1, net2_seg2])

            assert len(result) > 0
            print(f"  ✓ SAT: {len(result)} segments routed")

        except RoutingError as e:
            print(f"  ✗ UNSAT: {e}")
            raise

    def test_05_debug_same_net_different_indices(self):
        """
        TEST 5: Diagnostic - explicitly show the conflict

        Create 2 segments of the SAME net that share a cell.
        Current encoding treats them as different net_idx values.
        """
        print("\n" + "="*80)
        print("TEST 5: Diagnostic - Show NET1 conflict explicitly")
        print("="*80)

        grid = RoutingGrid(width_mm=10.0, height_mm=10.0, resolution_mm=1.0)

        config = Z3RoutingConfig(
            timeout_ms=10000,
            clearance_cells=0,
            optimize_wire_length=False,
            optimize_vias=False
        )

        router = Z3Router(grid, config)

        # Two segments of NET1 that share cell (5, 5)
        seg1 = NetDefinition(name="NET1", start=(5.0, 5.0), end=(8.0, 5.0), layer="F.Cu")
        seg2 = NetDefinition(name="NET1", start=(5.0, 5.0), end=(5.0, 8.0), layer="F.Cu")

        print(f"  Segment 1 (NET1): (5, 5) → (8, 5)  [net_idx=0]")
        print(f"  Segment 2 (NET1): (5, 5) → (5, 8)  [net_idx=1]")
        print(f"  ")
        print(f"  Z3 constraints:")
        print(f"    cell[5,5] == 0  (Segment 1 starts here)")
        print(f"    cell[5,5] == 1  (Segment 2 starts here)")
        print(f"    → CONFLICT! cell[5,5] cannot equal both 0 and 1")

        result = router.solve_routing([seg1, seg2])

        # After fix: segments of same net share the same net_idx
        # So both segments can claim cell (5,5) without conflict!
        assert "NET1" in result
        print(f"  ✓ SAT after fix! Encoding now groups segments by net name")
        print(f"  → Both segments share net_idx=0, so cell[5,5]==0 is satisfied by both")
        print(f"    NET1: {len(result['NET1'].path)} waypoints")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
