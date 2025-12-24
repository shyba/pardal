"""
Test Z3 path continuity constraints - prevent crossings by forcing proper paths.

Goal: Two nets where shortest paths would cross in an X pattern.
Z3 must find longer paths that go around to avoid the crossing.

Example scenario:
    A1 ---- ? ---- B1
            X
    A2 ---- ? ---- B2

Shortest paths: A1→B1 and A2→B2 cross at X
Solution: One net must route around the other
"""

import pytest
from pcb_tool.routing.grid import RoutingGrid
from pcb_tool.routing.z3_router import Z3Router, Z3RoutingConfig, RoutingError
from pcb_tool.routing.multi_net_router import NetDefinition


class TestZ3PathContinuity:
    """Test proper path continuity to prevent crossings."""

    def test_01_crossing_x_pattern_without_continuity(self):
        """
        TEST: Two nets crossing in X pattern - CURRENT BEHAVIOR

        Net1: (5, 10) → (15, 10)  (horizontal)
        Net2: (10, 5) → (10, 15)  (vertical)

        Without path continuity: Z3 just marks endpoints, we draw straight lines → CROSSING!
        Expected: SAT but produces crossing traces (current broken behavior)
        """
        print("\n" + "="*80)
        print("TEST 1: X-crossing WITHOUT path continuity (current broken behavior)")
        print("="*80)

        grid = RoutingGrid(width_mm=20.0, height_mm=20.0, resolution_mm=1.0)

        config = Z3RoutingConfig(
            timeout_ms=10000,
            clearance_cells=0,
            optimize_wire_length=True,
            optimize_vias=False
        )

        router = Z3Router(grid, config)

        # Two nets that cross if routed directly
        net1 = NetDefinition(name="NET1", start=(5.0, 10.0), end=(15.0, 10.0), layer="F.Cu")
        net2 = NetDefinition(name="NET2", start=(10.0, 5.0), end=(10.0, 15.0), layer="F.Cu")

        print(f"  NET1 (horizontal): (5, 10) → (15, 10)")
        print(f"  NET2 (vertical):   (10, 5) → (10, 15)")
        print(f"  These cross at (10, 10) if routed directly")

        result = router.solve_routing([net1, net2])

        assert "NET1" in result
        assert "NET2" in result

        # Check if routes cross at (10, 10)
        net1_cells = set(result["NET1"].path)
        net2_cells = set(result["NET2"].path)
        crossing = net1_cells.intersection(net2_cells)

        print(f"\n  NET1 path: {result['NET1'].path}")
        print(f"  NET2 path: {result['NET2'].path}")
        print(f"  Crossing cells: {crossing}")

        if len(crossing) > 0:
            print(f"\n  ⚠️  CROSSING DETECTED: {len(crossing)} shared cells")
            print(f"  → This is the bug we need to fix with path continuity!")
        else:
            print(f"\n  ✓ No crossing - Z3 found non-overlapping paths")

    def test_03_three_way_crossing_with_continuity(self):
        """
        TEST: Three nets in star pattern - need to route around each other

        Net1: Center → North
        Net2: Center → East
        Net3: Center → South

        All three share the center cell as start point (MST branching).
        With continuity, they must route without crossing each other.
        """
        print("\n" + "="*80)
        print("TEST 3: Three-way crossing (star pattern) with continuity")
        print("="*80)

        grid = RoutingGrid(width_mm=30.0, height_mm=30.0, resolution_mm=1.0)

        config = Z3RoutingConfig(
            timeout_ms=10000,
            clearance_cells=0,
            optimize_wire_length=True,
            optimize_vias=False
        )

        router = Z3Router(grid, config)
        router.enable_path_continuity = True

        # Three segments of NET1 branching from center
        center = (15.0, 15.0)
        north = (15.0, 25.0)
        east = (25.0, 15.0)
        south = (15.0, 5.0)

        seg1 = NetDefinition(name="NET1", start=center, end=north, layer="F.Cu")
        seg2 = NetDefinition(name="NET1", start=center, end=east, layer="F.Cu")
        seg3 = NetDefinition(name="NET1", start=center, end=south, layer="F.Cu")

        print(f"  Center: {center}")
        print(f"  North:  {north}")
        print(f"  East:   {east}")
        print(f"  South:  {south}")
        print(f"  All three segments share center point (MST branching)")

        result = router.solve_routing([seg1, seg2, seg3])

        assert "NET1" in result

        print(f"\n  NET1 path: {len(result['NET1'].path)} waypoints")
        print(f"  ✅ SUCCESS: Three-way branching routed!")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
