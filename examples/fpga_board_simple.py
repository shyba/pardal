#!/usr/bin/env python3
"""
Simplified FPGA Board Example

Demonstrates the new BoardBuilder API that reduces FPGA board creation
from ~350 lines to ~50 lines.

Usage:
    python examples/fpga_board_simple.py
"""
import sys
import os
import shutil
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pcb_tool.board_builder import fpga_board
from pcb_tool.routing_strategies import route_board
from pcb_tool.kicad_writer import KicadWriter
from pcb_tool.api import check_internal_drc, run_kicad_drc


def create_fpga_board():
    """Create and route a 4-layer FPGA development board."""

    # Create board using fpga_board() convenience function
    # This pre-configures:
    # - 4 layers (F.Cu, In1.Cu, In2.Cu, B.Cu)
    # - Power class: 0.5mm traces, 0.25mm clearance
    # - Signal class: 0.2mm traces, 0.2mm clearance
    board = (
        fpga_board(layers=4, width=40, height=40)
        # Central IC - pads auto-generated from footprint template
        .component("U1", "TQFP-32", (20, 20), value="FPGA")
        # Decoupling capacitors around IC
        .component("C1", "0603", (12, 20), value="100nF")
        .component("C2", "0603", (28, 20), value="100nF")
        .component("C3", "0603", (20, 12), rotation=90, value="100nF")
        .component("C4", "0603", (20, 28), rotation=90, value="100nF")
        # JTAG header (2x5 1.27mm pitch)
        .component("J1", "PinHeader_2x05_P1.27mm_Vertical", (5, 20), value="JTAG")
        # Power connector
        .component("J2", "PinHeader_1x02_P2.54mm_Vertical", (35, 20), value="PWR")
        # Power nets (use Power class = 0.5mm traces)
        .net(
            "VCC",
            "Power",
            [
                ("J2", "1"),
                ("U1", "8"),
                ("U1", "24"),
                ("C1", "1"),
                ("C2", "1"),
                ("C3", "1"),
                ("C4", "1"),
            ],
        )
        .net(
            "GND",
            "Power",
            [
                ("J2", "2"),
                ("U1", "16"),
                ("U1", "32"),
                ("C1", "2"),
                ("C2", "2"),
                ("C3", "2"),
                ("C4", "2"),
            ],
        )
        # JTAG signals (use Signal class = 0.2mm traces)
        .net("TMS", "Signal", [("J1", "2"), ("U1", "1")])
        .net("TCK", "Signal", [("J1", "4"), ("U1", "2")])
        .net("TDI", "Signal", [("J1", "8"), ("U1", "3")])
        .net("TDO", "Signal", [("J1", "6"), ("U1", "4")])
        # Additional GPIO signals
        .net("GPIO1", "Signal", [("U1", "9"), ("U1", "25")])
        .net("GPIO2", "Signal", [("U1", "10"), ("U1", "26")])
        .build()
    )

    return board


def main():
    print("=" * 60)
    print("Simplified FPGA Board Example")
    print("=" * 60)

    # Create board
    print("\nCreating board...")
    board = create_fpga_board()
    print(f"  Board: {board.width}x{board.height}mm, {board.layer_count} layers")
    print(f"  Components: {len(board.components)}")
    print(f"  Nets: {len(board.nets)}")

    # Route using FPGA strategy
    print("\nRouting board...")
    result = route_board(board, "fpga")

    # Print results
    print("\n" + "=" * 60)
    print("Routing Results")
    print("=" * 60)
    print(f"  Nets routed: {result.nets_routed}/{result.nets_total}")
    print(f"  Total length: {result.total_length_mm:.1f}mm")
    print(f"  Vias: {result.total_vias}")
    print(f"  Layers used: {', '.join(sorted(result.layers_used))}")

    if result.success:
        print("\n  Status: SUCCESS - All nets routed!")
    else:
        print(
            f"\n  Status: {result.nets_total - result.nets_routed} nets failed to route"
        )

    # Save to KiCad format
    output_path = Path(__file__).parent / "fpga_board_simple.kicad_pcb"
    KicadWriter().write(board, output_path)
    print(f"\nSaved to: {output_path}")

    print("\nRunning internal DRC (fast)...")
    internal = check_internal_drc(board)
    print(f"  DRC: {internal.errors} errors, {internal.warnings} warnings")
    if internal.errors or internal.warnings:
        print(internal.report)
        return 2

    if os.environ.get("PARDAL_RUN_KICAD_DRC") and shutil.which("kicad-cli"):
        print("\nRunning KiCad DRC via kicad-cli...")
        kicad = run_kicad_drc(output_path)
        print(
            f"  KiCad DRC: {kicad.errors} errors, {kicad.warnings} warnings, "
            f"{kicad.unconnected} unconnected"
        )
        if not kicad.success:
            for v in kicad.violations[:3]:
                print(f"  - {v.type}: {v.description}")
            return 3

    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
