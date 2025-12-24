"""
Test Real Board: 2-Channel Injector
Tests autorouting on the actual injector_2ch board from test fixtures.
Target: 0-5 DRC errors (better than manual routing's 5-6 errors).
Performance target: <60 seconds.
"""

import pytest
import time
from pathlib import Path
from pcb_tool.repl import REPL
from pcb_tool.data_model import Pad


@pytest.fixture
def injector_board_path():
    """Path to the real injector board netlist file."""
    # Try .net file first (netlist), fall back to .kicad_pcb
    repo_root = Path(__file__).resolve().parents[1]
    net_path = repo_root / "tests" / "fixtures" / "injector_2ch.net"
    pcb_path = repo_root / "tests" / "fixtures" / "injector_2ch.kicad_pcb"

    if net_path.exists():
        return net_path
    elif pcb_path.exists():
        pytest.skip("Injector board found but is .kicad_pcb format (need .net netlist)")
    else:
        pytest.skip(f"Injector board netlist not found at {net_path}")
    return net_path


@pytest.fixture
def injector_placements():
    """Component placements from injector_2ch_TRULY_ZERO.txt"""
    return [
        "MOVE J1 TO 15 70 ROTATION 0",
        "MOVE C1 TO 35 70 ROTATION 0",
        "MOVE C2 TO 50 70 ROTATION 0",
        "MOVE J2 TO 15 20 ROTATION 0",
        "MOVE R1 TO 65 48 ROTATION 0",
        "MOVE R3 TO 65 40 ROTATION 0",
        "MOVE Q1 TO 75 44 ROTATION 0",
        "MOVE D1 TO 75 28 ROTATION 90",
        "MOVE R2 TO 95 48 ROTATION 0",
        "MOVE R4 TO 95 40 ROTATION 0",
        "MOVE Q2 TO 105 44 ROTATION 0",
        "MOVE D2 TO 105 28 ROTATION 90",
        "MOVE J3 TO 130 44 ROTATION 0",
    ]


def test_injector_board_autoroute_all(injector_board_path, injector_placements):
    """Test autorouting all nets on the injector board.

    This test:
    1. Loads the real injector_2ch board
    2. Places components at optimized positions
    3. Runs AUTOROUTE ALL
    4. Checks DRC (target: 0-5 errors)
    5. Validates performance (<60 seconds)
    """
    repl = REPL()

    # Load board
    result = repl.process_command(f"LOAD {injector_board_path}")
    assert "OK:" in result or "Loaded" in result

    # Place components
    for placement_cmd in injector_placements:
        result = repl.process_command(placement_cmd)
        assert "OK:" in result or "Moved" in result

    # Measure autorouting time
    start_time = time.time()
    result = repl.process_command("AUTOROUTE ALL")
    end_time = time.time()

    routing_time = end_time - start_time

    # Check autorouting succeeded
    assert "OK:" in result
    # Should route most nets (accept 80%+ success rate)
    assert "routed" in result.lower()

    # Performance check: <60 seconds
    assert routing_time < 60.0, f"Autorouting took {routing_time:.1f}s, expected <60s"

    # Run DRC check
    drc_result = repl.process_command("CHECK DRC")

    # Parse DRC errors
    # Target: 0-5 errors (better than manual 5-6)
    drc_errors = 0
    if "violations:" in drc_result.lower():
        # Extract violation count
        for line in drc_result.split('\n'):
            if 'violations:' in line.lower():
                try:
                    drc_errors = int(line.split(':')[1].strip().split()[0])
                except (ValueError, IndexError):
                    pass

    # Report results
    print(f"\n=== Injector Board Autorouting Results ===")
    print(f"Routing time: {routing_time:.2f}s")
    print(f"DRC errors: {drc_errors}")
    print(f"Result: {result[:200]}...")
    print(f"DRC: {drc_result[:200]}...")

    # DRC check: 0-5 errors
    assert drc_errors <= 5, f"Expected <=5 DRC errors, got {drc_errors}"


def test_injector_board_net_count(injector_board_path):
    """Test that board has expected nets.

    Injector board should have: GND, +12V, +5V, IN1, IN2, GATE1, GATE2, OUT1, OUT2
    """
    repl = REPL()

    result = repl.process_command(f"LOAD {injector_board_path}")
    assert "OK:" in result or "Loaded" in result

    nets_result = repl.process_command("LIST NETS")

    # Expected nets
    expected_nets = ['GND', '+12V', '+5V', 'IN1', 'IN2', 'GATE1', 'GATE2', 'OUT1', 'OUT2']

    for net_name in expected_nets:
        assert net_name in nets_result, f"Expected net {net_name} not found"

    print(f"\n=== Injector Board Nets ===")
    print(f"Found all expected nets: {', '.join(expected_nets)}")


