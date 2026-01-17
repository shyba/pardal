#!/usr/bin/env python3
"""
Test script for 4-layer FPGA board routing.

Creates a simplified version of the MachXO2 bring-up board:
- Central IC placeholder (QFP-like footprint)
- Decoupling capacitors around IC
- JTAG header
- Power/GND nets

Tests the full 4-layer workflow: create -> route -> save -> verify
"""
import sys
from pathlib import Path

# Add pardal-pcb to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pcb_tool.data_model import Board, Net, Component, Pad, STANDARD_LAYER_STACKS
from pcb_tool.kicad_writer import KicadWriter
from pcb_tool.api import check_internal_drc
from pcb_tool.routing_strategies import FourLayerFPGA


def create_4layer_fpga_board() -> Board:
    """Create a 4-layer board with FPGA-like component layout."""

    # Create 4-layer board
    board = Board(layers=STANDARD_LAYER_STACKS[4])
    board.width = 40.0
    board.height = 40.0

    print(f"Created {board.layer_count}-layer board: {board.layers}")

    # Central IC (using mapped TQFP footprint)
    ic = Component(
        ref="U1",
        value="FPGA",
        footprint="TQFP-32_7x7mm_P0.8mm",  # Mapped in finalize.py
        position=(20.0, 20.0),
        rotation=0,
        layer="F.Cu",
    )
    # Add pads around the IC (simplified - just corners and some middle pads)
    pad_positions = [
        # Left side (pins 1-8)
        ("1", (-3.5, -2.8)),
        ("2", (-3.5, -2.0)),
        ("3", (-3.5, -1.2)),
        ("4", (-3.5, -0.4)),
        ("5", (-3.5, 0.4)),
        ("6", (-3.5, 1.2)),
        ("7", (-3.5, 2.0)),
        ("8", (-3.5, 2.8)),
        # Bottom (pins 9-16)
        ("9", (-2.8, 3.5)),
        ("10", (-2.0, 3.5)),
        ("11", (-1.2, 3.5)),
        ("12", (-0.4, 3.5)),
        ("13", (0.4, 3.5)),
        ("14", (1.2, 3.5)),
        ("15", (2.0, 3.5)),
        ("16", (2.8, 3.5)),
        # Right side (pins 17-24)
        ("17", (3.5, 2.8)),
        ("18", (3.5, 2.0)),
        ("19", (3.5, 1.2)),
        ("20", (3.5, 0.4)),
        ("21", (3.5, -0.4)),
        ("22", (3.5, -1.2)),
        ("23", (3.5, -2.0)),
        ("24", (3.5, -2.8)),
        # Top (pins 25-32)
        ("25", (2.8, -3.5)),
        ("26", (2.0, -3.5)),
        ("27", (1.2, -3.5)),
        ("28", (0.4, -3.5)),
        ("29", (-0.4, -3.5)),
        ("30", (-1.2, -3.5)),
        ("31", (-2.0, -3.5)),
        ("32", (-2.8, -3.5)),
    ]
    for pad_num, offset in pad_positions:
        ic.pads.append(
            Pad(
                number=int(pad_num),
                position_offset=offset,
                size=(0.5, 1.2),
                shape="rect",
            )
        )
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
            rotation=0 if pos[0] != 20.0 else 90,  # Rotate vertical caps
            layer="F.Cu",
        )
        cap.pads.append(
            Pad(number=1, position_offset=(-0.8, 0.0), size=(0.9, 0.9), shape="rect")
        )
        cap.pads.append(
            Pad(number=2, position_offset=(0.8, 0.0), size=(0.9, 0.9), shape="rect")
        )
        board.add_component(cap)

    # JTAG header (2x5 1.27mm pitch - Cortex style)
    jtag = Component(
        ref="J1",
        value="JTAG",
        footprint="PinHeader_2x05_P1.27mm_Vertical",  # Mapped in finalize.py
        position=(5.0, 20.0),
        rotation=0,
        layer="F.Cu",
    )
    for i in range(10):
        row = i % 2
        col = i // 2
        jtag.pads.append(
            Pad(
                number=i + 1,
                position_offset=(row * 1.27, col * 1.27 - 2.54),
                size=(0.7, 0.7),
                shape="circle",
            )
        )
    board.add_component(jtag)

    # Power connector (2-pin header)
    pwr = Component(
        ref="J2",
        value="PWR",
        footprint="PinHeader_1x02_P2.54mm_Vertical",  # Mapped in finalize.py
        position=(35.0, 20.0),
        rotation=0,
        layer="F.Cu",
    )
    pwr.pads.append(
        Pad(number=1, position_offset=(0.0, -1.27), size=(1.0, 1.0), shape="circle")
    )
    pwr.pads.append(
        Pad(number=2, position_offset=(0.0, 1.27), size=(1.0, 1.0), shape="circle")
    )
    board.add_component(pwr)

    # Create nets
    # Power net: VCC - connects to IC VCC pins and cap positive terminals
    vcc = Net(name="VCC", code="1", track_width=0.4)
    vcc.add_connection("J2", "1")  # Power input
    vcc.add_connection("U1", "8")  # IC VCC pin
    vcc.add_connection("U1", "24")  # IC VCC pin 2
    vcc.add_connection("C1", "1")
    vcc.add_connection("C2", "1")
    vcc.add_connection("C3", "1")
    vcc.add_connection("C4", "1")
    board.add_net(vcc)

    # Ground net: GND
    gnd = Net(name="GND", code="2", track_width=0.4)
    gnd.add_connection("J2", "2")
    gnd.add_connection("U1", "16")  # IC GND pin
    gnd.add_connection("U1", "32")  # IC GND pin 2
    gnd.add_connection("C1", "2")
    gnd.add_connection("C2", "2")
    gnd.add_connection("C3", "2")
    gnd.add_connection("C4", "2")
    board.add_net(gnd)

    # JTAG signals
    tms = Net(name="TMS", code="3")
    tms.add_connection("J1", "2")
    tms.add_connection("U1", "1")  # TMS pin
    board.add_net(tms)

    tck = Net(name="TCK", code="4")
    tck.add_connection("J1", "4")
    tck.add_connection("U1", "2")  # TCK pin
    board.add_net(tck)

    tdi = Net(name="TDI", code="5")
    tdi.add_connection("J1", "8")
    tdi.add_connection("U1", "3")  # TDI pin
    board.add_net(tdi)

    tdo = Net(name="TDO", code="6")
    tdo.add_connection("J1", "6")
    tdo.add_connection("U1", "4")  # TDO pin
    board.add_net(tdo)

    # A signal net that would benefit from inner layer routing
    sig1 = Net(name="SIG1", code="7")
    sig1.add_connection("U1", "17")  # Right side
    sig1.add_connection("U1", "5")  # Left side - crosses through IC
    board.add_net(sig1)

    print(f"Added {len(board.components)} components, {len(board.nets)} nets")
    return board


