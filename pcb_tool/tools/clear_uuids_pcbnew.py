#!/usr/bin/env python3
"""Clear board items by UUID from a KiCad PCB.

This enables DRC-driven local ripup by deleting only the exact offending items
reported by KiCad DRC (which includes UUIDs for many items).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pcbnew  # type: ignore


def _read_lines(path: Path) -> list[str]:
    out: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pcb", required=True, help="Input .kicad_pcb")
    ap.add_argument("--out", required=True, help="Output .kicad_pcb")
    ap.add_argument("--uuids-file", required=True, help="File with UUIDs to delete (one per line).")
    ap.add_argument("--out-nets-file", default=None, help="Optional output file of nets that were affected.")
    ap.add_argument(
        "--tracks-only",
        action="store_true",
        help="Only delete track segments (preserve vias), even if UUID matches.",
    )
    args = ap.parse_args()

    uuids = set(_read_lines(Path(args.uuids_file)))
    board = pcbnew.LoadBoard(str(Path(args.pcb)))

    via_type = getattr(pcbnew, "PCB_VIA", None) or getattr(pcbnew, "VIA", None)
    touched_nets: set[str] = set()
    removed = 0

    for u in uuids:
        try:
            kiid = pcbnew.KIID(u)
            item = board.GetItem(kiid)
        except Exception:
            item = None
        if item is None:
            continue
        if args.tracks_only:
            if via_type is not None and isinstance(item, via_type):
                continue
            if str(getattr(item, "GetClass", lambda: "")()) in {"VIA", "PCB_VIA"}:
                continue
        n = _net_name(item)
        if n:
            touched_nets.add(n)
        try:
            board.Remove(item)
            removed += 1
        except Exception:
            continue

    pcbnew.SaveBoard(str(Path(args.out)), board)
    if args.out_nets_file:
        Path(args.out_nets_file).write_text("\n".join(sorted(touched_nets)) + ("\n" if touched_nets else ""), encoding="utf-8")
    print(f"removed={removed} touched_nets={len(touched_nets)}")


if __name__ == "__main__":
    main()
