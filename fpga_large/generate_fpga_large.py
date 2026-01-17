#!/usr/bin/env python3
"""Generate a "large FPGA" BGA-324 breakout board (4-layer) using pcbnew.

Goal: create a board that can be used as a stress-test/fixture for routing large
BGAs. This generator places a via-in-pad microvia (F.Cu -> In1.Cu) on every BGA
pad so the exported Specctra DSN includes a microvia via-type for FreeRouting.

Note: This board intentionally starts with 324 unconnected 2-pin nets (BGA pad
to perimeter testpoint) and is meant to be routed by an autorouter.

Run inside KiCad 9's Python environment (docker recommended):
  docker run --rm -v "$PWD:/work" -w /work kicad/kicad:9.0.6-full \\
    python3 /work/pardal-pcb/fpga_large/generate_fpga_large.py \\
      /work/pardal-pcb/fpga_large/fpga_large_csg324.kicad_pcb
"""

from __future__ import annotations

import sys
from pathlib import Path

import pcbnew


BGA_LIB_DIR = "/usr/share/kicad/footprints/Package_BGA.pretty"
BGA_FOOTPRINT_NAME = "Xilinx_CSG324"

TP_LIB_DIR = "/usr/share/kicad/footprints/TestPoint.pretty"
TP_FOOTPRINT_NAME = "TestPoint_Pad_D1.0mm"


def _add_rect_outline(board: pcbnew.BOARD, *, x0_mm: float, y0_mm: float, x1_mm: float, y1_mm: float) -> None:
    pts = [
        (x0_mm, y0_mm),
        (x1_mm, y0_mm),
        (x1_mm, y1_mm),
        (x0_mm, y1_mm),
        (x0_mm, y0_mm),
    ]

    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        shape = pcbnew.PCB_SHAPE(board)
        shape.SetShape(pcbnew.SHAPE_T_SEGMENT)
        shape.SetLayer(pcbnew.Edge_Cuts)
        shape.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(ax), pcbnew.FromMM(ay)))
        shape.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(bx), pcbnew.FromMM(by)))
        shape.SetWidth(pcbnew.FromMM(0.1))
        board.Add(shape)


def _ensure_net(board: pcbnew.BOARD, name: str) -> pcbnew.NETINFO_ITEM:
    nets = board.GetNetsByName()
    if name in nets:
        return nets[name]
    net = pcbnew.NETINFO_ITEM(board, name)
    board.Add(net)
    return net


def _sorted_pad_keys(pad: pcbnew.PAD) -> tuple:
    num = pad.GetNumber()
    # Prefer alpha+numeric ordering for typical BGA names (e.g. A1, B12, AA1).
    letters = "".join([c for c in num if c.isalpha()])
    digits = "".join([c for c in num if c.isdigit()])
    return (len(letters), letters, int(digits) if digits else 0, num)


def _gen_testpoint_positions(
    *,
    x0_mm: float,
    y0_mm: float,
    x1_mm: float,
    y1_mm: float,
    per_side: int,
    inset_mm: float,
) -> list[tuple[float, float, float]]:
    # Returns (x, y, rotation_deg), clockwise starting at top-left.
    #
    # `per_side` is the number of points per edge *including both corners*.
    # To avoid duplicating corner points between edges, we exclude the first
    # point on each subsequent edge, and exclude the final point on the last edge.
    xs = [
        x0_mm
        + inset_mm
        + i * ((x1_mm - x0_mm - 2 * inset_mm) / (per_side - 1))
        for i in range(per_side)
    ]
    ys = [
        y0_mm
        + inset_mm
        + i * ((y1_mm - y0_mm - 2 * inset_mm) / (per_side - 1))
        for i in range(per_side)
    ]

    pos: list[tuple[float, float, float]] = []
    # Top edge (left->right), includes both corners.
    for x in xs:
        pos.append((x, y0_mm + inset_mm, 0.0))
    # Right edge (top->bottom), skip top-right corner.
    for y in ys[1:]:
        pos.append((x1_mm - inset_mm, y, 90.0))
    # Bottom edge (right->left), skip bottom-right corner.
    for x in reversed(xs[:-1]):
        pos.append((x, y1_mm - inset_mm, 180.0))
    # Left edge (bottom->top), skip bottom-left and top-left corners.
    for y in reversed(ys[1:-1]):
        pos.append((x0_mm + inset_mm, y, 270.0))
    return pos


