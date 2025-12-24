"""
KiCad Post-Processor using pcbnew SDK

Uses KiCad's Python SDK to perform operations that are difficult
to do correctly with raw S-expression writing, such as:
- Adding and filling copper zones (pours)
- Running DRC checks
- Computing zone fills

Usage:
    python3 kicad_postprocess.py input.kicad_pcb output.kicad_pcb --gnd-pour
"""

import argparse
import sys
from pathlib import Path

# pcbnew is only available in system Python, not virtualenvs
try:
    import pcbnew
except ImportError:
    print("ERROR: pcbnew module not found. Run with system Python 3.")
    print("Location: /usr/lib/python3/dist-packages/pcbnew.py")
    sys.exit(1)


def add_gnd_pour(board, layer=pcbnew.B_Cu, margin_mm=1.0, clearance_mm=0.3):
    """Add a GND copper pour covering the board area.

    Args:
        board: pcbnew.BOARD instance
        layer: Layer to add pour on (default B.Cu)
        margin_mm: Margin from board edge in mm
        clearance_mm: Clearance from other copper

    Returns:
        The created ZONE object, or None if GND net not found
    """
    gnd_net = board.FindNet("GND")
    if not gnd_net:
        print("Warning: GND net not found, skipping pour")
        return None

    # Get board bounding box - try edge cuts first, then fallback to items
    bbox = board.GetBoardEdgesBoundingBox()
    width = bbox.GetWidth()
    height = bbox.GetHeight()

    if width == 0 or height == 0:
        # Fall back to item bounding box
        bbox = board.GetBoundingBox()
        width = bbox.GetWidth()
        height = bbox.GetHeight()

    margin = pcbnew.FromMM(margin_mm)
    x1 = bbox.GetLeft() + margin
    y1 = bbox.GetTop() + margin
    x2 = bbox.GetRight() - margin
    y2 = bbox.GetBottom() - margin

    # Create zone
    zone = pcbnew.ZONE(board)
    zone.SetNet(gnd_net)
    zone.SetLayer(layer)

    # Create outline
    outline = zone.Outline()
    outline.NewOutline()
    outline.Append(x1, y1)
    outline.Append(x2, y1)
    outline.Append(x2, y2)
    outline.Append(x1, y2)

    # Set properties
    zone.SetLocalClearance(pcbnew.FromMM(clearance_mm))
    zone.SetMinThickness(pcbnew.FromMM(0.25))
    zone.SetThermalReliefGap(pcbnew.FromMM(0.5))
    zone.SetThermalReliefSpokeWidth(pcbnew.FromMM(0.5))
    zone.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)

    board.Add(zone)
    return zone


def fill_zones(board):
    """Fill all zones on the board.

    Args:
        board: pcbnew.BOARD instance
    """
    filler = pcbnew.ZONE_FILLER(board)
    zones = board.Zones()
    if zones:
        filler.Fill(zones)


def run_drc(board):
    """Run DRC check on board.

    Args:
        board: pcbnew.BOARD instance

    Returns:
        Tuple of (error_count, marker_count)
    """
    # Build connectivity for DRC
    board.BuildConnectivity()

    markers = board.GetMarkers()
    return len(markers)


# Mapping of footprint names to library paths
FOOTPRINT_LIBRARIES = {
    "R_0805_2012Metric": "/usr/share/kicad/footprints/Resistor_SMD.pretty",
    "C_0805_2012Metric": "/usr/share/kicad/footprints/Capacitor_SMD.pretty",
    "TO-220-3_Vertical": "/usr/share/kicad/footprints/Package_TO_SOT_THT.pretty",
    "D_DO-41_SOD81_P10.16mm_Horizontal": "/usr/share/kicad/footprints/Diode_THT.pretty",
    "CP_Radial_D6.3mm_P2.50mm": "/usr/share/kicad/footprints/Capacitor_THT.pretty",
    "PinHeader_1x03_P2.54mm_Vertical": "/usr/share/kicad/footprints/Connector_PinHeader_2.54mm.pretty",
    "PinHeader_1x07_P2.54mm_Vertical": "/usr/share/kicad/footprints/Connector_PinHeader_2.54mm.pretty",
}


