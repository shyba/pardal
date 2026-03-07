#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
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
    clear_nets_file: Path | None = None,
    clear_tracks_only: bool = False,
) -> None:
    payload: dict[str, Any] = json.loads(routes_json.read_text(encoding="utf-8", errors="replace"))
    tracks = payload.get("tracks", []) or []
    vias = payload.get("vias", []) or []
    # Optional endpoint snapping map: {track_uuid: {start_uuid, goal_uuid}} or a
    # global net->(uuid) mapping. For now we support direct uuid lookup on each
    # track record.

    board = pcbnew.LoadBoard(str(in_pcb))
    # Keep endpoint snapping conservative by default. Large snapping windows can
    # move dense BGA escape segments enough to create shorts after apply.
    try:
        snap_max_mm = float(os.environ.get("PARDAL_APPLY_SNAP_MAX_MM", "0.03"))
    except Exception:
        snap_max_mm = 0.03
    if snap_max_mm < 0.0:
        snap_max_mm = 0.0

    def _tracks_snapshot() -> list[Any]:
        # KiCad SWIG bindings differ across builds; prefer Tracks() iteration.
        try:
            return list(board.Tracks())
        except Exception:
            return list(board.GetTracks())

    tracks_before = _tracks_snapshot()

    clear_nets: set[str] = set()
    if clear_nets_file is not None and clear_nets_file.exists():
        clear_nets = {
            ln.strip()
            for ln in clear_nets_file.read_text(encoding="utf-8", errors="replace").splitlines()
            if ln.strip()
        }

    if clear_nets:
        # Rip up existing routing for selected nets so this apply step can replace
        # stale geometry instead of stacking overlapping/shorting segments.
        for it in tracks_before:
            try:
                net_name = str(it.GetNetname() or "")
            except Exception:
                net_name = ""
            if net_name not in clear_nets:
                continue
            if isinstance(it, pcbnew.PCB_VIA) and clear_tracks_only:
                continue
            board.Remove(it)

    def _via_rank(vt: str) -> int:
        # Prefer "stronger" vias that cover more layers.
        if vt == "through":
            return 3
        if vt in ("blind", "buried"):
            return 2
        if vt == "micro":
            return 1
        return 0

    def _net_code(it_or_netinfo) -> int:
        try:
            return int(it_or_netinfo.GetNetCode())
        except Exception:
            return 0

    def _net_name_from_via(it: pcbnew.PCB_VIA) -> str:
        try:
            return str(it.GetNetname() or "")
        except Exception:
            return ""

    existing_vias: dict[tuple[str, int, int], pcbnew.PCB_VIA] = {}
    for it in tracks_before:
        if clear_nets:
            # Vias on cleared nets are removed unless --clear-tracks-only was set.
            try:
                net_name = str(it.GetNetname() or "")
            except Exception:
                net_name = ""
            if net_name in clear_nets and (not clear_tracks_only):
                continue
        if isinstance(it, pcbnew.PCB_VIA):
            pos = it.GetPosition()
            code = _net_code(it)
            name = _net_name_from_via(it)
            if code > 0:
                existing_vias[(f"code:{code}", int(pos.x), int(pos.y))] = it
            if name:
                existing_vias[(f"name:{name}", int(pos.x), int(pos.y))] = it

    def _find_pad_center(uuid_str: str, *, layer: int) -> pcbnew.VECTOR2I | None:
        if not uuid_str:
            return None
        try:
            u = pcbnew.KIID(uuid_str)
        except Exception:
            return None
        it = board.GetItem(u)
        if it is None:
            return None
        if not isinstance(it, pcbnew.PAD):
            return None
        try:
            if not it.IsOnLayer(layer):
                return None
        except Exception:
            return None
        try:
            return it.GetPosition()
        except Exception:
            return None

    for t in tracks:
        net_name = str(t["net"])
        net_info = board.FindNet(net_name)
        if net_info is None:
            continue
        code = _net_code(net_info)
        code_key = f"code:{code}" if code > 0 else ""
        name_key = f"name:{net_name}"
        layer = _pcb_layer(str(t["layer"]))
        width_mm = float(t["width_mm"])
        (sx, sy) = t["start_mm"]
        (ex, ey) = t["end_mm"]
        s_uuid = str(t.get("start_uuid") or "")
        e_uuid = str(t.get("end_uuid") or "")
        s_pos = _find_pad_center(s_uuid, layer=layer)
        e_pos = _find_pad_center(e_uuid, layer=layer)
        track = pcbnew.PCB_TRACK(board)
        # Optional snapping: only snap when very close. This preserves intended
        # routed geometry and avoids introducing post-apply shorts.
        start = pcbnew.VECTOR2I(pcbnew.FromMM(float(sx)), pcbnew.FromMM(float(sy)))
        end = pcbnew.VECTOR2I(pcbnew.FromMM(float(ex)), pcbnew.FromMM(float(ey)))
        if s_pos is not None:
            dx = abs(pcbnew.ToMM(int(s_pos.x - start.x)))
            dy = abs(pcbnew.ToMM(int(s_pos.y - start.y)))
            if dx <= snap_max_mm and dy <= snap_max_mm:
                start = s_pos
        if e_pos is not None:
            dx = abs(pcbnew.ToMM(int(e_pos.x - end.x)))
            dy = abs(pcbnew.ToMM(int(e_pos.y - end.y)))
            if dx <= snap_max_mm and dy <= snap_max_mm:
                end = e_pos
        track.SetStart(start)
        track.SetEnd(end)
        track.SetLayer(layer)
        track.SetWidth(pcbnew.FromMM(width_mm))
        track.SetNet(net_info)
        board.Add(track)

    for v in vias:
        net_name = str(v["net"])
        net_info = board.FindNet(net_name)
        if net_info is None:
            continue
        code = _net_code(net_info)
        code_key = f"code:{code}" if code > 0 else ""
        name_key = f"name:{net_name}"
        (x, y) = v["pos_mm"]
        size_mm = float(v["size_mm"])
        drill_mm = float(v["drill_mm"])
        via_type = str(v.get("via_type", "through"))
        layers = list(v.get("layers", []))
        pos = pcbnew.VECTOR2I(pcbnew.FromMM(float(x)), pcbnew.FromMM(float(y)))
        px = int(pos.x)
        py = int(pos.y)
        pcb_via = None
        created_new = False
        if code_key:
            candidate = existing_vias.get((code_key, px, py))
            if candidate is not None:
                # Never merge across nets: a stale/mismatched net here is
                # catastrophic (creates shorts).
                if str(candidate.GetNetname() or "") == net_name:
                    pcb_via = candidate
        if pcb_via is None:
            candidate = existing_vias.get((name_key, px, py))
            if candidate is not None and str(candidate.GetNetname() or "") == net_name:
                pcb_via = candidate
        if pcb_via is None:
            pcb_via = pcbnew.PCB_VIA(board)
            pcb_via.SetPosition(pos)
            pcb_via.SetNet(net_info)
            board.Add(pcb_via)
            created_new = True
            if code_key:
                existing_vias[(code_key, px, py)] = pcb_via
            existing_vias[(name_key, px, py)] = pcb_via

        # Keep pre-existing vias geometry-stable. Upgrading existing in-pad
        # stacks to "stronger" routed geometry can explode hole/short DRC on
        # dense BGAs. New vias still get full requested geometry below.
        if created_new:
            try:
                try:
                    cur_w = pcbnew.ToMM(int(pcb_via.GetWidth(int(pcb_via.TopLayer()))))
                except Exception:
                    cur_w = pcbnew.ToMM(int(pcb_via.GetWidth(int(pcbnew.F_Cu))))
            except Exception:
                cur_w = 0.0
            try:
                cur_dr = pcbnew.ToMM(int(pcb_via.GetDrill()))
            except Exception:
                cur_dr = 0.0
            if size_mm > cur_w:
                pcb_via.SetWidth(pcbnew.FromMM(size_mm))
            if drill_mm > cur_dr:
                pcb_via.SetDrill(pcbnew.FromMM(drill_mm))

        # Only set type/span when creating a new via. If we merged into an
        # existing via, changing its type/layer-pair can expand copper onto
        # additional layers and create shorts elsewhere (the fixture may rely on
        # the original via type for clearance).
        if created_new and layers:
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
                # Through vias don't need a layer pair.
        elif created_new:
            pcb_via.SetViaType(pcbnew.VIATYPE_THROUGH)

    board.Save(str(out_pcb))
    _copy_project_files(in_pcb, out_pcb)


def main() -> int:
    ap = argparse.ArgumentParser(description="Apply routed tracks/vias to a KiCad PCB using pcbnew.")
    ap.add_argument("--in", dest="in_pcb", type=Path, required=True)
    ap.add_argument("--out", dest="out_pcb", type=Path, required=True)
    ap.add_argument("--routes", dest="routes_json", type=Path, required=True)
    ap.add_argument(
        "--clear-nets-file",
        type=Path,
        default=None,
        help="Optional file with one net name per line to clear before applying routes.",
    )
    ap.add_argument(
        "--clear-tracks-only",
        action="store_true",
        help="When clearing nets, delete only tracks/arcs and keep vias.",
    )
    args = ap.parse_args()

    apply_routes(
        in_pcb=args.in_pcb,
        out_pcb=args.out_pcb,
        routes_json=args.routes_json,
        clear_nets_file=args.clear_nets_file,
        clear_tracks_only=bool(args.clear_tracks_only),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
