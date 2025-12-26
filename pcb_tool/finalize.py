#!/usr/bin/env python3
"""
SDK finalization workflow - converts routed board to production-quality.

This module implements the 3-phase workflow that achieves 0 DRC errors:
1. Extract board data (footprints, tracks, nets, edges) to in-memory dict
2. Rebuild board using KiCad library footprints (full graphics, 3D models)
3. Add GND copper zones on F.Cu and B.Cu

Usage:
    from pcb_tool.finalize import finalize_board
    success, msg = finalize_board(Path("input.kicad_pcb"), Path("output.kicad_pcb"))
"""
from pathlib import Path
from typing import Any


# FOOTPRINT_LIBS maps pardal footprint names to KiCad library paths
FOOTPRINT_LIBS = {
    # Resistors SMD
    "R_0805_2012Metric": "/usr/share/kicad/footprints/Resistor_SMD.pretty",
    "R_0603_1608Metric": "/usr/share/kicad/footprints/Resistor_SMD.pretty",
    "R_0805": "/usr/share/kicad/footprints/Resistor_SMD.pretty",
    "R_0603": "/usr/share/kicad/footprints/Resistor_SMD.pretty",
    # Capacitors SMD
    "C_0805_2012Metric": "/usr/share/kicad/footprints/Capacitor_SMD.pretty",
    "C_0603_1608Metric": "/usr/share/kicad/footprints/Capacitor_SMD.pretty",
    "C_0805": "/usr/share/kicad/footprints/Capacitor_SMD.pretty",
    "C_0603": "/usr/share/kicad/footprints/Capacitor_SMD.pretty",
    # Capacitors THT
    "CP_Radial_D6.3mm_P2.50mm": "/usr/share/kicad/footprints/Capacitor_THT.pretty",
    # MOSFETs/Transistors
    "TO-220-3_Vertical": "/usr/share/kicad/footprints/Package_TO_SOT_THT.pretty",
    # Diodes
    "D_DO-41_SOD81_P10.16mm_Horizontal": "/usr/share/kicad/footprints/Diode_THT.pretty",
    # Connectors
    "PinHeader_1x03_P2.54mm_Vertical": "/usr/share/kicad/footprints/Connector_PinHeader_2.54mm.pretty",
    "PinHeader_1x04_P2.54mm_Vertical": "/usr/share/kicad/footprints/Connector_PinHeader_2.54mm.pretty",
    "PinHeader_1x05_P2.54mm_Vertical": "/usr/share/kicad/footprints/Connector_PinHeader_2.54mm.pretty",
    "PinHeader_1x06_P2.54mm_Vertical": "/usr/share/kicad/footprints/Connector_PinHeader_2.54mm.pretty",
    "PinHeader_1x07_P2.54mm_Vertical": "/usr/share/kicad/footprints/Connector_PinHeader_2.54mm.pretty",
    "PinHeader_1x08_P2.54mm_Vertical": "/usr/share/kicad/footprints/Connector_PinHeader_2.54mm.pretty",
    "PinHeader_1x10_P2.54mm_Vertical": "/usr/share/kicad/footprints/Connector_PinHeader_2.54mm.pretty",
    # Voltage regulators
    "SOT-223-3": "/usr/share/kicad/footprints/Package_TO_SOT_SMD.pretty",
    "SOT-223-3_TabPin2": "/usr/share/kicad/footprints/Package_TO_SOT_SMD.pretty",
    # ICs
    "DIP-8_W7.62mm": "/usr/share/kicad/footprints/Package_DIP.pretty",
    "SSOP-20_W5.3mm": "/usr/share/kicad/footprints/Package_SO.pretty",
    # Test points
    "TestPoint_Pad_1.0mm": "/usr/share/kicad/footprints/TestPoint.pretty",
    # Resistors THT
    "R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal": "/usr/share/kicad/footprints/Resistor_THT.pretty",
    # =========================================================================
    # FPGA/BGA packages
    # =========================================================================
    # Lattice MachXO2/iCE40 BGA-132 (8x8mm, 0.5mm pitch)
    "Lattice_iCE40_csBGA-132_8x8mm_Layout14x14_P0.5mm": "/usr/share/kicad/footprints/Package_BGA.pretty",
    "csBGA-132": "/usr/share/kicad/footprints/Package_BGA.pretty",
    "CSPBGA-132": "/usr/share/kicad/footprints/Package_BGA.pretty",
    # Generic BGA packages
    "BGA-132_12x18mm_Layout11x17_P1.0mm": "/usr/share/kicad/footprints/Package_BGA.pretty",
    "BGA-100_11.0x11.0mm_Layout10x10_P1.0mm_Ball0.5mm_Pad0.4mm_NSMD": "/usr/share/kicad/footprints/Package_BGA.pretty",
    "BGA-144_7.0x7.0mm_Layout13x13_P0.5mm_Ball0.3mm_Pad0.25mm_NSMD": "/usr/share/kicad/footprints/Package_BGA.pretty",
    "BGA-256_11.0x11.0mm_Layout20x20_P0.5mm_Ball0.3mm_Pad0.25mm_NSMD": "/usr/share/kicad/footprints/Package_BGA.pretty",
    # =========================================================================
    # QFP packages (for alternative FPGA packages)
    # =========================================================================
    "LQFP-100_14x14mm_P0.5mm": "/usr/share/kicad/footprints/Package_QFP.pretty",
    "LQFP-144_20x20mm_P0.5mm": "/usr/share/kicad/footprints/Package_QFP.pretty",
    "LQFP-128_14x14mm_P0.4mm": "/usr/share/kicad/footprints/Package_QFP.pretty",
    "LQFP-128_14x20mm_P0.5mm": "/usr/share/kicad/footprints/Package_QFP.pretty",
    "TQFP-100_14x14mm_P0.5mm": "/usr/share/kicad/footprints/Package_QFP.pretty",
    "TQFP-144_20x20mm_P0.5mm": "/usr/share/kicad/footprints/Package_QFP.pretty",
    "QFP-32_7x7mm_P0.8mm": "/usr/share/kicad/footprints/Package_QFP.pretty",
    "TQFP-32_7x7mm_P0.8mm": "/usr/share/kicad/footprints/Package_QFP.pretty",
    # =========================================================================
    # JTAG/Debug connectors (2x5 pin headers)
    # =========================================================================
    # 1.27mm pitch (Cortex-style, 10-pin ARM SWD/JTAG)
    "PinHeader_2x05_P1.27mm_Vertical": "/usr/share/kicad/footprints/Connector_PinHeader_1.27mm.pretty",
    "PinHeader_2x05_P1.27mm_Horizontal": "/usr/share/kicad/footprints/Connector_PinHeader_1.27mm.pretty",
    "PinHeader_2x05_P1.27mm_Vertical_SMD": "/usr/share/kicad/footprints/Connector_PinHeader_1.27mm.pretty",
    # 2.54mm pitch (standard JTAG)
    "PinHeader_2x05_P2.54mm_Vertical": "/usr/share/kicad/footprints/Connector_PinHeader_2.54mm.pretty",
    "PinHeader_2x05_P2.54mm_Horizontal": "/usr/share/kicad/footprints/Connector_PinHeader_2.54mm.pretty",
    # 2-pin power connectors
    "PinHeader_1x02_P2.54mm_Vertical": "/usr/share/kicad/footprints/Connector_PinHeader_2.54mm.pretty",
    # =========================================================================
    # Oscillators/Crystals
    # =========================================================================
    "Oscillator_SMD_Abracon_ASE-4Pin_3.2x2.5mm": "/usr/share/kicad/footprints/Oscillator.pretty",
    "Oscillator_SMD_ECS_2520MV-xxx-xx-4Pin_2.5x2.0mm": "/usr/share/kicad/footprints/Oscillator.pretty",
    "Oscillator_SMD_Abracon_ASDMB-4Pin_2.5x2.0mm": "/usr/share/kicad/footprints/Oscillator.pretty",
    "Crystal_SMD_3215-4Pin_3.2x1.5mm": "/usr/share/kicad/footprints/Crystal.pretty",
    # =========================================================================
    # Inductors/Ferrite beads
    # =========================================================================
    "L_0603_1608Metric": "/usr/share/kicad/footprints/Inductor_SMD.pretty",
    "L_0805_2012Metric": "/usr/share/kicad/footprints/Inductor_SMD.pretty",
    "FB_0603": "/usr/share/kicad/footprints/Inductor_SMD.pretty",  # Ferrite bead alias
    "FB_0805": "/usr/share/kicad/footprints/Inductor_SMD.pretty",
    # =========================================================================
    # Buttons/Switches
    # =========================================================================
    "SW_SPST_TL3342": "/usr/share/kicad/footprints/Button_Switch_SMD.pretty",
    "SW_Push_1P1T_NO_6x6mm_H9.5mm": "/usr/share/kicad/footprints/Button_Switch_THT.pretty",
    "Panasonic_EVQPUJ_EVQPUA": "/usr/share/kicad/footprints/Button_Switch_SMD.pretty",
    # =========================================================================
    # LEDs
    # =========================================================================
    "LED_0603_1608Metric": "/usr/share/kicad/footprints/LED_SMD.pretty",
    "LED_0805_2012Metric": "/usr/share/kicad/footprints/LED_SMD.pretty",
    # =========================================================================
    # Additional capacitors (0402 for decoupling)
    # =========================================================================
    "C_0402_1005Metric": "/usr/share/kicad/footprints/Capacitor_SMD.pretty",
    "C_0402": "/usr/share/kicad/footprints/Capacitor_SMD.pretty",
    # =========================================================================
    # Additional resistors (0402)
    # =========================================================================
    "R_0402_1005Metric": "/usr/share/kicad/footprints/Resistor_SMD.pretty",
    "R_0402": "/usr/share/kicad/footprints/Resistor_SMD.pretty",
}