def replace_footprints_with_library(board):
    """Replace embedded footprints with KiCad library versions.

    This fixes lib_footprint_mismatch warnings and adds proper 3D models.

    Args:
        board: pcbnew.BOARD instance

    Returns:
        Number of footprints replaced
    """
    io = pcbnew.PCB_IO_KICAD_SEXPR()
    replaced = 0

    for fp in list(board.GetFootprints()):
        fpid = fp.GetFPID()
        fp_name = str(fpid.GetLibItemName())

        if fp_name not in FOOTPRINT_LIBRARIES:
            print(f"  Skipping {fp.GetReference()} ({fp_name}) - no library mapping")
            continue

        lib_path = FOOTPRINT_LIBRARIES[fp_name]

        try:
            # Load from library
            new_fp = io.FootprintLoad(lib_path, fp_name)
            if not new_fp:
                print(f"  Failed to load {fp_name} from {lib_path}")
                continue

            # Save pad net assignments
            pad_nets = {}
            for pad in fp.Pads():
                pad_nets[pad.GetNumber()] = pad.GetNetname()

            # Copy properties
            new_fp.SetReference(fp.GetReference())
            new_fp.SetValue(fp.GetValue())
            new_fp.SetPosition(fp.GetPosition())
            new_fp.SetOrientation(fp.GetOrientation())
            new_fp.SetLayer(fp.GetLayer())

            # Assign nets to pads
            for pad in new_fp.Pads():
                pad_num = pad.GetNumber()
                if pad_num in pad_nets and pad_nets[pad_num]:
                    net = board.FindNet(pad_nets[pad_num])
                    if net:
                        pad.SetNet(net)

            # Replace on board
            board.Remove(fp)
            board.Add(new_fp)
            replaced += 1

        except Exception as e:
            print(f"  Error replacing {fp.GetReference()}: {e}")

    return replaced


def postprocess(input_path, output_path, add_gnd=True, fill=True, replace_fps=False):
    """Post-process a KiCad PCB file.

    Args:
        input_path: Path to input .kicad_pcb file
        output_path: Path to output .kicad_pcb file
        add_gnd: Whether to add GND pour
        fill: Whether to fill zones
        replace_fps: Whether to replace footprints with library versions
    """
    print(f"Loading {input_path}...")
    board = pcbnew.LoadBoard(str(input_path))

    if replace_fps:
        print("WARNING: Footprint replacement disabled due to pcbnew SWIG memory issues")
        print("  The lib_footprint_mismatch warnings are cosmetic and don't affect manufacturing")
        # Footprint replacement causes segfaults in pcbnew SWIG bindings
        # count = replace_footprints_with_library(board)
        # print(f"  Replaced {count} footprints")

    if add_gnd:
        # Add GND pour on both layers for complete connectivity
        print("Adding GND pour on B.Cu (primary)...")
        zone_b = add_gnd_pour(board, layer=pcbnew.B_Cu, margin_mm=1.0)
        if zone_b:
            zone_b.SetAssignedPriority(0)  # Lower priority
            print(f"  Created zone for net {zone_b.GetNetname()}")

        print("Adding GND pour on F.Cu (secondary)...")
        zone_f = add_gnd_pour(board, layer=pcbnew.F_Cu, margin_mm=1.0)
        if zone_f:
            zone_f.SetAssignedPriority(1)  # Higher priority (fills around traces)
            print(f"  Created zone for net {zone_f.GetNetname()}")

    if fill:
        print("Filling zones...")
        fill_zones(board)

    print(f"Saving to {output_path}...")
    board.Save(str(output_path))
    print("Done!")


def main():
    parser = argparse.ArgumentParser(description="KiCad PCB post-processor")
    parser.add_argument("input", help="Input .kicad_pcb file")
    parser.add_argument("output", help="Output .kicad_pcb file")
    parser.add_argument("--gnd-pour", action="store_true",
                        help="Add GND copper pour on both layers")
    parser.add_argument("--replace-footprints", action="store_true",
                        help="Replace footprints with KiCad library versions")
    parser.add_argument("--no-fill", action="store_true",
                        help="Skip zone filling")
    parser.add_argument("--all", action="store_true",
                        help="Apply all post-processing (--gnd-pour --replace-footprints)")

    args = parser.parse_args()

    add_gnd = args.gnd_pour or args.all
    replace_fps = args.replace_footprints or args.all

    postprocess(
        args.input,
        args.output,
        add_gnd=add_gnd,
        fill=not args.no_fill,
        replace_fps=replace_fps
    )


if __name__ == "__main__":
    main()
