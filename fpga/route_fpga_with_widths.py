#!/usr/bin/env python3
"""
Route FPGA board with optimized trace widths.

Power/Ground: 0.5mm (wider for lower resistance)
Signals: 0.2mm (thinner to fit between IC pins)
"""
import sys
from pathlib import Path

# Add pardal-pcb to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pcb_tool.data_model import (
    Board,
    Net,
    Component,
    Pad,
    NetClass,
    STANDARD_LAYER_STACKS,
)
from pcb_tool.kicad_writer import KicadWriter
from pcb_tool.api import check_internal_drc
from pcb_tool.footprint_templates import generate_pads
from pcb_tool.routing_strategies import FourLayerFPGA


def create_fpga_board_with_widths() -> Board:
    """Create FPGA board with optimized trace widths."""

    # Create 4-layer board
    board = Board(layers=STANDARD_LAYER_STACKS[4])
    board.width = 40.0
    board.height = 40.0

    # Define net classes with different widths
    board.net_classes["Power"] = NetClass(
        name="Power",
        track_width=0.5,  # Wider for power
        clearance=0.25,
        via_size=0.8,
        via_drill=0.4,
    )

    board.net_classes["Signal"] = NetClass(
        name="Signal",
        track_width=0.2,  # Thinner for signals
        clearance=0.2,
        via_size=0.6,
        via_drill=0.3,
    )

    print(f"Created {board.layer_count}-layer board: {board.layers}")
    print(
        f"Net classes: Power={board.net_classes['Power'].track_width}mm, Signal={board.net_classes['Signal'].track_width}mm"
    )

    # Central IC (TQFP-32)
    ic = Component(
        ref="U1",
        value="FPGA",
        footprint="TQFP-32_7x7mm_P0.8mm",
        position=(20.0, 20.0),
        rotation=0,
        layer="F.Cu",
    )
    # Use the shared footprint templates so routing geometry matches the expected
    # KiCad library footprint more closely.
    ic.pads = generate_pads(ic.footprint)
    board.add_component(ic)

    # Decoupling capacitors (4x around IC)
    cap_positions = [
        ("C1", (12.0, 20.0)),  # Left of IC
        ("C2", (28.0, 20.0)),  # Right of IC
        ("C3", (20.0, 12.0)),  # Above IC
        ("C4", (20.0, 28.0)),  # Below IC
    ]
    for ref, pos in cap_positions:
        cap = Component(
            ref=ref,
            value="100nF",
            footprint="C_0603_1608Metric",
            position=pos,
            rotation=0 if pos[0] != 20.0 else 90,
            layer="F.Cu",
        )
        cap.pads = generate_pads(cap.footprint)
        board.add_component(cap)

    # JTAG header (2x5 1.27mm pitch)
    jtag = Component(
        ref="J1",
        value="JTAG",
        footprint="PinHeader_2x05_P1.27mm_Vertical",
        position=(5.0, 20.0),
        rotation=0,
        layer="F.Cu",
    )
    jtag.pads = generate_pads(jtag.footprint)
    board.add_component(jtag)

    # Power connector (2-pin header)
    pwr = Component(
        ref="J2",
        value="PWR",
        footprint="PinHeader_1x02_P2.54mm_Vertical",
        position=(35.0, 20.0),
        rotation=0,
        layer="F.Cu",
    )
    pwr.pads = generate_pads(pwr.footprint)
    board.add_component(pwr)

    # === Create nets with appropriate widths ===

    # Power net: VCC (WIDE - 0.5mm)
    vcc = Net(name="VCC", code="1", track_width=0.5, net_class="Power")
    vcc.add_connection("J2", "1")  # Power input
    vcc.add_connection("U1", "8")  # IC VCC pin
    vcc.add_connection("U1", "24")  # IC VCC pin 2
    vcc.add_connection("C1", "1")
    vcc.add_connection("C2", "1")
    vcc.add_connection("C3", "1")
    vcc.add_connection("C4", "1")
    board.add_net(vcc)

    # Ground net: GND (WIDE - 0.5mm)
    gnd = Net(name="GND", code="2", track_width=0.5, net_class="Power")
    gnd.add_connection("J2", "2")
    gnd.add_connection("U1", "16")  # IC GND pin
    gnd.add_connection("U1", "32")  # IC GND pin 2
    gnd.add_connection("C1", "2")
    gnd.add_connection("C2", "2")
    gnd.add_connection("C3", "2")
    gnd.add_connection("C4", "2")
    board.add_net(gnd)

    # JTAG signals (THIN - 0.2mm)
    tms = Net(name="TMS", code="3", track_width=0.2, net_class="Signal")
    tms.add_connection("J1", "2")
    tms.add_connection("U1", "1")
    board.add_net(tms)

    tck = Net(name="TCK", code="4", track_width=0.2, net_class="Signal")
    tck.add_connection("J1", "4")
    tck.add_connection("U1", "2")
    board.add_net(tck)

    tdi = Net(name="TDI", code="5", track_width=0.2, net_class="Signal")
    tdi.add_connection("J1", "8")
    tdi.add_connection("U1", "3")
    board.add_net(tdi)

    tdo = Net(name="TDO", code="6", track_width=0.2, net_class="Signal")
    tdo.add_connection("J1", "6")
    tdo.add_connection("U1", "4")
    board.add_net(tdo)

    # Additional signal net (THIN - 0.2mm)
    sig1 = Net(name="SIG1", code="7", track_width=0.2, net_class="Signal")
    sig1.add_connection("U1", "17")  # Right side
    sig1.add_connection("U1", "5")  # Left side - crosses through IC
    board.add_net(sig1)

    # Add more signal connections for testing pin routing
    # GPIO signals connecting different IC pins
    sig2 = Net(name="GPIO1", code="8", track_width=0.2, net_class="Signal")
    sig2.add_connection("U1", "9")  # Bottom side
    sig2.add_connection("U1", "25")  # Top side
    board.add_net(sig2)

    sig3 = Net(name="GPIO2", code="9", track_width=0.2, net_class="Signal")
    sig3.add_connection("U1", "10")  # Bottom side
    sig3.add_connection("U1", "26")  # Top side
    board.add_net(sig3)

    print(f"\nAdded {len(board.components)} components, {len(board.nets)} nets")
    print("\nNet widths:")
    for net_name, net in board.nets.items():
        print(f"  {net_name}: {net.track_width}mm ({net.net_class or 'default'})")

    return board