def finalize_board(
    input_pcb: Path, output_pcb: Path, gnd_net: str = "GND"
) -> tuple[bool, str]:
    """
    Run full SDK finalization workflow.

    Args:
        input_pcb: Path to routed board with simplified footprints
        output_pcb: Path to save finalized board
        gnd_net: Net name for copper zones (default: "GND")

    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        import pcbnew
    except ImportError:
        return False, "pcbnew not available. Run with system Python, not venv."

    # Phase 1: Extract board data
    print(f"Phase 1: Extracting data from {input_pcb}...")
    board_data = _extract_board_data(input_pcb)
    print(
        f"  Extracted {len(board_data['footprints'])} footprints, {len(board_data['tracks'])} tracks"
    )

    # Check for unmapped footprints
    unmapped = []
    for fp in board_data["footprints"]:
        if fp["fp_name"] not in FOOTPRINT_LIBS:
            unmapped.append(f"  {fp['ref']} ({fp['fp_name']})")
    if unmapped:
        return False, f"Cannot finalize - unmapped footprints:\n" + "\n".join(
            unmapped[:10]
        )

    # Phase 2: Build with library footprints
    print("Phase 2: Building with KiCad library footprints...")
    final_board = _build_with_library_footprints(board_data)
    print(f"  Created board with {len(list(final_board.GetFootprints()))} footprints")

    # Phase 3: Add zones
    print("Phase 3: Adding GND zones...")
    _add_gnd_zones(final_board, gnd_net)

    # Save
    final_board.Save(str(output_pcb))
    return True, f"Finalized board saved to {output_pcb}"


def _extract_board_data(input_pcb: Path) -> dict[str, Any]:
    """Phase 1: Extract all board data to in-memory dict."""
    import pcbnew

    board = pcbnew.LoadBoard(str(input_pcb))

    data = {
        "net_names": [],
        "pad_nets": {},  # "REF:PAD" -> net_name
        "footprints": [],
        "tracks": [],
        "edges": [],
        "copper_layer_count": board.GetCopperLayerCount(),  # Preserve layer count
    }

    # Extract nets from pads and tracks
    net_names = set()
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname():
                net_names.add(pad.GetNetname())
    for track in board.GetTracks():
        if track.GetNetname():
            net_names.add(track.GetNetname())
    data["net_names"] = list(net_names)

    # Extract pad-to-net mapping (critical for reconnection)
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        for pad in fp.Pads():
            if pad.GetNetname():
                data["pad_nets"][f"{ref}:{pad.GetNumber()}"] = pad.GetNetname()

    # Extract footprint info with pad 1 position for alignment
    for fp in board.GetFootprints():
        pos = fp.GetPosition()
        pad1_pos = pos
        for pad in fp.Pads():
            if pad.GetNumber() == "1":
                pad1_pos = pad.GetPosition()
                break

        data["footprints"].append(
            {
                "fp_name": str(fp.GetFPID().GetLibItemName()),
                "ref": fp.GetReference(),
                "value": fp.GetValue(),
                "pos_x": pcbnew.ToMM(pos.x),
                "pos_y": pcbnew.ToMM(pos.y),
                "pad1_x": pcbnew.ToMM(pad1_pos.x),
                "pad1_y": pcbnew.ToMM(pad1_pos.y),
                "orientation": fp.GetOrientationDegrees(),
                "layer": fp.GetLayer(),
            }
        )

    # Extract tracks and vias
    for track in board.GetTracks():
        is_via = isinstance(track, pcbnew.PCB_VIA)
        info = {
            "is_via": is_via,
            "net_name": track.GetNetname(),
            "width": track.GetWidth(),
            "layer": track.GetLayer(),
        }
        if is_via:
            pos = track.GetPosition()
            info["pos_x"] = pos.x
            info["pos_y"] = pos.y
            info["drill"] = track.GetDrill()
            info["via_type"] = int(track.GetViaType())
        else:
            info["start_x"] = track.GetStart().x
            info["start_y"] = track.GetStart().y
            info["end_x"] = track.GetEnd().x
            info["end_y"] = track.GetEnd().y
        data["tracks"].append(info)

    # Extract board outline
    for drawing in board.GetDrawings():
        if drawing.GetLayer() == pcbnew.Edge_Cuts:
            data["edges"].append(
                {
                    "shape": int(drawing.GetShape()),
                    "start_x": drawing.GetStart().x,
                    "start_y": drawing.GetStart().y,
                    "end_x": drawing.GetEnd().x,
                    "end_y": drawing.GetEnd().y,
                    "width": drawing.GetWidth(),
                }
            )

    return data


def _build_with_library_footprints(data: dict[str, Any]) -> "pcbnew.BOARD":
    """Phase 2: Create new board with library footprints."""
    import pcbnew

    board = pcbnew.BOARD()
    io = pcbnew.PCB_IO_KICAD_SEXPR()

    # Set copper layer count (preserve from input board)
    copper_layers = data.get("copper_layer_count", 2)
    if copper_layers > 2:
        board.SetCopperLayerCount(copper_layers)
        print(f"  Set copper layer count to {copper_layers}")

    # Create nets
    for net_name in data["net_names"]:
        board.Add(pcbnew.NETINFO_ITEM(board, net_name))

    # Add footprints from library
    for info in data["footprints"]:
        lib_path = FOOTPRINT_LIBS.get(info["fp_name"])
        if not lib_path:
            print(f"  Warning: No library for {info['fp_name']} ({info['ref']})")
            continue

        try:
            fp = io.FootprintLoad(lib_path, info["fp_name"])
        except Exception as e:
            print(f"  Error loading {info['fp_name']}: {e}")
            continue

        # Find pad 1 offset in library footprint for alignment
        lib_pad1_x, lib_pad1_y = 0, 0
        for pad in fp.Pads():
            if pad.GetNumber() == "1":
                lib_pad1_x = pcbnew.ToMM(pad.GetPosition().x)
                lib_pad1_y = pcbnew.ToMM(pad.GetPosition().y)
                break

        # Position by pad 1 alignment (critical for routing to work)
        new_x = info.get("pad1_x", info["pos_x"]) - lib_pad1_x
        new_y = info.get("pad1_y", info["pos_y"]) - lib_pad1_y

        pos = pcbnew.VECTOR2I(pcbnew.FromMM(new_x), pcbnew.FromMM(new_y))
        fp.SetPosition(pos)
        fp.SetOrientationDegrees(info["orientation"])
        fp.SetReference(info["ref"])
        fp.SetValue(info["value"])

        # Flip if on back layer
        if info["layer"] == pcbnew.B_Cu:
            fp.Flip(pos, False)

        # Reconnect nets to pads
        for pad in fp.Pads():
            key = f"{info['ref']}:{pad.GetNumber()}"
            net_name = data["pad_nets"].get(key)
            if net_name:
                net_info = board.FindNet(net_name)
                if net_info:
                    pad.SetNet(net_info)

        board.Add(fp)

    # Add tracks and vias
    for info in data["tracks"]:
        net_info = board.FindNet(info["net_name"]) if info["net_name"] else None

        if info["is_via"]:
            via = pcbnew.PCB_VIA(board)
            via.SetPosition(pcbnew.VECTOR2I(info["pos_x"], info["pos_y"]))
            via.SetWidth(info["width"])
            via.SetDrill(info["drill"])
            via.SetViaType(pcbnew.VIATYPE(info["via_type"]))
            if net_info:
                via.SetNet(net_info)
            board.Add(via)
        else:
            track = pcbnew.PCB_TRACK(board)
            track.SetStart(pcbnew.VECTOR2I(info["start_x"], info["start_y"]))
            track.SetEnd(pcbnew.VECTOR2I(info["end_x"], info["end_y"]))
            track.SetWidth(info["width"])
            track.SetLayer(info["layer"])
            if net_info:
                track.SetNet(net_info)
            board.Add(track)

    # Add board outline
    for info in data["edges"]:
        shape = pcbnew.PCB_SHAPE(board)
        shape.SetShape(info["shape"])
        shape.SetStart(pcbnew.VECTOR2I(info["start_x"], info["start_y"]))
        shape.SetEnd(pcbnew.VECTOR2I(info["end_x"], info["end_y"]))
        shape.SetLayer(pcbnew.Edge_Cuts)
        shape.SetWidth(info["width"])
        board.Add(shape)

    return board


def _add_gnd_zones(board: "pcbnew.BOARD", gnd_net: str = "GND"):
    """Phase 3: Add GND copper zones on all copper layers (supports 2/4/6/8-layer boards)."""
    import pcbnew

    gnd_net_info = board.FindNet(gnd_net)
    if not gnd_net_info:
        print(f"  Warning: Net '{gnd_net}' not found, skipping zones")
        return

    # Get board bounding box for zone outline
    bbox = board.GetBoardEdgesBoundingBox()
    if bbox.GetWidth() == 0:
        bbox = board.ComputeBoundingBox()

    # Get all enabled copper layers from board
    # Layer IDs: F.Cu=0, B.Cu=2, In1.Cu=4, In2.Cu=6, ... (even numbers for copper)
    copper_layers = []
    enabled = board.GetEnabledLayers()

    # Check standard copper layers explicitly
    standard_copper = [
        pcbnew.F_Cu,
        pcbnew.B_Cu,
    ]
    # Add inner layers if board has more than 2 copper layers
    num_copper = board.GetCopperLayerCount()
    if num_copper >= 4:
        standard_copper.extend([pcbnew.In1_Cu, pcbnew.In2_Cu])
    if num_copper >= 6:
        standard_copper.extend([pcbnew.In3_Cu, pcbnew.In4_Cu])
    if num_copper >= 8:
        standard_copper.extend([pcbnew.In5_Cu, pcbnew.In6_Cu])

    for layer_id in standard_copper:
        if enabled.Contains(layer_id):
            copper_layers.append(layer_id)

    # Fallback to outer layers if detection fails
    if not copper_layers:
        copper_layers = [pcbnew.F_Cu, pcbnew.B_Cu]

    layer_names = [board.GetLayerName(lid) for lid in copper_layers]
    print(
        f"  Creating GND zones on {len(copper_layers)} layers: {', '.join(layer_names)}"
    )

    # Create zones on all copper layers
    for layer in copper_layers:
        zone = pcbnew.ZONE(board)
        zone.SetNet(gnd_net_info)
        zone.SetLayer(layer)
        zone.SetIsFilled(False)

        # Create outline slightly inside board edges (0.5mm inset)
        outline = zone.Outline()
        outline.NewOutline()
        inset = pcbnew.FromMM(0.5)
        outline.Append(bbox.GetLeft() + inset, bbox.GetTop() + inset)
        outline.Append(bbox.GetRight() - inset, bbox.GetTop() + inset)
        outline.Append(bbox.GetRight() - inset, bbox.GetBottom() - inset)
        outline.Append(bbox.GetLeft() + inset, bbox.GetBottom() - inset)

        # Zone settings
        zone.SetLocalClearance(pcbnew.FromMM(0.3))
        zone.SetMinThickness(pcbnew.FromMM(0.25))
        zone.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        zone.SetThermalReliefGap(pcbnew.FromMM(0.5))
        zone.SetThermalReliefSpokeWidth(pcbnew.FromMM(0.5))

        board.Add(zone)

    # Note: Zone filling via pcbnew Python API can segfault.
    # We leave zones unfilled - KiCad will auto-fill them when the file is opened.
    # To fill manually, run: kicad-cli pcb drc --fill-zones <file>

    print(
        f"  Added GND zones on {len(copper_layers)} copper layers (unfilled - KiCad will refill on open)"
    )


def main() -> int:
    """Standalone CLI for finalization (run with system Python).

    This entry point is meant to be run with /usr/bin/python3 (system Python)
    which has access to the pcbnew module from KiCad.

    Usage:
        /usr/bin/python3 -m pcb_tool.finalize input.kicad_pcb output.kicad_pcb
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="pardal-finalize",
        description="Finalize PCB with KiCad library footprints (requires system Python with pcbnew)",
    )
    parser.add_argument("input", type=Path, help="Input .kicad_pcb file (routed board)")
    parser.add_argument(
        "output", type=Path, help="Output .kicad_pcb file (finalized board)"
    )
    parser.add_argument(
        "--gnd-net", default="GND", help="Net name for copper zones (default: GND)"
    )

    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: Input file not found: {args.input}", file=sys.stderr)
        return 1

    success, msg = finalize_board(args.input, args.output, args.gnd_net)
    print(msg)
    return 0 if success else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
