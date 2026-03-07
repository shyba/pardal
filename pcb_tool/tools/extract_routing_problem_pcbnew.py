#!/usr/bin/env python3
"""Extract a compact routing problem from a KiCad PCB using pcbnew (KiCad 9).

This script is intended to run inside KiCad's bundled Python environment (e.g. the
`kicad/kicad:9.x-full` docker image). It produces a lightweight JSON input for the
Rust router backend without embedding a full raster grid.

The current extractor is optimized for the `fpga_large` fixture:
- Exports circular pads as circles and non-circular pads as polygonal footprints.
- Polygon pads include rounded primitives (oval/roundrect) where possible.
- Builds per-net start/goal points from U1 BGA pads and TP* testpoint pads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import pcbnew

_PAD_SHAPE_CIRCLE = int(getattr(pcbnew, "PAD_SHAPE_CIRCLE", -1))
_PAD_SHAPE_OVAL = int(getattr(pcbnew, "PAD_SHAPE_OVAL", -1))
_PAD_SHAPE_ROUNDRECT = int(getattr(pcbnew, "PAD_SHAPE_ROUNDRECT", -1))
_PAD_SHAPE_RECT = int(getattr(pcbnew, "PAD_SHAPE_RECT", -1))
_PAD_SHAPE_TRAPEZOID = int(getattr(pcbnew, "PAD_SHAPE_TRAPEZOID", -1))
_PAD_SHAPE_CHAMFERED_RECT = int(getattr(pcbnew, "PAD_SHAPE_CHAMFERED_RECT", -1))
_PAD_SHAPE_CUSTOM = int(getattr(pcbnew, "PAD_SHAPE_CUSTOM", -1))


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


def _enforce_min_annular(
    *,
    size_mm: float,
    drill_mm: float,
    min_annular_mm: float,
) -> float:
    if min_annular_mm <= 0.0:
        return float(size_mm)
    needed = float(drill_mm) + 2.0 * float(min_annular_mm)
    return float(max(size_mm, needed))


def _board_min_annular_widths(board: pcbnew.BOARD) -> Tuple[float, float]:
    via_min_annular_mm = 0.0
    uvia_min_annular_mm = 0.0
    try:
        ds = board.GetDesignSettings()
        via_min_annular_mm = _to_mm(int(getattr(ds, "m_ViasMinAnnularWidth", 0)))
        uvia_min_annular_mm = _to_mm(int(getattr(ds, "m_MicroViasMinAnnularWidth", 0)))
    except Exception:
        via_min_annular_mm = 0.0
        uvia_min_annular_mm = 0.0
    if uvia_min_annular_mm <= 0.0:
        uvia_min_annular_mm = via_min_annular_mm
    return float(via_min_annular_mm), float(uvia_min_annular_mm)


def _netclass_defaults(board: pcbnew.BOARD) -> Tuple[float, float, float, float, float, float]:
    """Return (track_width_mm, clearance_mm, via_diam_mm, via_drill_mm, uvia_diam_mm, uvia_drill_mm)."""
    # KiCad board-level minimum annular width constraints. If a netclass has
    # smaller via/microvia sizes, bump diameters so routed vias are legal by
    # construction instead of relying on post-route DRC cleanup.
    via_min_annular_mm, uvia_min_annular_mm = _board_min_annular_widths(board)

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
        via_d = _enforce_min_annular(size_mm=via_d, drill_mm=via_dr, min_annular_mm=via_min_annular_mm)
        uvia_d = _enforce_min_annular(size_mm=uvia_d, drill_mm=uvia_dr, min_annular_mm=uvia_min_annular_mm)
        return track, clr, via_d, via_dr, uvia_d, uvia_dr
    try:
        uvia_d = _to_mm(int(nc.GetuViaDiameter()))
        uvia_dr = _to_mm(int(nc.GetuViaDrill()))
    except Exception:
        uvia_d = _to_mm(int(nc.GetViaDiameter()))
        uvia_dr = _to_mm(int(nc.GetViaDrill()))
    via_d = _to_mm(int(nc.GetViaDiameter()))
    via_dr = _to_mm(int(nc.GetViaDrill()))
    via_d = _enforce_min_annular(size_mm=via_d, drill_mm=via_dr, min_annular_mm=via_min_annular_mm)
    uvia_d = _enforce_min_annular(size_mm=uvia_d, drill_mm=uvia_dr, min_annular_mm=uvia_min_annular_mm)
    return (_to_mm(int(nc.GetTrackWidth())), _to_mm(int(nc.GetClearance())), via_d, via_dr, uvia_d, uvia_dr)


def _netclass_profiles(
    board: pcbnew.BOARD,
    default_profile: Tuple[float, float, float, float, float, float],
) -> Dict[str, Tuple[float, float, float, float, float, float]]:
    """Return per-netclass (track, clearance, via_d, via_drill, uvia_d, uvia_drill)."""
    via_min_annular_mm, uvia_min_annular_mm = _board_min_annular_widths(board)
    out: Dict[str, Tuple[float, float, float, float, float, float]] = {}
    try:
        all_ncs = dict(board.GetAllNetClasses())
    except Exception:
        all_ncs = {}
    for name, nc in all_ncs.items():
        try:
            track_mm = _to_mm(int(nc.GetTrackWidth()))
            clearance_mm = _to_mm(int(nc.GetClearance()))
            via_d_mm = _to_mm(int(nc.GetViaDiameter()))
            via_dr_mm = _to_mm(int(nc.GetViaDrill()))
            try:
                uvia_d_mm = _to_mm(int(nc.GetuViaDiameter()))
                uvia_dr_mm = _to_mm(int(nc.GetuViaDrill()))
            except Exception:
                uvia_d_mm = via_d_mm
                uvia_dr_mm = via_dr_mm
            via_d_mm = _enforce_min_annular(
                size_mm=via_d_mm,
                drill_mm=via_dr_mm,
                min_annular_mm=via_min_annular_mm,
            )
            uvia_d_mm = _enforce_min_annular(
                size_mm=uvia_d_mm,
                drill_mm=uvia_dr_mm,
                min_annular_mm=uvia_min_annular_mm,
            )
            out[str(name)] = (
                float(track_mm),
                float(clearance_mm),
                float(via_d_mm),
                float(via_dr_mm),
                float(uvia_d_mm),
                float(uvia_dr_mm),
            )
        except Exception:
            continue
    if "Default" not in out:
        out["Default"] = default_profile
    return out


def _netclass_by_net_name(board: pcbnew.BOARD) -> Dict[str, str]:
    """Return net_name -> netclass name for nets available on the board."""
    out: Dict[str, str] = {}
    try:
        net_info = board.GetNetInfo()
        net_count = int(board.GetNetCount())
    except Exception:
        return out
    for i in range(net_count):
        try:
            net_item = net_info.GetNetItem(i)
            net_name = str(net_item.GetNetname())
        except Exception:
            continue
        if not net_name:
            continue
        try:
            class_name = str(net_item.GetNetClassName())
        except Exception:
            class_name = ""
        if class_name:
            out[net_name] = class_name
    return out


def _grid_xy(
    pos: pcbnew.VECTOR2I,
    resolution_mm: float,
    *,
    origin_x_mm: float = 0.0,
    origin_y_mm: float = 0.0,
) -> Tuple[int, int]:
    x_mm = _to_mm(int(pos.x)) - float(origin_x_mm)
    y_mm = _to_mm(int(pos.y)) - float(origin_y_mm)
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


def _rotated_rect_points_grid(
    *,
    center: pcbnew.VECTOR2I,
    w_mm: float,
    h_mm: float,
    angle_deg: float,
    inflate_mm: float,
    origin_x_mm: float,
    origin_y_mm: float,
    resolution_mm: float,
) -> List[Dict[str, int]]:
    """Return 4 corner points (grid coords) for a rotated rectangle with inflation."""
    cx_mm = _to_mm(int(center.x)) - float(origin_x_mm)
    cy_mm = _to_mm(int(center.y)) - float(origin_y_mm)
    hw = 0.5 * (float(w_mm) + 2.0 * float(inflate_mm))
    hh = 0.5 * (float(h_mm) + 2.0 * float(inflate_mm))

    # Corners in local coordinates (counter-clockwise).
    local = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    th = math.radians(float(angle_deg))
    c = math.cos(th)
    s = math.sin(th)
    out: List[Dict[str, int]] = []
    for lx, ly in local:
        rx = lx * c - ly * s
        ry = lx * s + ly * c
        gx = int(round((cx_mm + rx) / float(resolution_mm)))
        gy = int(round((cy_mm + ry) / float(resolution_mm)))
        out.append({"x": gx, "y": gy})
    return out


def _rotated_superellipse_points_grid(
    *,
    center: pcbnew.VECTOR2I,
    w_mm: float,
    h_mm: float,
    angle_deg: float,
    inflate_mm: float,
    origin_x_mm: float,
    origin_y_mm: float,
    resolution_mm: float,
    point_count: int,
    exponent: float,
) -> List[Dict[str, int]]:
    """Return polygon points (grid coords) approximating a rounded rectangle/ellipse."""
    if point_count < 4:
        point_count = 4
    if exponent <= 0.0:
        return _rotated_rect_points_grid(
            center=center,
            w_mm=w_mm,
            h_mm=h_mm,
            angle_deg=angle_deg,
            inflate_mm=inflate_mm,
            origin_x_mm=origin_x_mm,
            origin_y_mm=origin_y_mm,
            resolution_mm=resolution_mm,
        )
    cx_mm = _to_mm(int(center.x)) - float(origin_x_mm)
    cy_mm = _to_mm(int(center.y)) - float(origin_y_mm)
    hw = 0.5 * (float(w_mm) + 2.0 * float(inflate_mm))
    hh = 0.5 * (float(h_mm) + 2.0 * float(inflate_mm))
    if hw <= 0.0 or hh <= 0.0:
        return _rotated_rect_points_grid(
            center=center,
            w_mm=w_mm,
            h_mm=h_mm,
            angle_deg=angle_deg,
            inflate_mm=inflate_mm,
            origin_x_mm=origin_x_mm,
            origin_y_mm=origin_y_mm,
            resolution_mm=resolution_mm,
        )
    # p=2 => ellipse. Larger exponent biases toward a box-like shape.
    p = max(1.0, float(exponent))
    m = 2.0 / p

    th = math.radians(float(angle_deg))
    c = math.cos(th)
    s = math.sin(th)
    out: List[Dict[str, int]] = []
    i = 0
    step = (2.0 * math.pi) / float(point_count)
    while i < point_count:
        t = step * float(i)
        ct = math.cos(t)
        st = math.sin(t)
        x_local = hw * (abs(ct) ** m)
        y_local = hh * (abs(st) ** m)
        if ct < 0.0:
            x_local = -x_local
        if st < 0.0:
            y_local = -y_local
        rx = x_local * c - y_local * s
        ry = x_local * s + y_local * c
        gx = int(round((cx_mm + rx) / float(resolution_mm)))
        gy = int(round((cy_mm + ry) / float(resolution_mm)))
        out.append({"x": gx, "y": gy})
        i += 1
    return out


def _pad_layers(pad: pcbnew.PAD, copper_layer_ids: Iterable[int]) -> List[int]:
    layers: List[int] = []
    for lid in copper_layer_ids:
        try:
            if pad.IsOnLayer(lid):
                layers.append(int(lid))
        except Exception:
            continue
    return layers


def _chain_points_to_grid(
    chain: pcbnew.SHAPE_LINE_CHAIN,
    *,
    origin_x_mm: float,
    origin_y_mm: float,
    resolution_mm: float,
) -> List[Dict[str, int]]:
    """Return polygon points in grid coordinates for a KiCad SHAPE_LINE_CHAIN."""
    out: List[Dict[str, int]] = []
    try:
        n = int(chain.PointCount())
    except Exception:
        return out
    if n < 3:
        return out

    i = 0
    last_x = None
    last_y = None
    while i < n:
        try:
            pt = chain.CPoint(i)
            x_mm = _to_mm(int(pt.x)) - float(origin_x_mm)
            y_mm = _to_mm(int(pt.y)) - float(origin_y_mm)
            gx = int(round(x_mm / float(resolution_mm)))
            gy = int(round(y_mm / float(resolution_mm)))
            if gx != last_x or gy != last_y:
                out.append({"x": int(gx), "y": int(gy)})
                last_x = gx
                last_y = gy
        except Exception:
            pass
        i += 1

    if out:
        # Drop trailing duplicate when contours are explicitly closed.
        if len(out) > 1 and out[0] == out[-1]:
            out.pop()
    return out


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
    nets_filter: Optional[Set[str]] = None,
) -> None:
    board = pcbnew.LoadBoard(str(pcb_path))
    origin_x_mm = 0.0
    origin_y_mm = 0.0
    try:
        bbox = board.GetBoardEdgesBoundingBox()
    except Exception:
        bbox = board.GetBoundingBox()
    bbox_x_mm = _to_mm(int(bbox.GetX()))
    bbox_y_mm = _to_mm(int(bbox.GetY()))
    bbox_w_mm = _to_mm(int(bbox.GetWidth()))
    bbox_h_mm = _to_mm(int(bbox.GetHeight()))
    # Grid extents are defined in the same absolute coordinate system as all extracted
    # pad/track coordinates (origin at 0). Ensure the grid spans the full board bbox,
    # even if the board bbox min is negative.
    x_max_mm = max(0.0, float(bbox_x_mm + bbox_w_mm))
    y_max_mm = max(0.0, float(bbox_y_mm + bbox_h_mm))
    width = int(math.ceil(x_max_mm / resolution_mm)) + 2
    height = int(math.ceil(y_max_mm / resolution_mm)) + 2
    # Board-level copper-to-edge clearance (KiCad DRC "copper edge clearance").
    # Expose this so the router can block a border band and avoid routing outside
    # of the legal area. Default to 0.0 if unavailable (older pcbnew APIs).
    edge_clearance_mm = 0.0
    try:
        ds = board.GetDesignSettings()
        try:
            edge_clearance_mm = _to_mm(int(ds.GetCopperEdgeClearance()))
        except Exception:
            edge_clearance_mm = _to_mm(int(getattr(ds, "m_CopperEdgeClearance", 0)))
    except Exception:
        edge_clearance_mm = 0.0
    layer_ids = _copper_layer_ids(board)
    layer_names = _copper_layer_names(board)
    layer_id_by_name: Dict[str, int] = {name: lid for name, lid in zip(layer_names, layer_ids)}
    layer_index = _layer_index_by_id(board)

    track_w_mm, clr_mm, via_d_mm, via_dr_mm, uvia_d_mm, uvia_dr_mm = _netclass_defaults(board)
    default_profile = (
        float(track_w_mm),
        float(clr_mm),
        float(via_d_mm),
        float(via_dr_mm),
        float(uvia_d_mm),
        float(uvia_dr_mm),
    )
    netclass_profiles = _netclass_profiles(board, default_profile)
    netclass_by_net = _netclass_by_net_name(board)
    layer_roles: Dict[str, str] = {}
    internal_plane_layers: List[int] = []
    for li, lname in enumerate(layer_names):
        up = str(lname).upper()
        is_plane = ("GND" in up) or ("PWR" in up) or ("POWER" in up) or ("PLANE" in up)
        layer_roles[lname] = "plane" if is_plane else "signal"
        if is_plane and li > 0 and li < (len(layer_names) - 1):
            internal_plane_layers.append(int(li))
    if inflate_mm is None:
        # Keep hard geometry close to physical copper size by default. Clearance
        # handling is negotiated in the router; over-inflating hard obstacles can
        # close real channels and block completion on dense boards.
        # Keep a tiny safety margin above half-track to avoid borderline
        # short-mask artifacts from grid quantization.
        inflate_mm = max((track_w_mm / 2.0) + 0.005, resolution_mm * 0.5)
    # Extra inflation for copper pads without a net: KiCad treats these as obstacles
    # for all nets, and via annuli can be larger than track widths. Without this,
    # we can get pad/via clearance DRC failures near no-net copper features.
    nonet_extra_inflate_mm = max(0.0, (uvia_d_mm / 2.0) - (track_w_mm / 2.0))

    # Board-level drill-to-drill clearance (KiCad DRC "hole to hole" constraint).
    # Used to generate a via-only keepout field, so we don't place vias too close to
    # any existing drilled pad hole (even on the same net).
    hole_clearance_mm = 0.25
    try:
        ds = board.GetDesignSettings()
        try:
            hole_clearance_mm = _to_mm(int(ds.GetMinHoleClearance()))
        except Exception:
            hole_clearance_mm = _to_mm(int(getattr(ds, "m_HoleClearance", pcbnew.FromMM(0.25))))
    except Exception:
        hole_clearance_mm = 0.25


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

    def _pick_pad_start_layer(pad: pcbnew.PAD) -> str:
        """Pick a legal copper layer for a pad endpoint, preferring F.Cu when present."""
        ordered: List[str] = []
        if "F.Cu" in layer_id_by_name:
            ordered.append("F.Cu")
        for name in layer_names:
            if name not in ordered:
                ordered.append(name)
        for name in ordered:
            lid = layer_id_by_name.get(name)
            if lid is None:
                continue
            try:
                if bool(pad.IsOnLayer(int(lid))):
                    return name
            except Exception:
                continue
        return "F.Cu" if "F.Cu" in layer_names else layer_names[0]

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
                # For generic boards (non-fpga_large), prefer routing *all* nets with
                # at least 2 pads. Limiting to small nets causes us to ignore power
                # nets/pads as obstacles, which can create shorts in the routed output.
                if 2 <= len(pads)
            ]
        )
    if nets_filter is not None:
        net_names = [n for n in net_names if n in nets_filter]
    net_id_by_name: Dict[str, int] = {name: i + 1 for i, name in enumerate(net_names)}

    # Net specs can contain multiple segments per net name (e.g. VCC/GND).
    # Each segment shares the same `net_id` (ownership + obstacles), but has its own endpoints.
    net_specs: List[Tuple[str, int, Tuple[int, int, int], Tuple[int, int, int]]] = []

    if use_tp_goals:
        starts: Dict[str, Tuple[int, int, int]] = {}
        goals: Dict[str, Tuple[int, int, int]] = {}
        start_uuid: Dict[str, str] = {}
        goal_uuid: Dict[str, str] = {}

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
            gx, gy = _grid_xy(
                pad.GetPosition(),
                origin_x_mm=origin_x_mm,
                origin_y_mm=origin_y_mm,
                resolution_mm=resolution_mm,
            )
            # Use a pad-valid copper layer for endpoint anchoring. This avoids
            # synthetic starts on inner layers that are not physically connected
            # to the actual pad copper after routing cleanup.
            start_layer = _pick_pad_start_layer(pad)
            starts[net_name] = (layer_names.index(start_layer), gx, gy)
            try:
                start_uuid[net_name] = str(pad.m_Uuid.AsString())
            except Exception:
                pass

        # Goal points: TP* pads (prefer F.Cu if present).
        for fp in board.GetFootprints():
            ref = str(fp.GetReference() or "")
            if not ref.startswith("TP"):
                continue
            for pad in fp.Pads():
                net_name = str(pad.GetNetname())
                if net_name not in net_id_by_name:
                    continue
                gx, gy = _grid_xy(
                    pad.GetPosition(),
                    origin_x_mm=origin_x_mm,
                    origin_y_mm=origin_y_mm,
                    resolution_mm=resolution_mm,
                )
                goal_layer = "F.Cu" if "F.Cu" in layer_names else layer_names[0]
                goals[net_name] = (layer_names.index(goal_layer), gx, gy)
                try:
                    goal_uuid[net_name] = str(pad.m_Uuid.AsString())
                except Exception:
                    pass
    else:
        # Generic fallback: route nets by pad connectivity on a single outer layer.
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
                    ax, ay = _grid_xy(
                        ai.GetPosition(),
                        origin_x_mm=origin_x_mm,
                        origin_y_mm=origin_y_mm,
                        resolution_mm=resolution_mm,
                    )
                    bx, by = _grid_xy(
                        bi.GetPosition(),
                        origin_x_mm=origin_x_mm,
                        origin_y_mm=origin_y_mm,
                        resolution_mm=resolution_mm,
                    )
                    try:
                        au = str(ai.m_Uuid.AsString())
                    except Exception:
                        au = ""
                    try:
                        bu = str(bi.m_Uuid.AsString())
                    except Exception:
                        bu = ""
                    a_layer = _pick_pad_start_layer(ai)
                    b_layer = _pick_pad_start_layer(bi)
                    a_li = layer_names.index(a_layer)
                    b_li = layer_names.index(b_layer)
                    net_specs.append(
                        (net_name, net_id_by_name[net_name], (a_li, ax, ay), (b_li, bx, by), au, bu)
                    )
                    used += 1
                    if used >= len(pads_sorted) - 1:
                        break

    if use_tp_goals:
        missing = [n for n in net_names if n not in starts or n not in goals]
        if missing:
            raise SystemExit(f"Missing endpoints for {len(missing)} nets (e.g. {missing[:5]})")
        for name in net_names:
            net_specs.append(
                (
                    name,
                    net_id_by_name[name],
                    starts[name],
                    goals[name],
                    start_uuid.get(name, ""),
                    goal_uuid.get(name, ""),
                )
            )

    if not net_specs:
        raise SystemExit("No nets found to route (net_specs is empty)")

    circles: Dict[Tuple[str, int, int, int, int, int], _Circle] = {}
    drill_circles: Dict[Tuple[int, int, int], Tuple[int, int, int]] = {}
    polygons: List[Dict[str, Any]] = []
    existing_vias: List[Dict[str, Any]] = []
    # Drilled pad stacks (typically PTH) are exported separately so the router
    # can avoid placing new vias directly on top of existing drilled pads.
    pad_stacks: Dict[Tuple[int, int, Tuple[int, ...]], Dict[str, Any]] = {}
    existing_tracks: List[Dict[str, Any]] = []

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
            # Always treat copper pads as obstacles, even if the net is not being
            # routed. Otherwise the router may place tracks through pads on other
            # nets (or no-net mechanical pads), creating DRC shorts.
            net_id = int(net_id_by_name.get(net_name, 0))
            size = pad.GetSize()
            w_mm = _to_mm(int(size.x))
            h_mm = _to_mm(int(size.y))
            gx, gy = _grid_xy(
                pad.GetPosition(),
                origin_x_mm=origin_x_mm,
                origin_y_mm=origin_y_mm,
                resolution_mm=resolution_mm,
            )

            pad_layers = _pad_layers(pad, layer_ids)
            if not pad_layers:
                continue
            layers = tuple(sorted({layer_index[lid] for lid in pad_layers if lid in layer_index}))
            if not layers:
                continue
            pad_inflate_mm = float(inflate_mm) + (float(nonet_extra_inflate_mm) if not net_name else 0.0)

            # Use a closer pad-shape approximation than circles for non-round pads.
            # Over-inflated circles can close narrow channels and prevent routing.
            angle_deg = 0.0
            try:
                ang = pad.GetOrientation()
                # KiCad 9: EDA_ANGLE has AsDegrees()
                angle_deg = float(getattr(ang, "AsDegrees", lambda: 0.0)())
            except Exception:
                angle_deg = 0.0
            try:
                shape = int(pad.GetShape())
            except Exception:
                shape = -1

            is_round = False
            is_round = shape == _PAD_SHAPE_CIRCLE
            shape_is_oval = shape == _PAD_SHAPE_OVAL
            shape_is_roundrect = shape == _PAD_SHAPE_ROUNDRECT
            shape_is_chamfered = shape == _PAD_SHAPE_CHAMFERED_RECT
            shape_is_trapezoid = shape == _PAD_SHAPE_TRAPEZOID
            shape_is_custom = shape == _PAD_SHAPE_CUSTOM
            if shape < 0:
                shape_is_oval = False
                shape_is_roundrect = False
                shape_is_chamfered = False
                shape_is_trapezoid = False
                shape_is_custom = False

            if is_round and abs(w_mm - h_mm) < 1e-6:
                radius_mm = 0.5 * float(w_mm) + pad_inflate_mm
                r = _grid_r(radius_mm, resolution_mm)
                for li in layers:
                    add_circle(net_name=net_name, net_id=net_id, layers=[li], gx=gx, gy=gy, r=r)
            elif shape_is_oval:
                pts = _rotated_superellipse_points_grid(
                    center=pad.GetPosition(),
                    w_mm=float(w_mm),
                    h_mm=float(h_mm),
                    angle_deg=float(angle_deg),
                    inflate_mm=pad_inflate_mm,
                    origin_x_mm=origin_x_mm,
                    origin_y_mm=origin_y_mm,
                    resolution_mm=float(resolution_mm),
                    point_count=40,
                    exponent=2.0,
                )
                if len(pts) >= 3:
                    polygons.append(
                        {
                            "net": net_name,
                            "net_id": int(net_id),
                            "src": "pad",
                            "layers": [int(li) for li in layers],
                            "points": pts,
                        }
                    )
            elif shape_is_roundrect or shape_is_chamfered or shape_is_trapezoid:
                pts = _rotated_superellipse_points_grid(
                    center=pad.GetPosition(),
                    w_mm=float(w_mm),
                    h_mm=float(h_mm),
                    angle_deg=float(angle_deg),
                    inflate_mm=pad_inflate_mm,
                    origin_x_mm=origin_x_mm,
                    origin_y_mm=origin_y_mm,
                    resolution_mm=float(resolution_mm),
                    point_count=28,
                    exponent=4.0,
                )
                if len(pts) >= 3:
                    polygons.append(
                        {
                            "net": net_name,
                            "net_id": int(net_id),
                            "src": "pad",
                            "layers": [int(li) for li in layers],
                            "points": pts,
                        }
                    )
            elif shape_is_custom:
                pts = _rotated_superellipse_points_grid(
                    center=pad.GetPosition(),
                    w_mm=float(w_mm),
                    h_mm=float(h_mm),
                    angle_deg=float(angle_deg),
                    inflate_mm=pad_inflate_mm,
                    origin_x_mm=origin_x_mm,
                    origin_y_mm=origin_y_mm,
                    resolution_mm=float(resolution_mm),
                    point_count=36,
                    exponent=2.8,
                )
                if len(pts) >= 3:
                    polygons.append(
                        {
                            "net": net_name,
                            "net_id": int(net_id),
                            "src": "pad",
                            "layers": [int(li) for li in layers],
                            "points": pts,
                        }
                    )
            else:
                pts = _rotated_rect_points_grid(
                    center=pad.GetPosition(),
                    w_mm=float(w_mm),
                    h_mm=float(h_mm),
                    angle_deg=float(angle_deg),
                    inflate_mm=pad_inflate_mm,
                    origin_x_mm=origin_x_mm,
                    origin_y_mm=origin_y_mm,
                    resolution_mm=float(resolution_mm),
                )
                polygons.append(
                    {
                        "net": net_name,
                        "net_id": int(net_id),
                        "src": "pad",
                        "layers": [int(li) for li in layers],
                        "points": pts,
                    }
                )

            # Via-only drill keepout: forbid via drills too close to pad drills.
            # This is enforced during via placement (not for track routing).
            try:
                drill = pad.GetDrillSize()
                drill_w_mm = _to_mm(int(drill.x))
                drill_h_mm = _to_mm(int(drill.y))
            except Exception:
                drill_w_mm = 0.0
                drill_h_mm = 0.0
            drill_mm = max(drill_w_mm, drill_h_mm)
            if drill_mm > 0.0:
                keepout_mm = (drill_mm / 2.0) + float(hole_clearance_mm) + (via_dr_mm / 2.0)
                dr = _grid_r(keepout_mm, resolution_mm)
                drill_circles[(gx, gy, dr)] = (gx, gy, dr)
                # Vertical drill stack used by router emission to suppress
                # co-located vias that would violate hole-to-hole constraints.
                if len(layers) >= 2:
                    ps_key = (int(gx), int(gy), tuple(int(li) for li in layers))
                    if ps_key not in pad_stacks:
                        pad_stacks[ps_key] = {
                            "net": net_name,
                            "net_id": int(net_id),
                            "layers": [int(li) for li in layers],
                            "center": {"x": int(gx), "y": int(gy)},
                            "drill_mm": float(drill_mm),
                        }


    # Existing copper on inner layers matters for short avoidance (e.g. the fpga_large
    # fixture seeds a tiny filled circle on In1.Cu for every BGA net).
    for item in board.GetTracks():
        try:
            net_name = str(item.GetNetname())
        except Exception:
            continue
        # Existing copper should always be treated as an obstacle, even for nets
        # we don't attempt to route in this run.
        net_id = int(net_id_by_name.get(net_name, 0))

        # Vias: stamp across their layer span.
        if isinstance(item, pcbnew.PCB_VIA):
            pos = item.GetPosition()
            gx, gy = _grid_xy(
                pos,
                origin_x_mm=origin_x_mm,
                origin_y_mm=origin_y_mm,
                resolution_mm=resolution_mm,
            )
            layers_idx: List[int] = []
            try:
                try:
                    size_mm = _to_mm(int(item.GetWidth(int(item.TopLayer()))))
                except Exception:
                    size_mm = via_d_mm
                drill_mm = 0.0
                try:
                    drill_mm = _to_mm(int(item.GetDrillValue()))
                except Exception:
                    try:
                        dsz = item.GetDrill()
                        drill_mm = _to_mm(int(max(int(dsz.x), int(dsz.y))))
                    except Exception:
                        drill_mm = via_dr_mm
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
                drill_mm = via_dr_mm
            if not layers_idx:
                # Fallback: treat as through via spanning all copper layers.
                layers_idx = list(range(len(layer_names)))
            if len(layers_idx) == 2 and abs(layers_idx[0] - layers_idx[1]) == 1 and drill_mm <= 0:
                drill_mm = uvia_dr_mm
            if drill_mm <= 0:
                drill_mm = via_dr_mm
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
                    "drill_mm": float(drill_mm),
                }
            )

            if drill_mm > 0.0:
                # Avoid placing future vias on top of, or too close to, this
                # existing drilled via for hole-to-hole clearance (applies to all
                # nets, including same-net vias).
                keepout_mm = (
                    (drill_mm / 2.0)
                    + float(hole_clearance_mm)
                    + (via_dr_mm / 2.0)
                )
                dr = _grid_r(keepout_mm, resolution_mm)
                drill_circles[(gx, gy, dr)] = (gx, gy, dr)
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
                gx, gy = _grid_xy(
                    pcbnew.VECTOR2I(x, y),
                    origin_x_mm=origin_x_mm,
                    origin_y_mm=origin_y_mm,
                    resolution_mm=resolution_mm,
                )
                add_circle(
                    net_name=net_name,
                    net_id=net_id,
                    layers=[li],
                    gx=gx,
                    gy=gy,
                    r=_grid_r(radius_mm, resolution_mm),
                )
            continue

    # Filled zone pours (including large copper fills and thermal islands) are
    # required obstacles for clearance parity.
    area_count = int(board.GetAreaCount())
    for aidx in range(area_count):
        try:
            area = board.GetArea(aidx)
        except Exception:
            continue
        try:
            if not area.IsFilled():
                continue
        except Exception:
            continue
        try:
            area_net_name = str(area.GetNetname())
        except Exception:
            area_net_name = ""
        area_net_id = int(net_id_by_name.get(area_net_name, 0))
        try:
            area_layer_set = area.GetLayerSet()
        except Exception:
            continue
        for lid in layer_ids:
            try:
                if not bool(area_layer_set.Contains(int(lid))):
                    continue
            except Exception:
                continue
            li = layer_index.get(int(lid))
            if li is None:
                continue
            try:
                fill = area.GetFilledPolysList(int(lid))
            except Exception:
                continue
            if fill is None:
                continue
            try:
                contour_count = int(fill.OutlineCount())
            except Exception:
                continue
            j = 0
            while j < contour_count:
                try:
                    chain = fill.COutline(j)
                except Exception:
                    chain = None
                if chain is None:
                    j += 1
                    continue
                pts = _chain_points_to_grid(
                    chain,
                    origin_x_mm=origin_x_mm,
                    origin_y_mm=origin_y_mm,
                    resolution_mm=resolution_mm,
                )
                if len(pts) >= 3:
                    polygons.append(
                        {
                            "net": area_net_name,
                            "net_id": int(area_net_id),
                            "src": "zone",
                            "layers": [int(li)],
                            "points": pts,
                        }
                    )
                j += 1

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
            gx, gy = _grid_xy(
                center,
                origin_x_mm=origin_x_mm,
                origin_y_mm=origin_y_mm,
                resolution_mm=resolution_mm,
            )
            add_circle(
                net_name=net_name,
                net_id=net_id,
                layers=[li],
                gx=gx,
                gy=gy,
                r=_grid_r(radius_mm, resolution_mm),
            )

    # Export existing copper tracks as obstacles/ownership so the router won't
    # blindly route through pre-routed copper. This is critical for fixtures
    # like `fpga_large` which include pre-existing escape/fanout wiring.
    for it in list(board.GetTracks()):
        try:
            if isinstance(it, pcbnew.PCB_VIA):
                continue
        except Exception:
            # Older pcbnew types: skip by RTTI type when possible.
            try:
                if int(it.Type()) == int(pcbnew.PCB_VIA_T):
                    continue
            except Exception:
                pass
        if not isinstance(it, pcbnew.PCB_TRACK):
            continue
        try:
            net_name = str(it.GetNetname() or "")
        except Exception:
            net_name = ""
        if not net_name:
            continue
        net_id = int(net_id_by_name.get(net_name, 0))
        try:
            layer_name = str(board.GetLayerName(int(it.GetLayer())))
        except Exception:
            layer_name = "F.Cu"
        start = it.GetStart()
        end = it.GetEnd()
        try:
            width_mm = _to_mm(int(it.GetWidth()))
        except Exception:
            width_mm = float(track_w_mm)
        existing_tracks.append(
            {
                "net": net_name,
                "net_id": int(net_id),
                "layer": layer_name,
                "width_mm": float(width_mm),
                "start_mm": [float(_to_mm(int(start.x))), float(_to_mm(int(start.y)))],
                "end_mm": [float(_to_mm(int(end.x))), float(_to_mm(int(end.y)))],
            }
        )

    nets_payload: List[Dict[str, Any]] = []
    default_nc = netclass_profiles.get("Default", default_profile)
    for name, net_id, s, g, su, gu in net_specs:
        class_name = netclass_by_net.get(name, "Default")
        nc = netclass_profiles.get(class_name, default_nc)
        _tw_mm, nc_clearance_mm, _nc_via_d_mm, _nc_via_dr_mm, _nc_uvia_d_mm, _nc_uvia_dr_mm = nc
        net_track_w_mm = float(_tw_mm if _tw_mm > 0.0 else track_w_mm)
        net_via_d_mm = float(_nc_via_d_mm if _nc_via_d_mm > 0.0 else via_d_mm)
        net_via_dr_mm = float(_nc_via_dr_mm if _nc_via_dr_mm > 0.0 else via_dr_mm)
        net_uvia_d_mm = float(_nc_uvia_d_mm if _nc_uvia_d_mm > 0.0 else uvia_d_mm)
        net_uvia_dr_mm = float(_nc_uvia_dr_mm if _nc_uvia_dr_mm > 0.0 else uvia_dr_mm)
        # Keep endpoint identifiers deterministic across repeated extractions.
        #
        # KiCad pad UUIDs can vary across intermediate board copies, and using
        # those unstable strings in routing payloads leads to route-quality drift
        # for otherwise identical geometry. We still preserve the original pad
        # UUIDs in side fields for debugging/forward compatibility.
        su_det = f"s_{int(net_id)}_{int(s[0])}_{int(s[1])}_{int(s[2])}"
        gu_det = f"g_{int(net_id)}_{int(g[0])}_{int(g[1])}_{int(g[2])}"
        row = {
            "net": name,
            "net_id": int(net_id),
            "netclass": str(class_name),
            "start": {"layer": int(s[0]), "x": int(s[1]), "y": int(s[2])},
            "goal": {"layer": int(g[0]), "x": int(g[1]), "y": int(g[2])},
            "start_uuid": str(su_det),
            "goal_uuid": str(gu_det),
            "start_pad_uuid": str(su),
            "goal_pad_uuid": str(gu),
            # FR-style parity: honor per-netclass geometry + clearance.
            "track_width_mm": float(net_track_w_mm),
            "clearance_mm": float(nc_clearance_mm),
            "via_diameter_mm": float(net_via_d_mm),
            "via_drill_mm": float(net_via_dr_mm),
            "uvia_diameter_mm": float(net_uvia_d_mm),
            "uvia_drill_mm": float(net_uvia_dr_mm),
        }
        is_power_net = str(name) in {"GND", "GNDREF", "VCC", "3V3", "+3V3", "5V", "+5V", "12V", "+12V"}
        if is_power_net and internal_plane_layers:
            row["forbid_via_layers"] = [int(li) for li in internal_plane_layers]
        nets_payload.append(row)

    def _circle_indices_for_layer(layer_idx: int, cx: int, cy: int, r: int) -> List[int]:
        if layer_idx < 0 or layer_idx >= len(layer_names) or r <= 0:
            return []
        x0 = max(cx - r, 0)
        x1 = min(cx + r, width - 1)
        y0 = max(cy - r, 0)
        y1 = min(cy + r, height - 1)
        r2 = r * r
        layer_base = layer_idx * width * height
        out: List[int] = []
        for yy in range(y0, y1 + 1):
            dy = yy - cy
            dy2 = dy * dy
            row_base = layer_base + yy * width
            for xx in range(x0, x1 + 1):
                dx = xx - cx
                if dx * dx + dy2 <= r2:
                    out.append(row_base + xx)
        return out

    def _polygon_indices_for_layer(layer_idx: int, points: List[Dict[str, Any]]) -> List[int]:
        if layer_idx < 0 or layer_idx >= len(layer_names) or len(points) < 3:
            return []
        pts = [(int(pt["x"]), int(pt["y"])) for pt in points]
        min_x = max(min(x for x, _ in pts), 0)
        max_x = min(max(x for x, _ in pts), width - 1)
        min_y = max(min(y for _, y in pts), 0)
        max_y = min(max(y for _, y in pts), height - 1)
        if max_x < min_x or max_y < min_y:
            return []

        def _point_in_poly(px: int, py: int) -> bool:
            inside = False
            j = len(pts) - 1
            for i, (xi, yi) in enumerate(pts):
                xj, yj = pts[j]
                if (yi > py) != (yj > py):
                    lhs = (px - xi) * (yj - yi)
                    rhs = (py - yi) * (xj - xi)
                    if (yj - yi) > 0:
                        if lhs < rhs:
                            inside = not inside
                    else:
                        if lhs > rhs:
                            inside = not inside
                j = i
            return inside

        def _scanline_indices() -> List[int]:
            out: List[int] = []
            layer_base = layer_idx * width * height
            for yy in range(min_y, max_y + 1):
                hits: List[float] = []
                j = len(pts) - 1
                for i, (xi, yi) in enumerate(pts):
                    xj, yj = pts[j]
                    if (yi > yy) != (yj > yy):
                        dy = float(yj - yi)
                        if dy != 0.0:
                            x_hit = float(xi) + (float(yy - yi) * float(xj - xi) / dy)
                            hits.append(x_hit)
                    j = i
                hits.sort()
                row_base = layer_base + yy * width
                for xa, xb in zip(hits[0::2], hits[1::2]):
                    x0 = int(xa)
                    if float(x0) < xa:
                        x0 += 1
                    x1 = int(xb)
                    if float(x1) < xb:
                        x1 += 1
                    x1 -= 1
                    if x0 < min_x:
                        x0 = min_x
                    if x1 > max_x:
                        x1 = max_x
                    if x1 < x0:
                        continue
                    out.extend(row_base + xx for xx in range(x0, x1 + 1))
            return out

        bbox_area = (max_x - min_x + 1) * (max_y - min_y + 1)
        if len(pts) >= 128 or (len(pts) >= 16 and bbox_area >= 4096):
            return _scanline_indices()

        layer_base = layer_idx * width * height
        out: List[int] = []
        for yy in range(min_y, max_y + 1):
            row_base = layer_base + yy * width
            for xx in range(min_x, max_x + 1):
                if _point_in_poly(xx, yy):
                    out.append(row_base + xx)
        return out

    static_cache = {
        "schema_version": 1,
        "circles": [],
        "polygons": [],
    }
    for c in circles.values():
        effective_r = int(c.r)
        if int(c.net_id) == 0:
            effective_r += 1
        static_cache["circles"].append(
            {
                "layers": [
                    {
                        "layer": int(li),
                        "indices": _circle_indices_for_layer(int(li), int(c.x), int(c.y), effective_r),
                    }
                    for li in c.layers
                ]
            }
        )
    for p in polygons:
        static_cache["polygons"].append(
            {
                "layers": [
                    {
                        "layer": int(li),
                        "indices": _polygon_indices_for_layer(int(li), p["points"]),
                    }
                    for li in p["layers"]
                ]
            }
        )

    payload: Dict[str, Any] = {
        "version": 1,
        "pcb_path": str(pcb_path),
        "board_bbox_mm": {
            "x": float(bbox_x_mm),
            "y": float(bbox_y_mm),
            "w": float(bbox_w_mm),
            "h": float(bbox_h_mm),
        },
        "resolution_mm": float(resolution_mm),
        "inflate_mm": float(inflate_mm),
        "layers": layer_names,
        "layer_roles": layer_roles,
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
        "edge_clearance_mm": float(edge_clearance_mm),
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
        "drill_circles": [{"center": {"x": int(x), "y": int(y)}, "r": int(r)} for (x, y, r) in drill_circles.values()],
        "pad_stacks": list(pad_stacks.values()),
        "polygons": polygons,
        "existing_vias": existing_vias,
        "existing_tracks": existing_tracks,
        "nets": nets_payload,
    }

    out_json.parent.mkdir(parents=True, exist_ok=True)
    payload_text = json.dumps(payload, indent=2, sort_keys=True)
    out_json.write_text(payload_text, encoding="utf-8")
    out_pickle = out_json.with_suffix(".pickle")
    out_cache = out_json.with_suffix(".problem.cache.v1")
    source_stat = out_json.stat()
    payload_sha256 = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
    cache_payload = dict(payload)
    cache_payload["static_cache_v1"] = static_cache
    out_cache.write_bytes(
        pickle.dumps(
            {
                "schema_version": 1,
                "source_size": int(source_stat.st_size),
                "source_mtime_ns": int(source_stat.st_mtime_ns),
                "source_sha256": payload_sha256,
                "grid_dims": {
                    "layers": len(layer_names),
                    "width": int(width),
                    "height": int(height),
                },
                "resolution_mm": float(payload["resolution_mm"]),
                "config_build_hash": "extractor-static-raster-v1",
                "problem": cache_payload,
            },
            protocol=pickle.HIGHEST_PROTOCOL,
        )
    )
    out_pickle.write_bytes(
        pickle.dumps(
            {
                "source_size": int(source_stat.st_size),
                "source_mtime_ns": int(source_stat.st_mtime_ns),
                "problem": payload,
            },
            protocol=pickle.HIGHEST_PROTOCOL,
        )
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pcb", dest="pcb_path", type=Path, required=True)
    ap.add_argument("--out", dest="out_json", type=Path, required=True)
    ap.add_argument("--resolution", dest="resolution_mm", type=float, default=0.2)
    ap.add_argument("--inflate", dest="inflate_mm", type=float, default=None)
    ap.add_argument(
        "--nets-file",
        dest="nets_file",
        type=Path,
        default=None,
        help="Optional text file with one net name per line to restrict extraction.",
    )
    args = ap.parse_args()
    nets_filter: Optional[Set[str]] = None
    if args.nets_file is not None:
        nets_filter = {
            ln.strip()
            for ln in args.nets_file.read_text(encoding="utf-8", errors="replace").splitlines()
            if ln.strip()
        }
    extract_problem(
        pcb_path=args.pcb_path,
        out_json=args.out_json,
        resolution_mm=float(args.resolution_mm),
        inflate_mm=args.inflate_mm if args.inflate_mm is None else float(args.inflate_mm),
        nets_filter=nets_filter,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
