#!/usr/bin/env python3
"""Clear tracks/vias inside a window from a KiCad PCB.

This is intended for DRC-driven local ripup/repair loops where deleting an entire
net is too destructive.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pcbnew  # type: ignore


def _read_nets_file(path: Path | None) -> set[str] | None:
    if path is None:
        return None
    nets: set[str] = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        nets.add(line)
    return nets


def _net_name(item: pcbnew.BOARD_ITEM) -> str:
    try:
        n = item.GetNetname()
        if n:
            return str(n)
    except Exception:
        pass
    try:
        net = item.GetNet()
        if net is not None:
            n2 = net.GetNetname()
            if n2:
                return str(n2)
    except Exception:
        pass
    return ""


def _mm_to_nm(v: float) -> int:
    return int(round(v * 1_000_000.0))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pcb", required=True, help="Input .kicad_pcb")
    ap.add_argument("--out", required=True, help="Output .kicad_pcb")
    ap.add_argument(
        "--bbox",
        required=True,
        help="Window bbox as 'xmin,ymin,xmax,ymax' in mm (board coordinate system).",
    )
    ap.add_argument(
        "--nets-file",
        default=None,
        help="Optional list of net names to clear; if omitted, clears all nets.",
    )
    ap.add_argument(
        "--out-nets-file",
        default=None,
        help="Optional output file to write net names that had items deleted (one per line).",
    )
    ap.add_argument(
        "--tracks-only",
        action="store_true",
        help="Only delete TRACK segments (preserve VIAs). Recommended for via-in-pad seeds.",
    )
    args = ap.parse_args()

    in_pcb = Path(args.pcb)
    out_pcb = Path(args.out)
    bbox = [float(x) for x in str(args.bbox).split(",")]
    if len(bbox) != 4:
        raise SystemExit("--bbox must be xmin,ymin,xmax,ymax")
    xmin, ymin, xmax, ymax = bbox
    xmin_nm, ymin_nm, xmax_nm, ymax_nm = map(_mm_to_nm, (xmin, ymin, xmax, ymax))

    nets = _read_nets_file(Path(args.nets_file) if args.nets_file else None)
    touched_nets: set[str] = set()

    board = pcbnew.LoadBoard(str(in_pcb))
    to_delete: list[pcbnew.BOARD_ITEM] = []

    # Tracks() includes vias; use type checks to control deletion.
    via_type = getattr(pcbnew, "PCB_VIA", None) or getattr(pcbnew, "VIA", None)
    for t in list(board.GetTracks()):
        if args.tracks_only:
            if via_type is not None and isinstance(t, via_type):
                continue
            if str(getattr(t, "GetClass", lambda: "")()) in {"VIA", "PCB_VIA"}:
                continue
        n = _net_name(t)
        if nets is not None and n not in nets:
            continue
        bb = t.GetBoundingBox()
        if bb.GetRight() < xmin_nm or bb.GetLeft() > xmax_nm or bb.GetBottom() < ymin_nm or bb.GetTop() > ymax_nm:
            continue
        to_delete.append(t)
        if n:
            touched_nets.add(n)

    for item in to_delete:
        board.Remove(item)

    pcbnew.SaveBoard(str(out_pcb), board)
    if args.out_nets_file:
        Path(args.out_nets_file).write_text("\n".join(sorted(touched_nets)) + ("\n" if touched_nets else ""), encoding="utf-8")


if __name__ == "__main__":
    main()
