#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pcbnew


def _get_layer_map() -> dict[str, int]:
    layer_map = {
        "F.Cu": pcbnew.F_Cu,
        "B.Cu": pcbnew.B_Cu,
    }
    for i in range(1, 31):
        layer_map[f"In{i}.Cu"] = getattr(pcbnew, f"In{i}_Cu", pcbnew.F_Cu)
    return layer_map


def _pcb_layer(layer_name: str) -> int:
    return _get_layer_map().get(layer_name, pcbnew.F_Cu)


def _copy_project_files(in_pcb: Path, out_pcb: Path) -> None:
    if in_pcb == out_pcb:
        return
    for ext in (".kicad_pro", ".kicad_prl"):
        src = in_pcb.with_suffix(ext)
        dst = out_pcb.with_suffix(ext)
        if src.exists():
            dst.write_text(src.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")


def apply_routes(
    *,
    in_pcb: Path,
    out_pcb: Path,
    routes_json: Path,
) -> None:
    payload: dict[str, Any] = json.loads(routes_json.read_text(encoding="utf-8", errors="replace"))
    tracks = payload.get("tracks", []) or []
    vias = payload.get("vias", []) or []

    board = pcbnew.LoadBoard(str(in_pcb))

    for t in tracks:
        net_name = str(t["net"])
        net_info = board.FindNet(net_name)
        if net_info is None:
            continue
        layer = _pcb_layer(str(t["layer"]))
        width_mm = float(t["width_mm"])
        (sx, sy) = t["start_mm"]
        (ex, ey) = t["end_mm"]
        track = pcbnew.PCB_TRACK(board)
        track.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(float(sx)), pcbnew.FromMM(float(sy))))
        track.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(float(ex)), pcbnew.FromMM(float(ey))))
        track.SetLayer(layer)
        track.SetWidth(pcbnew.FromMM(width_mm))
        track.SetNet(net_info)
        board.Add(track)

    for v in vias:
        net_name = str(v["net"])
        net_info = board.FindNet(net_name)
        if net_info is None:
            continue
        (x, y) = v["pos_mm"]
        size_mm = float(v["size_mm"])
        drill_mm = float(v["drill_mm"])
        via_type = str(v.get("via_type", "through"))
        layers = list(v.get("layers", []))

        pcb_via = pcbnew.PCB_VIA(board)
        pcb_via.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(float(x)), pcbnew.FromMM(float(y))))
        pcb_via.SetWidth(pcbnew.FromMM(size_mm))
        pcb_via.SetDrill(pcbnew.FromMM(drill_mm))
        pcb_via.SetNet(net_info)

        if layers:
            layer0 = _pcb_layer(str(layers[0]))
            layer1 = _pcb_layer(str(layers[-1]))
            if via_type == "micro":
                pcb_via.SetViaType(pcbnew.VIATYPE_MICROVIA)
                pcb_via.SetLayerPair(layer0, layer1)
            elif via_type in ("blind", "buried"):
                pcb_via.SetViaType(pcbnew.VIATYPE_BLIND_BURIED)
                pcb_via.SetLayerPair(layer0, layer1)
            else:
                pcb_via.SetViaType(pcbnew.VIATYPE_THROUGH)
        else:
            pcb_via.SetViaType(pcbnew.VIATYPE_THROUGH)

        board.Add(pcb_via)

    board.Save(str(out_pcb))
    _copy_project_files(in_pcb, out_pcb)


def main() -> int:
    ap = argparse.ArgumentParser(description="Apply routed tracks/vias to a KiCad PCB using pcbnew.")
    ap.add_argument("--in", dest="in_pcb", type=Path, required=True)
    ap.add_argument("--out", dest="out_pcb", type=Path, required=True)
    ap.add_argument("--routes", dest="routes_json", type=Path, required=True)
    args = ap.parse_args()

    apply_routes(in_pcb=args.in_pcb, out_pcb=args.out_pcb, routes_json=args.routes_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