def route_board(board: Board) -> bool:
    """Route the board using the FPGA routing strategy."""
    print("\nRouting board...")
    print(
        f"Board: {board.width}x{board.height}mm, {len(board.layers)} layers: {board.layers}"
    )

    strategy = FourLayerFPGA(
        net_layer_overrides={
            "VCC": "F.Cu",
            "GND": "B.Cu",
            "TMS": "F.Cu",
            "TCK": "F.Cu",
            "TDI": "F.Cu",
            "TDO": "F.Cu",
            "SIG1": "In1.Cu",
        },
        net_via_costs={"*": 2.0},
        verbose=True,
    )
    result = strategy.route(board)
    print(result.message)

    # Check if any nets were routed
    routed_count = 0
    for net in board.nets.values():
        if len(net.segments) > 0:
            routed_count += 1
            # Check which layers have traces
            layers_used = set(seg.layer for seg in net.segments)
            print(f"  {net.name}: {len(net.segments)} segments on {layers_used}")

    return routed_count > 0


def main():
    """Main test function."""
    output_dir = Path(__file__).parent

    # Step 1: Create board
    print("=" * 60)
    print("Step 1: Creating 4-layer FPGA test board")
    print("=" * 60)
    board = create_4layer_fpga_board()

    # Step 2: Route board
    print("\n" + "=" * 60)
    print("Step 2: Routing board")
    print("=" * 60)
    success = route_board(board)
    drc = check_internal_drc(board)
    if drc.errors == 0 and drc.warnings == 0:
        print("✅ DRC clean (internal)")
    else:
        print("⚠️  DRC issues (internal):")
        print(drc.report)

    # Step 3: Save board
    print("\n" + "=" * 60)
    print("Step 3: Saving board")
    print("=" * 60)
    output_path = output_dir / "fpga_4layer_routed.kicad_pcb"
    KicadWriter().write(board, output_path)
    print(f"Saved to: {output_path}")

    # Step 4: Verify layer content
    print("\n" + "=" * 60)
    print("Step 4: Verifying output")
    print("=" * 60)
    content = output_path.read_text()

    layers_found = []
    for layer in ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]:
        if f'"{layer}"' in content:
            layers_found.append(layer)
    print(f"Layers in output: {layers_found}")

    # Check for traces on inner layers
    if '"In1.Cu"' in content or '"In2.Cu"' in content:
        print("Inner layer content detected!")
    else:
        print(
            "Note: No inner layer traces (may be expected if routing stayed on outer layers)"
        )

    print("\n" + "=" * 60)
    print("Test complete!")
    print("=" * 60)
    print(f"\nNext steps to test finalize:")
    print(
        f"  /usr/bin/python3 -m pcb_tool.finalize {output_path} {output_dir}/fpga_4layer_final.kicad_pcb"
    )
    print(f"  kicad-cli pcb drc {output_dir}/fpga_4layer_final.kicad_pcb")

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