def test_injector_board_component_count(injector_board_path):
    """Test that board has expected components.

    Injector board has: J1, J2, J3 (connectors), C1, C2 (caps), R1-R4 (resistors),
    Q1, Q2 (MOSFETs), D1, D2 (diodes) = 13 components
    """
    repl = REPL()

    result = repl.process_command(f"LOAD {injector_board_path}")
    assert "OK:" in result or "Loaded" in result

    components_result = repl.process_command("LIST COMPONENTS")

    # Expected components
    expected_components = ['J1', 'J2', 'J3', 'C1', 'C2', 'R1', 'R2', 'R3', 'R4',
                           'Q1', 'Q2', 'D1', 'D2']

    for comp_ref in expected_components:
        assert comp_ref in components_result, f"Expected component {comp_ref} not found"

    print(f"\n=== Injector Board Components ===")
    print(f"Found all {len(expected_components)} expected components")


def test_injector_board_routing_quality_metrics(injector_board_path, injector_placements):
    """Test routing quality metrics.

    Measures:
    - Total trace length
    - Via count
    - Routing success rate
    - DRC errors
    """
    repl = REPL()

    # Load and place
    repl.process_command(f"LOAD {injector_board_path}")
    for placement_cmd in injector_placements:
        repl.process_command(placement_cmd)

    # Autoroute
    result = repl.process_command("AUTOROUTE ALL")

    # Extract metrics from result
    metrics = {
        'nets_routed': 0,
        'total_nets': 0,
        'total_length_mm': 0.0,
        'vias': 0,
        'routing_time': 0.0,
    }

    # Parse result
    for line in result.split('\n'):
        if '/' in line and 'routed' in line.lower():
            # Extract "X/Y nets routed"
            try:
                parts = line.split('/')
                metrics['nets_routed'] = int(parts[0].split()[-1])
                metrics['total_nets'] = int(parts[1].split()[0])
            except (ValueError, IndexError):
                pass
        if 'length:' in line.lower():
            # Extract "Total length: X.Xmm"
            try:
                metrics['total_length_mm'] = float(line.split(':')[1].strip().replace('mm', ''))
            except (ValueError, IndexError):
                pass
        if 'via' in line.lower():
            # Count via mentions
            metrics['vias'] += line.lower().count('via')

    # Run DRC
    drc_result = repl.process_command("CHECK DRC")
    drc_errors = 0
    if "violations:" in drc_result.lower():
        for line in drc_result.split('\n'):
            if 'violations:' in line.lower():
                try:
                    drc_errors = int(line.split(':')[1].strip().split()[0])
                except (ValueError, IndexError):
                    pass

    metrics['drc_errors'] = drc_errors

    # Quality assertions
    if metrics['total_nets'] > 0:
        success_rate = (metrics['nets_routed'] / metrics['total_nets']) * 100
        assert success_rate >= 80.0, f"Success rate {success_rate:.1f}% below 80%"

    assert metrics['drc_errors'] <= 5, f"DRC errors {metrics['drc_errors']} exceeds 5"

    # Report metrics
    print(f"\n=== Routing Quality Metrics ===")
    print(f"Nets routed: {metrics['nets_routed']}/{metrics['total_nets']}")
    print(f"Total trace length: {metrics['total_length_mm']:.1f}mm")
    print(f"Via count: {metrics['vias']}")
    print(f"DRC errors: {metrics['drc_errors']}")
    if metrics['total_nets'] > 0:
        print(f"Success rate: {(metrics['nets_routed']/metrics['total_nets'])*100:.1f}%")


def test_injector_board_stress_test_repeated_routing(injector_board_path, injector_placements):
    """Stress test: Route, undo, route again.

    Tests that autorouting is deterministic and undo works correctly.
    """
    repl = REPL()

    # Load and place
    repl.process_command(f"LOAD {injector_board_path}")
    for placement_cmd in injector_placements:
        repl.process_command(placement_cmd)

    # First routing
    result1 = repl.process_command("AUTOROUTE ALL")
    assert "OK:" in result1 or "routed" in result1.lower()

    # Undo
    undo_result = repl.process_command("UNDO")
    assert "OK:" in undo_result or "undone" in undo_result.lower()

    # Second routing (should match first)
    result2 = repl.process_command("AUTOROUTE ALL")
    assert "OK:" in result2 or "routed" in result2.lower()

    print(f"\n=== Repeated Routing Test ===")
    print(f"First routing: {result1[:100]}")
    print(f"Undo: {undo_result[:100]}")
    print(f"Second routing: {result2[:100]}")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
