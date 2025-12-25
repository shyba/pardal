#!/usr/bin/env python3
"""
Simple 2-Layer Board Example

Demonstrates creating a basic 2-layer board with minimal code.

Usage:
    python examples/simple_2layer.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pcb_tool.board_builder import simple_board
from pcb_tool.routing_strategies import route_board
from pcb_tool.kicad_writer import KicadWriter


def main():
    # Create a simple LED circuit board
    board = (simple_board(layers=2, width=30, height=20)
        # LED and current-limiting resistor
        .component("D1", "0805", (10, 10), value="LED")
        .component("R1", "0603", (20, 10), value="330R")

        # Power header
        .component("J1", "PinHeader_1x02_P2.54mm_Vertical", (5, 10), value="PWR")

        # Connections
        .net("VCC", connections=[("J1", "1"), ("R1", "1")])
        .net("LED_A", connections=[("R1", "2"), ("D1", "1")])
        .net("GND", connections=[("D1", "2"), ("J1", "2")])

        .build()
    )

    # Route
    result = route_board(board, "simple")

    print(f"Routed {result.nets_routed}/{result.nets_total} nets")
    print(f"Length: {result.total_length_mm:.1f}mm, Vias: {result.total_vias}")

    # Save
    output_path = Path(__file__).parent / "simple_2layer.kicad_pcb"
    KicadWriter().write(board, output_path)
    print(f"Saved to: {output_path}")


if __name__ == "__main__":
    main()
