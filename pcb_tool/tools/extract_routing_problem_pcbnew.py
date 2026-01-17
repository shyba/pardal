#!/usr/bin/env python3
"""Extract a compact routing problem from a KiCad PCB using pcbnew (KiCad 9).

This script is intended to run inside KiCad's bundled Python environment (e.g. the
`kicad/kicad:9.x-full` docker image). It produces a lightweight JSON input for the
Rust router backend without embedding a full raster grid.

The current extractor is optimized for the `fpga_large` fixture:
- Treats copper pads as circular obstacles (radius = max(pad_w, pad_h)/2 + inflate).
- Builds per-net start/goal points from U1 BGA pads and TP* testpoint pads.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pcbnew


def _copper_layer_ids(board: pcbnew.BOARD) -> List[int]:
    count = int(board.GetCopperLayerCount())
    if count < 2:
        return [pcbnew.F_Cu]
    ids = [pcbnew.F_Cu]
    for i in range(1, count - 1):
        ids.append(getattr(pcbnew, f"In{i}_Cu"))
    ids.append(pcbnew.B_Cu)
    return ids


def _copper_layer_names(board: pcbnew.BOARD) -> List[str]:
    return [board.GetLayerName(lid) for lid in _copper_layer_ids(board)]


def _layer_index_by_id(board: pcbnew.BOARD) -> Dict[int, int]:
    ids = _copper_layer_ids(board)
    return {lid: idx for idx, lid in enumerate(ids)}


def _to_mm(v: int) -> float:
    return float(pcbnew.ToMM(v))


def _netclass_defaults(board: pcbnew.BOARD) -> Tuple[float, float, float, float, float, float]:
    """Return (track_width_mm, clearance_mm, via_diam_mm, via_drill_mm, uvia_diam_mm, uvia_drill_mm)."""
    try:
        nc = board.GetAllNetClasses().get("Default")
    except Exception:
        nc = None
    if nc is None:
        ds = board.GetDesignSettings()
        track = _to_mm(int(getattr(ds, "m_TrackMinWidth", pcbnew.FromMM(0.10))))
        clr = _to_mm(int(getattr(ds, "m_MinClearance", pcbnew.FromMM(0.10))))
        via_d = _to_mm(int(getattr(ds, "m_ViasMinSize", pcbnew.FromMM(0.40))))
        via_dr = _to_mm(int(getattr(ds, "m_MinThroughDrill", pcbnew.FromMM(0.20))))
        uvia_d = _to_mm(int(getattr(ds, "m_MicroViasMinSize", pcbnew.FromMM(0.35))))
        uvia_dr = _to_mm(int(getattr(ds, "m_MicroViasMinDrill", pcbnew.FromMM(0.15))))
        return track, clr, via_d, via_dr, uvia_d, uvia_dr
    try:
        uvia_d = _to_mm(int(nc.GetuViaDiameter()))
        uvia_dr = _to_mm(int(nc.GetuViaDrill()))
    except Exception:
        uvia_d = _to_mm(int(nc.GetViaDiameter()))
        uvia_dr = _to_mm(int(nc.GetViaDrill()))
    return (
        _to_mm(int(nc.GetTrackWidth())),
        _to_mm(int(nc.GetClearance())),
        _to_mm(int(nc.GetViaDiameter())),
        _to_mm(int(nc.GetViaDrill())),
        uvia_d,
        uvia_dr,
    )


def _grid_xy(pos: pcbnew.VECTOR2I, resolution_mm: float) -> Tuple[int, int]:
    x_mm = _to_mm(int(pos.x))
    y_mm = _to_mm(int(pos.y))
    gx = int(round(x_mm / resolution_mm))
    gy = int(round(y_mm / resolution_mm))
    return gx, gy


def _grid_r(radius_mm: float, resolution_mm: float) -> int:
    if radius_mm <= 0.0:
        return 0
    # Use ceiling to avoid under-approximating keepouts; otherwise the router can
    # "thread the needle" through cells that still violate KiCad DRC after conversion
    # back to true geometry.
    import math

    return int(math.ceil(radius_mm / resolution_mm))


def _pad_layers(pad: pcbnew.PAD, copper_layer_ids: Iterable[int]) -> List[int]:
    layers: List[int] = []
    for lid in copper_layer_ids:
        try:
            if pad.IsOnLayer(lid):
                layers.append(int(lid))
        except Exception:
            continue
    return layers


def _dist_mm(a: pcbnew.VECTOR2I, b: pcbnew.VECTOR2I) -> float:
    dx = _to_mm(int(b.x - a.x))
    dy = _to_mm(int(b.y - a.y))
    return float((dx * dx + dy * dy) ** 0.5)


@dataclass(frozen=True)
class _Circle:
    net_name: str
    net_id: int
    layers: Tuple[int, ...]
    x: int
    y: int
    r: int


def extract_problem(
    *,
    pcb_path: Path,
    out_json: Path,
    resolution_mm: float,
    inflate_mm: Optional[float] = None,
) -> None:
    board = pcbnew.LoadBoard(str(pcb_path))
    layer_ids = _copper_layer_ids(board)
    layer_names = _copper_layer_names(board)
    layer_index = _layer_index_by_id(board)

    track_w_mm, clr_mm, via_d_mm, via_dr_mm, uvia_d_mm, uvia_dr_mm = _netclass_defaults(board)
    if inflate_mm is None:
        inflate_mm = clr_mm + track_w_mm / 2.0

    def _net_pads() -> Dict[str, List[pcbnew.PAD]]:
        out: Dict[str, List[pcbnew.PAD]] = {}
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                try:
                    net_name = str(pad.GetNetname())
                except Exception:
                    continue
                if not net_name:
                    continue
                out.setdefault(net_name, []).append(pad)
        return out

    pads_by_net = _net_pads()

    # Net id mapping: stable, dense ids for routing occupancy ownership.
    #
    # Primary target: `fpga_large` uses nets named `U1_*` and TP* goals.
    # Fallback: if there are no `U1_*` nets, route small-ish nets by pad connectivity.
    net_names_u1 = sorted([n for n in pads_by_net.keys() if n.startswith("U1_")])
    if net_names_u1:
        net_names = net_names_u1
        use_tp_goals = True
    else:
        use_tp_goals = False
        net_names = sorted(
            [
                n
                for n, pads in pads_by_net.items()
                if 2 <= len(pads) <= 12
            ]
        )
    net_id_by_name: Dict[str, int] = {name: i + 1 for i, name in enumerate(net_names)}

    # Net specs can contain multiple segments per net name (e.g. VCC/GND).
    # Each segment shares the same `net_id` (ownership + obstacles), but has its own endpoints.
    net_specs: List[Tuple[str, int, Tuple[int, int, int], Tuple[int, int, int]]] = []

    if use_tp_goals:
        starts: Dict[str, Tuple[int, int, int]] = {}
        goals: Dict[str, Tuple[int, int, int]] = {}

        # Start points: U1 BGA pads.
        #
        # The `fpga_large` fixture includes a microvia-in-pad connecting F.Cu->In1.Cu
        # for every BGA pad. Starting on F.Cu generally reduces the number of new vias
        # the router must introduce (helpful for DRC and performance).
        u1 = board.FindFootprintByReference("U1")
        if u1 is None:
            raise SystemExit("Failed to find footprint U1 (BGA)")
        for pad in u1.Pads():
            net_name = str(pad.GetNetname())
            if net_name not in net_id_by_name:
                continue
            gx, gy = _grid_xy(pad.GetPosition(), resolution_mm)
            # The BGA breakout fixtures seed a microvia-in-pad (F.Cu->In1.Cu) for every ball.
            # Starting on In1.Cu avoids adding redundant microvias and reduces search on F.Cu
            # where the pad field is dense.
            if "In1.Cu" in layer_names:
                start_layer = "In1.Cu"
            else:
                start_layer = "F.Cu" if "F.Cu" in layer_names else layer_names[0]
            starts[net_name] = (layer_names.index(start_layer), gx, gy)

        # Goal points: TP* pads (prefer F.Cu if present).
        for fp in board.GetFootprints():
            ref = str(fp.GetReference() or "")
            if not ref.startswith("TP"):
                continue
            for pad in fp.Pads():
                net_name = str(pad.GetNetname())
                if net_name not in net_id_by_name:
                    continue
                gx, gy = _grid_xy(pad.GetPosition(), resolution_mm)
                goal_layer = "F.Cu" if "F.Cu" in layer_names else layer_names[0]
                goals[net_name] = (layer_names.index(goal_layer), gx, gy)
    else:
        # Generic fallback: route nets by pad connectivity on a single outer layer.
        default_layer = "F.Cu" if "F.Cu" in layer_names else layer_names[0]
        li = layer_names.index(default_layer)

        def _pad_key(p: pcbnew.PAD) -> Tuple[str, str]:
            return (
                str(p.GetParentFootprint().GetReference() or ""),
                str(p.GetPadName() or ""),
            )

        for net_name in net_names:
            pads = pads_by_net.get(net_name) or []
            if len(pads) < 2:
                continue
            pads_sorted = sorted(pads, key=_pad_key)

            # Build a small minimum spanning tree over pads to avoid long star routes.
            # This helps multi-pin nets like VCC/GND on small boards.
            parent = list(range(len(pads_sorted)))
            rank = [0] * len(pads_sorted)

            def find(x: int) -> int:
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x

            def union(a: int, b: int) -> bool:
                ra, rb = find(a), find(b)
                if ra == rb:
                    return False
                if rank[ra] < rank[rb]:
                    parent[ra] = rb
                elif rank[ra] > rank[rb]:
                    parent[rb] = ra
                else:
                    parent[rb] = ra
                    rank[ra] += 1
                return True

            edges: List[Tuple[int, int, int]] = []
            for i, pa in enumerate(pads_sorted):
                posa = pa.GetPosition()
                for j in range(i + 1, len(pads_sorted)):
                    pb = pads_sorted[j]
                    posb = pb.GetPosition()
                    dx = int(posa.x) - int(posb.x)
                    dy = int(posa.y) - int(posb.y)
                    d2 = dx * dx + dy * dy
                    edges.append((d2, i, j))
            edges.sort(key=lambda t: (t[0], t[1], t[2]))

            used = 0
            for _d2, i, j in edges:
                if union(i, j):
                    ai = pads_sorted[i]
                    bi = pads_sorted[j]
                    ax, ay = _grid_xy(ai.GetPosition(), resolution_mm)
                    bx, by = _grid_xy(bi.GetPosition(), resolution_mm)
                    net_specs.append(
                        (net_name, net_id_by_name[net_name], (li, ax, ay), (li, bx, by))
                    )
                    used += 1
                    if used >= len(pads_sorted) - 1:
                        break

    if use_tp_goals:
        missing = [n for n in net_names if n not in starts or n not in goals]
        if missing:
            raise SystemExit(f"Missing endpoints for {len(missing)} nets (e.g. {missing[:5]})")
        for name in net_names:
            net_specs.append((name, net_id_by_name[name], starts[name], goals[name]))

    if not net_specs:
        raise SystemExit("No nets found to route (net_specs is empty)")

    circles: Dict[Tuple[str, int, int, int, int, int], _Circle] = {}
    existing_vias: List[Dict[str, Any]] = []

    def add_circle(
        *,
        net_name: str,
        net_id: int,
        layers: Iterable[int],
        gx: int,
        gy: int,
        r: int,
    ) -> None:
        if r < 0:
            return
        layer_list = tuple(sorted(set(int(x) for x in layers)))
        for li in layer_list:
            key = (net_name, net_id, li, gx, gy, r)
            circles[key] = _Circle(net_name, net_id, (li,), int(gx), int(gy), int(r))
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            net_name = str(pad.GetNetname())
            if net_name not in net_id_by_name:
                continue
            net_id = int(net_id_by_name[net_name])
            size = pad.GetSize()
            w_mm = _to_mm(int(size.x))
            h_mm = _to_mm(int(size.y))
            radius_mm = 0.5 * max(w_mm, h_mm) + float(inflate_mm)
            gx, gy = _grid_xy(pad.GetPosition(), resolution_mm)
            r = _grid_r(radius_mm, resolution_mm)

            pad_layers = _pad_layers(pad, layer_ids)
            if not pad_layers:
                continue
            layers = tuple(sorted({layer_index[lid] for lid in pad_layers if lid in layer_index}))
            if not layers:
                continue

            for li in layers:
                add_circle(net_name=net_name, net_id=net_id, layers=[li], gx=gx, gy=gy, r=r)

    # Existing copper on inner layers matters for short avoidance (e.g. the fpga_large
    # fixture seeds a tiny filled circle on In1.Cu for every BGA net).
    for item in board.GetTracks():
        try:
            net_name = str(item.GetNetname())
        except Exception:
            continue
        if net_name not in net_id_by_name:
            continue
        net_id = int(net_id_by_name.get(net_name, 0))
        if net_id <= 0:
            continue

        # Vias: stamp across their layer span.
        if isinstance(item, pcbnew.PCB_VIA):
            pos = item.GetPosition()
            gx, gy = _grid_xy(pos, resolution_mm)
            layers_idx: List[int] = []
            try:
                try:
                    size_mm = _to_mm(int(item.GetWidth(int(item.TopLayer()))))
                except Exception:
                    size_mm = via_d_mm
                l0 = int(item.TopLayer())
                l1 = int(item.BottomLayer())
                i0 = layer_index.get(l0)
                i1 = layer_index.get(l1)
                if i0 is not None and i1 is not None:
                    lo, hi = (i0, i1) if i0 <= i1 else (i1, i0)
                    layers_idx = list(range(lo, hi + 1))
            except Exception:
                try:
                    size_mm = _to_mm(int(item.GetWidth(int(pcbnew.F_Cu))))
                except Exception:
                    size_mm = via_d_mm
            if not layers_idx:
                # Fallback: treat as through via spanning all copper layers.
                layers_idx = list(range(len(layer_names)))
            radius_mm = (float(size_mm) / 2.0) + float(inflate_mm)

            add_circle(
                net_name=net_name,
                net_id=net_id,
                layers=layers_idx,
                gx=gx,
                gy=gy,
                r=_grid_r(radius_mm, resolution_mm),
            )
            existing_vias.append(
                {
                    "net": net_name,
                    "net_id": int(net_id),
                    "layers": [int(li) for li in layers_idx],
                    "center": {"x": int(gx), "y": int(gy)},
                    "size_mm": float(size_mm),
                }
            )
            continue

        # Tracks: sample along the segment to approximate its occupied corridor.
        if isinstance(item, pcbnew.PCB_TRACK):
            layer_id = int(item.GetLayer())
            li = layer_index.get(layer_id)
            if li is None:
                continue
            start = item.GetStart()
            end = item.GetEnd()
            width_mm = _to_mm(int(item.GetWidth()))
            radius_mm = (width_mm / 2.0) + float(inflate_mm)
            dist = _dist_mm(start, end)
            step = max(resolution_mm / 2.0, 0.05)
            steps = max(1, int(dist / step))
            for i in range(steps + 1):
                t = i / steps
                x = int(round(start.x + (end.x - start.x) * t))
                y = int(round(start.y + (end.y - start.y) * t))
                gx, gy = _grid_xy(pcbnew.VECTOR2I(x, y), resolution_mm)
                add_circle(
                    net_name=net_name,
                    net_id=net_id,
                    layers=[li],
                    gx=gx,
                    gy=gy,
                    r=_grid_r(radius_mm, resolution_mm),
                )
            continue

    for drawing in list(board.GetDrawings()):
        if not isinstance(drawing, pcbnew.PCB_SHAPE):
            continue
        try:
            net_name = str(drawing.GetNetname())
        except Exception:
            net_name = ""
        if net_name not in net_id_by_name:
            continue
        net_id = int(net_id_by_name.get(net_name, 0))
        if net_id <= 0:
            continue
        layer_id = int(drawing.GetLayer())
        li = layer_index.get(layer_id)
        if li is None:
            continue
        try:
            shape = int(drawing.GetShape())
        except Exception:
            continue
        if shape == int(pcbnew.SHAPE_T_CIRCLE):
            try:
                if not bool(drawing.IsFilled()):
                    continue
            except Exception:
                continue
            center = drawing.GetStart()
            edge = drawing.GetEnd()
            radius_mm = _dist_mm(center, edge) + float(inflate_mm)
            gx, gy = _grid_xy(center, resolution_mm)
            add_circle(
                net_name=net_name,
                net_id=net_id,
                layers=[li],
                gx=gx,
                gy=gy,
                r=_grid_r(radius_mm, resolution_mm),
            )

    # Board extents in grid cells: prefer outline size if available; fallback to bbox.
    try:
        bbox = board.GetBoardEdgesBoundingBox()
        width_mm = _to_mm(int(bbox.GetWidth()))
        height_mm = _to_mm(int(bbox.GetHeight()))
    except Exception:
        bbox = board.GetBoundingBox()
        width_mm = _to_mm(int(bbox.GetWidth()))
        height_mm = _to_mm(int(bbox.GetHeight()))
    width = int((width_mm / resolution_mm) + 0.999999)
    height = int((height_mm / resolution_mm) + 0.999999)

    payload: Dict[str, Any] = {
        "version": 1,
        "pcb_path": str(pcb_path),
        "resolution_mm": float(resolution_mm),
        "inflate_mm": float(inflate_mm),
        "layers": layer_names,
        "width": int(width),
        "height": int(height),
        "net_defaults": {
            "track_width_mm": float(track_w_mm),
            "clearance_mm": float(clr_mm),
            "via_diameter_mm": float(via_d_mm),
            "via_drill_mm": float(via_dr_mm),
            "uvia_diameter_mm": float(uvia_d_mm),
            "uvia_drill_mm": float(uvia_dr_mm),
        },
        "circles": [
            {
                "net": c.net_name,
                "net_id": int(c.net_id),
                "layers": [int(li) for li in c.layers],
                "center": {"x": int(c.x), "y": int(c.y)},
                "r": int(c.r),
            }
            for c in circles.values()
        ],
        "existing_vias": existing_vias,
        "nets": [
            {
                "net": name,
                "net_id": int(net_id),
                "start": {"layer": int(s[0]), "x": int(s[1]), "y": int(s[2])},
                "goal": {"layer": int(g[0]), "x": int(g[1]), "y": int(g[2])},
                "track_width_mm": float(track_w_mm),
                "via_diameter_mm": float(via_d_mm),
                "via_drill_mm": float(via_dr_mm),
                "uvia_diameter_mm": float(uvia_d_mm),
                "uvia_drill_mm": float(uvia_dr_mm),
            }
            for (name, net_id, s, g) in net_specs
        ],
    }

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pcb", dest="pcb_path", type=Path, required=True)
    ap.add_argument("--out", dest="out_json", type=Path, required=True)
    ap.add_argument("--resolution", dest="resolution_mm", type=float, default=0.2)
    ap.add_argument("--inflate", dest="inflate_mm", type=float, default=None)
    args = ap.parse_args()
    extract_problem(
        pcb_path=args.pcb_path,
        out_json=args.out_json,
        resolution_mm=float(args.resolution_mm),
        inflate_mm=args.inflate_mm if args.inflate_mm is None else float(args.inflate_mm),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