def _strip_footprint_graphics(fp: pcbnew.FOOTPRINT) -> None:
    # DRC for a dense perimeter of testpoints is dominated by silkscreen and courtyard
    # overlaps; for this routing fixture, keep only copper/mask/paste for the pad.
    move_layers = {
        pcbnew.F_SilkS,
        pcbnew.B_SilkS,
        pcbnew.F_CrtYd,
        pcbnew.B_CrtYd,
        pcbnew.F_Fab,
        pcbnew.B_Fab,
    }
    for item in list(fp.GraphicalItems()):
        if item.GetLayer() in move_layers:
            # Removing graphical items from a loaded footprint can trigger SWIG
            # wrapper issues in some KiCad builds. Instead, move them to a
            # non-DRC layer.
            item.SetLayer(pcbnew.Dwgs_User)


def _make_layer_anchor(
    board: pcbnew.BOARD, *, net: pcbnew.NETINFO_ITEM, pos: pcbnew.VECTOR2I, layer: int
) -> None:
    """Add a tiny copper-filled circle on a layer to prevent 'via_dangling' DRC warnings."""
    radius_mm = 0.15
    shape = pcbnew.PCB_SHAPE(board)
    shape.SetShape(pcbnew.SHAPE_T_CIRCLE)
    shape.SetLayer(layer)
    shape.SetNet(net)
    shape.SetFilled(True)
    shape.SetWidth(pcbnew.FromMM(0.05))
    shape.SetStart(pos)
    shape.SetEnd(pcbnew.VECTOR2I(pos.x + pcbnew.FromMM(radius_mm), pos.y))
    board.Add(shape)


