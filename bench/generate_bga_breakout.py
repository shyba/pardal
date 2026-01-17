#!/usr/bin/env python3
"""Generate a BGA breakout routing fixture (4-layer) using KiCad 9 pcbnew.

This is a synthetic benchmark board used to compare:
- FreeRouting (Specctra DSN/SES)
- pardal's Rust router prototype (grid-based)

The generator:
- Loads a KiCad library BGA footprint from `Package_BGA.pretty`
- Connects each ball/pad to a perimeter testpoint pad (2-pin net per pad)
- Adds a via-in-pad microvia (F.Cu -> In1.Cu) on every BGA pad (HDI-ish escape)
- Seeds additional microvia types so KiCad exports them into DSN via-structure

Run inside KiCad 9's Python environment (docker recommended):
  docker run --rm -v "$PWD:/work" -w /work kicad/kicad:9.0.6-full \\
    python3 /work/pardal-pcb/bench/generate_bga_breakout.py \\
      --bga BGA-324_15.0x15.0mm_Layout18x18_P0.8mm_Ball0.5mm_Pad0.4mm_NSMD \\
      --out /work/pardal-pcb/bench/bga324/bga324_breakout.kicad_pcb
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pcbnew


BGA_LIB_DIR = "/usr/share/kicad/footprints/Package_BGA.pretty"
TP_LIB_DIR = "/usr/share/kicad/footprints/TestPoint.pretty"


def _add_rect_outline(
    board: pcbnew.BOARD, *, x0_mm: float, y0_mm: float, x1_mm: float, y1_mm: float
) -> None:
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
    num = str(pad.GetNumber() or "")
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
    for x in xs:
        pos.append((x, y0_mm + inset_mm, 0.0))
    for y in ys[1:]:
        pos.append((x1_mm - inset_mm, y, 90.0))
    for x in reversed(xs[:-1]):
        pos.append((x, y1_mm - inset_mm, 180.0))
    for y in reversed(ys[1:-1]):
        pos.append((x0_mm + inset_mm, y, 270.0))
    return pos


def _strip_footprint_graphics(fp: pcbnew.FOOTPRINT) -> None:
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
            item.SetLayer(pcbnew.Dwgs_User)


def _make_layer_anchor(
    board: pcbnew.BOARD, *, net: pcbnew.NETINFO_ITEM, pos: pcbnew.VECTOR2I, layer: int
) -> None:
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


def generate_board(
    *,
    out_path: Path,
    bga_footprint_name: str,
    tp_footprint_name: str = "TestPoint_Pad_1.0x1.0mm",
    board_size_mm: float | None = None,
    inset_mm: float = 14.0,
) -> None:
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(4)

    # HDI-ish defaults (mirrors fpga_large fixture).
    ds = board.GetDesignSettings()
    ds.m_TrackMinWidth = pcbnew.FromMM(0.10)
    ds.m_MinClearance = pcbnew.FromMM(0.10)
    ds.m_HoleClearance = pcbnew.FromMM(0.10)
    ds.m_HoleToHoleMin = pcbnew.FromMM(0.10)
    ds.m_ViasMinAnnularWidth = pcbnew.FromMM(0.10)
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

    # Also set the "Default" netclass so KiCad's exporter and our extractor agree on sizes.
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

    bga = pcbnew.FootprintLoad(BGA_LIB_DIR, bga_footprint_name)
    if bga is None:
        raise SystemExit(f"Failed to load BGA footprint {bga_footprint_name} from {BGA_LIB_DIR}")

    bga.SetReference("U1")
    bga.SetValue(bga_footprint_name)
    bga.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(60), pcbnew.FromMM(60)))
    board.Add(bga)

    pads = sorted(list(bga.Pads()), key=_sorted_pad_keys)
    n_pads = len(pads)
    if n_pads < 4:
        raise SystemExit(f"Footprint has too few pads: {n_pads}")
    per_side = (n_pads + 4) // 4
    if 4 * per_side - 4 != n_pads:
        raise SystemExit(
            f"Pad count {n_pads} cannot be mapped to perimeter points (needs N=4*k-4)."
        )

    # Choose a board size that keeps testpoints reasonably spaced.
    # Require ~2.0mm pitch between points along the edge.
    if board_size_mm is None:
        pitch_mm = 2.0
        board_size_mm = max(260.0, 2 * inset_mm + pitch_mm * (per_side - 1))
        board_size_mm = float(int(board_size_mm + 0.5))

    tp_positions = _gen_testpoint_positions(
        x0_mm=0.0,
        y0_mm=0.0,
        x1_mm=board_size_mm,
        y1_mm=board_size_mm,
        per_side=per_side,
        inset_mm=inset_mm,
    )
    if len(tp_positions) != n_pads:
        raise SystemExit(f"Expected {n_pads} testpoint positions, got {len(tp_positions)}")

    via_diameter_mm = 0.35
    via_drill_mm = 0.15

    for idx, (pad, (tx, ty, rot)) in enumerate(zip(pads, tp_positions), start=1):
        pad_number = str(pad.GetNumber() or str(idx))
        net_name = f"U1_{pad_number}"
        net = _ensure_net(board, net_name)
        pad.SetNet(net)

        # Via-in-pad microvia to enable dense escape routing.
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

        # Seed via types (1-2 and 2-3) on the first net so DSN contains all microvia types.
        if idx == 1:
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

        tp = pcbnew.FootprintLoad(TP_LIB_DIR, tp_footprint_name)
        if tp is None:
            raise SystemExit(f"Failed to load testpoint {tp_footprint_name} from {TP_LIB_DIR}")
        _strip_footprint_graphics(tp)
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

    _add_rect_outline(board, x0_mm=0.0, y0_mm=0.0, x1_mm=board_size_mm, y1_mm=board_size_mm)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    board.Save(str(out_path))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bga", required=True, help="Footprint name (no .kicad_mod) in Package_BGA.pretty")
    ap.add_argument("--out", type=Path, required=True, help="Output .kicad_pcb path")
    ap.add_argument("--tp", default="TestPoint_Pad_1.0x1.0mm", help="TestPoint footprint name")
    ap.add_argument("--board-size-mm", type=float, default=None, help="Override board size (square)")
    ap.add_argument("--inset-mm", type=float, default=14.0, help="Inset from board edge for testpoints")
    args = ap.parse_args()

    generate_board(
        out_path=args.out,
        bga_footprint_name=str(args.bga),
        tp_footprint_name=str(args.tp),
        board_size_mm=args.board_size_mm,
        inset_mm=float(args.inset_mm),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