def route_board(board: Board) -> dict:
    """Route the board and return statistics."""
    print("\n" + "=" * 60)
    print("Routing 4-layer board (FPGA strategy)...")
    print("=" * 60)

    net_layer_overrides = {
        # Keep JTAG on the top layer for readability + short paths near the edge.
        "TMS": "F.Cu",
        "TCK": "F.Cu",
        "TDI": "F.Cu",
        "TDO": "F.Cu",
        # Dense pinfield connections: prefer inner layers.
        "SIG1": "In1.Cu",
        "GPIO1": "In1.Cu",
        "GPIO2": "In2.Cu",
        # Rails: default power/ground behavior, but keep explicit.
        "VCC": "F.Cu",
        "GND": "B.Cu",
    }

    strategy = FourLayerFPGA(
        net_layer_overrides=net_layer_overrides,
        net_via_costs={"*": 2.0},
        verbose=True,
    )
    result = strategy.route(board)
    print(result.message)

    # Collect statistics
    stats = {
        "total_nets": len(board.nets),
        "routed_nets": 0,
        "total_segments": 0,
        "total_vias": 0,
        "layers_used": set(),
        "widths_used": {},
    }

    for net_name, net in board.nets.items():
        if len(net.segments) > 0:
            stats["routed_nets"] += 1
            stats["total_segments"] += len(net.segments)
            stats["total_vias"] += len(net.vias)

            for seg in net.segments:
                stats["layers_used"].add(seg.layer)
                width = seg.width
                if width not in stats["widths_used"]:
                    stats["widths_used"][width] = 0
                stats["widths_used"][width] += 1

    return stats


def run_drc(board: Board) -> int:
    """Run internal DRC check and return error count."""
    print("\n" + "=" * 60)
    print("Running DRC...")
    print("=" * 60)

    summary = check_internal_drc(board)
    print(summary.report)
    return summary.errors


def main():
    """Main function."""
    output_dir = Path(__file__).parent

    # Step 1: Create board with optimized widths
    print("=" * 60)
    print("FPGA Board Routing with Optimized Trace Widths")
    print("=" * 60)
    print("\nTrace width configuration:")
    print("  Power/GND: 0.5mm (wide for low resistance)")
    print("  Signals:   0.2mm (thin to fit between IC pins)")

    board = create_fpga_board_with_widths()

    # Save an unrouted baseline board for external routers / debugging.
    unrouted_path = output_dir / "fpga_unrouted.kicad_pcb"
    KicadWriter().write(board, unrouted_path)
    print(f"\nSaved unrouted board to: {unrouted_path}")

    # Step 2: Route board
    stats = route_board(board)

    # Step 3: Print routing statistics
    print("\n" + "=" * 60)
    print("Routing Statistics")
    print("=" * 60)
    print(f"Nets routed: {stats['routed_nets']}/{stats['total_nets']}")
    print(f"Total segments: {stats['total_segments']}")
    print(f"Total vias: {stats['total_vias']}")
    print(f"Layers used: {sorted(stats['layers_used'])}")
    print(f"Trace widths used:")
    for width, count in sorted(stats["widths_used"].items()):
        print(f"  {width}mm: {count} segments")

    # Step 4: Run DRC
    drc_errors = run_drc(board)

    # Step 5: Save board
    print("\n" + "=" * 60)
    print("Saving board...")
    print("=" * 60)
    output_path = output_dir / "fpga_routed_with_widths.kicad_pcb"
    KicadWriter().write(board, output_path)
    print(f"Saved to: {output_path}")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Routing success rate: {stats['routed_nets']}/{stats['total_nets']} nets")
    print(f"DRC errors: {drc_errors}")
    if drc_errors == 0:
        print("Board is ready for manufacturing!")
    else:
        print(f"Board needs {drc_errors} DRC issues fixed.")

    # Print per-net details
    print("\nPer-net routing details:")
    for net_name, net in board.nets.items():
        layers = set(seg.layer for seg in net.segments) if net.segments else set()
        print(
            f"  {net_name}: {len(net.segments)} segments, {len(net.vias)} vias, width={net.track_width}mm, layers={layers or 'unrouted'}"
        )

    return 0 if drc_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