def generate_board(out_path: Path) -> None:
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(4)

    # Aggressive-ish HDI-ish defaults to make routing feasible for a dense 324-ball
    # breakout fixture. These defaults mainly influence what KiCad exports into
    # Specctra DSN (track width, clearances, default via sizes).
    ds = board.GetDesignSettings()
    ds.m_TrackMinWidth = pcbnew.FromMM(0.10)
    ds.m_MinClearance = pcbnew.FromMM(0.10)
    ds.m_HoleClearance = pcbnew.FromMM(0.10)
    ds.m_HoleToHoleMin = pcbnew.FromMM(0.10)
    ds.m_ViasMinAnnularWidth = pcbnew.FromMM(0.10)
    # KiCad's "min diameter/min hole" constraints apply to blind/buried vias too, so
    # set them low enough to permit the microvias used for BGA escape.
    ds.m_ViasMinSize = pcbnew.FromMM(0.35)
    ds.m_MinThroughDrill = pcbnew.FromMM(0.15)
    ds.m_MicroViasMinSize = pcbnew.FromMM(0.35)
    ds.m_MicroViasMinDrill = pcbnew.FromMM(0.15)
    try:
        ds.SetCustomTrackWidth(pcbnew.FromMM(0.10))
        ds.SetTrackWidthIndex(0)
    except Exception:
        pass
    try:
        ds.UseCustomTrackViaSize(True)
        ds.SetCustomViaSize(pcbnew.FromMM(0.40))
        ds.SetCustomViaDrill(pcbnew.FromMM(0.20))
        ds.SetViaSizeIndex(0)
    except Exception:
        pass
    try:
        default_nc = board.GetAllNetClasses().get("Default")
        if default_nc is not None:
            default_nc.SetTrackWidth(pcbnew.FromMM(0.10))
            default_nc.SetClearance(pcbnew.FromMM(0.10))
            default_nc.SetViaDiameter(pcbnew.FromMM(0.40))
            default_nc.SetViaDrill(pcbnew.FromMM(0.20))
            default_nc.SetuViaDiameter(pcbnew.FromMM(0.35))
            default_nc.SetuViaDrill(pcbnew.FromMM(0.15))
    except Exception:
        pass

    fp = pcbnew.FootprintLoad(BGA_LIB_DIR, BGA_FOOTPRINT_NAME)
    if fp is None:
        raise SystemExit(
            f"Failed to load footprint {BGA_FOOTPRINT_NAME} from {BGA_LIB_DIR}"
        )

    fp.SetReference("U1")
    fp.SetValue("XC6SLX25-CSG324")
    fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(50), pcbnew.FromMM(50)))
    board.Add(fp)

    pads = sorted(list(fp.Pads()), key=_sorted_pad_keys)

    # Microvia constraints: satisfy default KiCad DRC annular width (>= 0.10mm).
    # annular = (diameter - drill) / 2
    via_diameter_mm = 0.35
    via_drill_mm = 0.15

    tp_positions = _gen_testpoint_positions(
        x0_mm=0,
        y0_mm=0,
        x1_mm=260,
        y1_mm=260,
        per_side=82,  # 4*82 - 4 corners = 324 unique points
        inset_mm=12,
    )
    if len(tp_positions) != 324:
        raise SystemExit(f"Expected 324 testpoint positions, got {len(tp_positions)}")

    # Nets: connect each BGA pad to a perimeter testpoint (2-pin net).
    for idx, (pad, (tx, ty, rot)) in enumerate(zip(pads, tp_positions), start=1):
        pad_number = pad.GetNumber()
        net_name = f"U1_{pad_number}"
        net = _ensure_net(board, net_name)
        pad.SetNet(net)

        # Add a via-in-pad microvia so FreeRouting has a viable "escape" via type.
        pos = pad.GetPosition()
        via = pcbnew.PCB_VIA(board)
        via.SetPosition(pos)
        via.SetNet(net)
        via.SetWidth(pcbnew.FromMM(via_diameter_mm))
        via.SetDrill(pcbnew.FromMM(via_drill_mm))
        via.SetViaType(pcbnew.VIATYPE_MICROVIA)
        via.SetLayerPair(pcbnew.F_Cu, pcbnew.In1_Cu)
        board.Add(via)
        _make_layer_anchor(board, net=net, pos=pos, layer=pcbnew.In1_Cu)

        # Seed additional adjacent-layer microvia types (1-2 and 2-3) on the first net,
        # so KiCad exports them into the DSN `(structure (via ...))` list. FreeRouting
        # can only use via types that appear there.
        if idx == 1:
            # Avoid stacked/coincident drills (KiCad DRC flags this as `holes_co_located`)
            # by offsetting the seed vias and connecting them with short inner-layer stubs.
            off = pcbnew.FromMM(1.0)
            pos12 = pcbnew.VECTOR2I(pos.x - off, pos.y)
            pos23 = pcbnew.VECTOR2I(pos.x - off, pos.y - off)

            via12 = pcbnew.PCB_VIA(board)
            via12.SetPosition(pos12)
            via12.SetNet(net)
            via12.SetWidth(pcbnew.FromMM(via_diameter_mm))
            via12.SetDrill(pcbnew.FromMM(via_drill_mm))
            via12.SetViaType(pcbnew.VIATYPE_MICROVIA)
            via12.SetLayerPair(pcbnew.In1_Cu, pcbnew.In2_Cu)
            board.Add(via12)

            seg_in1 = pcbnew.PCB_TRACK(board)
            seg_in1.SetStart(pos)
            seg_in1.SetEnd(pos12)
            seg_in1.SetLayer(pcbnew.In1_Cu)
            seg_in1.SetWidth(pcbnew.FromMM(0.10))
            seg_in1.SetNet(net)
            board.Add(seg_in1)

            via23 = pcbnew.PCB_VIA(board)
            via23.SetPosition(pos23)
            via23.SetNet(net)
            via23.SetWidth(pcbnew.FromMM(via_diameter_mm))
            via23.SetDrill(pcbnew.FromMM(via_drill_mm))
            via23.SetViaType(pcbnew.VIATYPE_MICROVIA)
            via23.SetLayerPair(pcbnew.In2_Cu, pcbnew.B_Cu)
            board.Add(via23)

            seg_in2 = pcbnew.PCB_TRACK(board)
            seg_in2.SetStart(pos12)
            seg_in2.SetEnd(pos23)
            seg_in2.SetLayer(pcbnew.In2_Cu)
            seg_in2.SetWidth(pcbnew.FromMM(0.10))
            seg_in2.SetNet(net)
            board.Add(seg_in2)

            _make_layer_anchor(board, net=net, pos=pos23, layer=pcbnew.B_Cu)

        tp = pcbnew.FootprintLoad(TP_LIB_DIR, TP_FOOTPRINT_NAME)
        if tp is None:
            raise SystemExit(f"Failed to load testpoint {TP_FOOTPRINT_NAME} from {TP_LIB_DIR}")
        _strip_footprint_graphics(tp)
        # Also move ref/value texts off silkscreen to avoid DRC overlaps.
        try:
            tp.Reference().SetLayer(pcbnew.Dwgs_User)
            tp.Value().SetLayer(pcbnew.Dwgs_User)
        except Exception:
            pass
        tp.SetReference(f"TP{idx}")
        tp.SetValue(pad_number)
        tp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(tx), pcbnew.FromMM(ty)))
        tp.SetOrientationDegrees(rot)
        for tpad in tp.Pads():
            tpad.SetNet(net)
        board.Add(tp)

    # Large outline around footprint with margin.
    _add_rect_outline(board, x0_mm=0, y0_mm=0, x1_mm=260, y1_mm=260)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    board.Save(str(out_path))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip())
        return 2
    generate_board(Path(argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
