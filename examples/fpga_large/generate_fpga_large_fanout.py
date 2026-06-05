#!/usr/bin/env python3
"""Generate a 4-layer BGA-324 "fanout" fixture with 0 DRC issues.

Each BGA pad gets:
- a unique net name (`U1_<pad_number>`)
- a microvia placed at the pad center (F.Cu -> In1.Cu)
- a tiny "landing pad" on In1.Cu at the same coordinate (so the microvia is not
  flagged as dangling by KiCad DRC)

This creates a board where every ball is escaped to In1.Cu without requiring a
full board-wide autoroute.

Run inside KiCad 9's Python environment:
  docker run --rm -v "$PWD:/work" -w /work kicad/kicad:9.0.6-full \\
    python3 examples/fpga_large/generate_fpga_large_fanout.py \\
      examples/fpga_large/fpga_large_csg324_fanout.kicad_pcb
"""

from __future__ import annotations

import sys
from pathlib import Path

import pcbnew


BGA_LIB_DIR = "/usr/share/kicad/footprints/Package_BGA.pretty"
BGA_FOOTPRINT_NAME = "Xilinx_CSG324"


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
    num = pad.GetNumber()
    letters = "".join([c for c in num if c.isalpha()])
    digits = "".join([c for c in num if c.isdigit()])
    return (len(letters), letters, int(digits) if digits else 0, num)


def _make_in1_anchor(board: pcbnew.BOARD, *, net: pcbnew.NETINFO_ITEM, pos: pcbnew.VECTOR2I) -> None:
    """Add a tiny copper-filled circle on In1.Cu to prevent 'via_dangling' DRC warnings."""
    radius_mm = 0.15
    shape = pcbnew.PCB_SHAPE(board)
    shape.SetShape(pcbnew.SHAPE_T_CIRCLE)
    shape.SetLayer(pcbnew.In1_Cu)
    shape.SetNet(net)
    shape.SetFilled(True)
    shape.SetWidth(pcbnew.FromMM(0.05))
    shape.SetStart(pos)
    shape.SetEnd(pcbnew.VECTOR2I(pos.x + pcbnew.FromMM(radius_mm), pos.y))
    board.Add(shape)


def generate_board(out_path: Path) -> None:
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(4)

    bga = pcbnew.FootprintLoad(BGA_LIB_DIR, BGA_FOOTPRINT_NAME)
    if bga is None:
        raise SystemExit(
            f"Failed to load footprint {BGA_FOOTPRINT_NAME} from {BGA_LIB_DIR}"
        )

    bga.SetReference("U1")
    bga.SetValue("XC6SLX25-CSG324")
    bga.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(50), pcbnew.FromMM(50)))
    try:
        bga.Reference().SetLayer(pcbnew.Dwgs_User)
        bga.Value().SetLayer(pcbnew.Dwgs_User)
    except Exception:
        pass
    board.Add(bga)

    # Microvia constraints: satisfy default KiCad DRC annular width (>= 0.10mm).
    # annular = (diameter - drill) / 2
    via_diameter_mm = 0.35
    via_drill_mm = 0.15

    for pad in sorted(list(bga.Pads()), key=_sorted_pad_keys):
        pad_number = pad.GetNumber()
        net = _ensure_net(board, f"U1_{pad_number}")
        pad.SetNet(net)

        pos = pad.GetPosition()

        via = pcbnew.PCB_VIA(board)
        via.SetPosition(pos)
        via.SetNet(net)
        via.SetWidth(pcbnew.FromMM(via_diameter_mm))
        via.SetDrill(pcbnew.FromMM(via_drill_mm))
        via.SetViaType(pcbnew.VIATYPE_MICROVIA)
        via.SetLayerPair(pcbnew.F_Cu, pcbnew.In1_Cu)
        board.Add(via)
        _make_in1_anchor(board, net=net, pos=pos)

    _add_rect_outline(board, x0_mm=0, y0_mm=0, x1_mm=100, y1_mm=100)
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
