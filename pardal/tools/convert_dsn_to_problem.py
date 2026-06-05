#!/usr/bin/env python3
"""Convert a Specctra DSN file (FreeRouting fixtures) into a Mojo router problem.json.

This is an MVP semantic parser intended to unlock corpus-driven parity work.
It does NOT attempt to fully model FreeRouting's board/rules system yet.

Supported subset (enough for many fixtures):
- (resolution <unit> <value>)
- (unit <unit>) (ignored, we keep coordinates in DSN native units)
- (structure (layer <name> ...) ...) : captures ordered copper layers
- (structure (boundary (path pcb ...))) : captures boundary bbox for origin
- (placement (component ... (place REF X Y ... ) ...)) : captures component refs
- (library (image FP ... (pin ... <pin_no> <x> <y>) ...)) : captures footprint pin offsets
- (network (net <name> (pins REF-PIN ...))) : builds per-net endpoints

The produced problem.json is compatible with pardal_router_mojo (grid-based):
- Coordinates are mapped to a compact grid by resolution_um (default derived from DSN resolution).
- Pads are approximated as circular keepouts (radius derived from default clearance/width if present).
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _is_list(x: Any) -> bool:
    return isinstance(x, list)


def _as_str(x: Any) -> str:
    if isinstance(x, str):
        return x
    return str(x)


def _walk(root: Any) -> Iterable[Any]:
    stack = [root]
    while stack:
        n = stack.pop()
        yield n
        if _is_list(n):
            stack.extend(reversed(n))


def _first(root: Any, head: str) -> Optional[List[Any]]:
    for n in _walk(root):
        if _is_list(n) and n and _as_str(n[0]) == head:
            return n
    return None


def _all(root: Any, head: str) -> List[List[Any]]:
    out: List[List[Any]] = []
    for n in _walk(root):
        if _is_list(n) and n and _as_str(n[0]) == head:
            out.append(n)
    return out


def _parse_sexpr(src: str) -> Any:
    # Use the Mojo S-expression parser via its Python interop? No: keep this tool standalone.
    # Minimal python parser for DSN/RULES/SES fixtures (enough for parity work).
    i = 0
    out: List[Any] = []
    stack: List[List[Any]] = []
    at_line_start = True
    while i < len(src):
        ch = src[i]
        if ch in " \t\r\n":
            if ch == "\n":
                at_line_start = True
            i += 1
            continue
        if ch == ";" and at_line_start:
            # comment
            i += 1
            while i < len(src) and src[i] != "\n":
                i += 1
            continue
        if ch == "(":
            stack.append([])
            at_line_start = False
            i += 1
            continue
        if ch == ")":
            if not stack:
                raise ValueError("unexpected ')'")
            cur = stack.pop()
            if stack:
                stack[-1].append(cur)
            else:
                out.append(cur)
            at_line_start = False
            i += 1
            continue
        if ch == '"':
            # DSN sometimes uses standalone '"' atom: treat as atom if followed by ws or ')'
            if i + 1 < len(src) and src[i + 1] in " \t\r\n)":
                tok: Any = '"'
                if stack:
                    stack[-1].append(tok)
                else:
                    out.append(tok)
                at_line_start = False
                i += 1
                continue
            i += 1
            s = []
            while i < len(src):
                ch = src[i]
                if ch == '"':
                    i += 1
                    break
                if ch == "\\":
                    if i + 1 >= len(src):
                        raise ValueError("unterminated escape")
                    nxt = src[i + 1]
                    if nxt in '\\"':
                        s.append(nxt)
                    else:
                        # preserve unknown escapes (windows paths)
                        s.append("\\")
                        s.append(nxt)
                    i += 2
                    continue
                s.append(ch)
                i += 1
            tok = "".join(s)
            if stack:
                stack[-1].append(tok)
            else:
                out.append(tok)
            at_line_start = False
            continue
        # atom
        j = i
        while j < len(src) and src[j] not in " \t\r\n()\"":
            j += 1
        tok = src[i:j]
        if not tok:
            raise ValueError("empty atom")
        if stack:
            stack[-1].append(tok)
        else:
            out.append(tok)
        at_line_start = False
        i = j
    if stack:
        raise ValueError("unterminated '('")
    return out


@dataclass(frozen=True)
class PinRef:
    ref: str
    pin: str


@dataclass(frozen=True)
class Place:
    ref: str
    x: float
    y: float
    side: str
    rot_deg: float


def _rot_deg_to_rad(deg: float) -> float:
    return deg * math.pi / 180.0


def _apply_place_transform(place: Place, dx: float, dy: float) -> Tuple[float, float]:
    # DSN placement provides (x,y), side (front/back), and rotation degrees.
    # MVP transform:
    # - rotate pin offset by rot
    # - mirror X for back side (approx; Specctra semantics vary by exporter)
    # This is enough to reduce gross misplacement for many fixtures.
    ang = _rot_deg_to_rad(place.rot_deg)
    ca = math.cos(ang)
    sa = math.sin(ang)
    x = dx * ca - dy * sa
    y = dx * sa + dy * ca
    if place.side.lower() == "back":
        x = -x
    return place.x + x, place.y + y


def _parse_float(x: Any) -> float:
    return float(_as_str(x))


def _dsn_resolution_um(ast: Any) -> int:
    node = _first(ast, "resolution")
    if not node or len(node) < 3:
        return 10  # default like many KiCad exports (10um)
    unit = _as_str(node[1])
    val = int(float(_as_str(node[2])))
    if unit == "um":
        return val
    if unit == "mm":
        return int(val * 1000)
    if unit == "inch":
        return int(val * 25400)
    return val


def _dsn_layers(ast: Any) -> List[str]:
    struct = _first(ast, "structure")
    if not struct:
        return ["F.Cu", "B.Cu"]
    layers: List[Tuple[int, str]] = []
    for layer in _all(struct, "layer"):
        if len(layer) < 2:
            continue
        name = _as_str(layer[1])
        idx = None
        for prop in layer[2:]:
            if _is_list(prop) and prop and _as_str(prop[0]) == "property":
                for p in prop[1:]:
                    if _is_list(p) and len(p) >= 2 and _as_str(p[0]) == "index":
                        idx = int(float(_as_str(p[1])))
        if idx is None:
            idx = len(layers)
        layers.append((idx, name))
    layers.sort(key=lambda t: t[0])
    return [name for _, name in layers] or ["F.Cu", "B.Cu"]


def _dsn_default_rule(ast: Any) -> Tuple[Optional[float], Optional[float]]:
    # Return (width, clearance) in DSN units (typically um).
    struct = _first(ast, "structure")
    if not struct:
        return None, None
    rule = _first(struct, "rule")
    if not rule:
        return None, None
    width = None
    clearance = None
    for n in rule[1:]:
        if _is_list(n) and n:
            h = _as_str(n[0])
            if h == "width" and len(n) >= 2:
                width = _parse_float(n[1])
            if h == "clearance" and len(n) >= 2 and clearance is None:
                clearance = _parse_float(n[1])
    return width, clearance


def _dsn_keepouts(ast: Any) -> List[Tuple[str, float, float, float]]:
    # Return list of circle keepouts: (layer_name_or_signal, x, y, r) in DSN units.
    struct = _first(ast, "structure")
    if not struct:
        return []
    out: List[Tuple[str, float, float, float]] = []
    for ko in _all(struct, "keepout"):
        # (keepout <name?> (polygon <layer> <w> x y x y ...))
        # (keepout (circ <layer> <r> <x> <y>))
        for child in ko[1:]:
            if not _is_list(child) or not child:
                continue
            head = _as_str(child[0])
            if head == "circ" and len(child) >= 5:
                layer = _as_str(child[1])
                r = abs(_parse_float(child[2]))
                x = _parse_float(child[3])
                y = _parse_float(child[4])
                out.append((layer, x, y, r))
            if head == "polygon" and len(child) >= 5:
                layer = _as_str(child[1])
                coords = child[3:]
                pts = [(float(_as_str(coords[i])), float(_as_str(coords[i + 1]))) for i in range(0, len(coords) - 1, 2)]
                if not pts:
                    continue
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                cx = sum(xs) / len(xs)
                cy = sum(ys) / len(ys)
                # Conservative radius: farthest vertex from centroid.
                r = 0.0
                for px, py in pts:
                    r = max(r, math.hypot(px - cx, py - cy))
                out.append((layer, cx, cy, r))
    return out


def _dsn_keepout_polygons(ast: Any) -> List[Tuple[str, List[Tuple[float, float]]]]:
    # Return list of polygon keepouts: (layer_name_or_signal, [(x,y), ...]) in DSN units.
    struct = _first(ast, "structure")
    if not struct:
        return []
    out: List[Tuple[str, List[Tuple[float, float]]]] = []
    for ko in _all(struct, "keepout"):
        for child in ko[1:]:
            if not _is_list(child) or not child:
                continue
            head = _as_str(child[0])
            if head != "polygon" or len(child) < 5:
                continue
            layer = _as_str(child[1])
            coords = child[3:]
            pts = [(float(_as_str(coords[i])), float(_as_str(coords[i + 1]))) for i in range(0, len(coords) - 1, 2)]
            if len(pts) >= 3:
                out.append((layer, pts))
    return out

def _dsn_boundary_bbox(ast: Any) -> Tuple[float, float, float, float]:
    struct = _first(ast, "structure")
    if not struct:
        return (0.0, 0.0, 1000.0, 1000.0)
    boundary = _first(struct, "boundary")
    if not boundary:
        return (0.0, 0.0, 1000.0, 1000.0)
    path = _first(boundary, "path")
    if not path or len(path) < 5:
        return (0.0, 0.0, 1000.0, 1000.0)
    # (path pcb <width> x y x y ...)
    coords = path[3:]
    xs = [float(_as_str(coords[i])) for i in range(0, len(coords), 2)]
    ys = [float(_as_str(coords[i + 1])) for i in range(0, len(coords), 2)]
    return (min(xs), min(ys), max(xs), max(ys))


def _dsn_placements(ast: Any) -> Dict[str, Place]:
    placement = _first(ast, "placement")
    if not placement:
        return {}
    out: Dict[str, Place] = {}
    for place in _all(placement, "place"):
        if len(place) < 6:
            continue
        ref = _as_str(place[1])
        x = _parse_float(place[2])
        y = _parse_float(place[3])
        side = _as_str(place[4])
        rot = _parse_float(place[5])
        out[ref] = Place(ref, x, y, side, rot)
    return out


def _dsn_pin_offsets(ast: Any) -> Dict[Tuple[str, str], Tuple[float, float]]:
    # Extract (pin <padstack> <pin_no> <x> <y>) under (library (image FOOTPRINT ...))
    lib = _first(ast, "library")
    if not lib:
        return {}
    out: Dict[Tuple[str, str], Tuple[float, float]] = {}
    for image in _all(lib, "image"):
        if len(image) < 2:
            continue
        fp = _as_str(image[1])
        for pin in _all(image, "pin"):
            # Pin formats vary:
            # - (pin PADSTACK <pin_no> <x> <y>)
            # - (pin PADSTACK (rotate 180) <pin_no> <x> <y>)
            if len(pin) < 5:
                continue
            # Pick the last two atoms as coordinates.
            try:
                x = _parse_float(pin[-2])
                y = _parse_float(pin[-1])
            except Exception:
                continue
            # Find the pin number as the last non-list token before coords.
            pin_no = None
            for tok in reversed(pin[:-2]):
                if _is_list(tok):
                    continue
                if _as_str(tok) == "pin":
                    break
                pin_no = _as_str(tok)
                break
            if not pin_no:
                continue
            out[(fp, pin_no)] = (x, y)
    return out


def _dsn_component_footprints(ast: Any) -> Dict[str, str]:
    placement = _first(ast, "placement")
    if not placement:
        return {}
    out: Dict[str, str] = {}
    for comp in _all(placement, "component"):
        if len(comp) < 2:
            continue
        fp = _as_str(comp[1])
        for place in _all(comp, "place"):
            if len(place) < 2:
                continue
            ref = _as_str(place[1])
            out[ref] = fp
    return out


def _parse_pinref(tok: str) -> PinRef:
    # DSN uses "REF-PIN"
    if "-" not in tok:
        return PinRef(tok, "")
    ref, pin = tok.split("-", 1)
    return PinRef(ref, pin)


def _dsn_nets(ast: Any) -> Dict[str, List[PinRef]]:
    network = _first(ast, "network")
    if not network:
        return {}
    out: Dict[str, List[PinRef]] = {}
    for net in _all(network, "net"):
        if len(net) < 2:
            continue
        name = _as_str(net[1])
        pins: List[PinRef] = []
        for pins_node in _all(net, "pins"):
            for tok in pins_node[1:]:
                pins.append(_parse_pinref(_as_str(tok)))
        if pins:
            out[name] = pins
    return out


def convert_dsn_to_problem(
    *,
    dsn_path: Path,
    out_json: Path,
    grid_resolution_um: Optional[int] = None,
    keepout_inflate_um: Optional[int] = None,
    net_limit: Optional[int] = None,
) -> None:
    src = dsn_path.read_text(encoding="utf-8", errors="replace")
    # Some corpus entries are corrupted/binary (contain NULs). Treat these as unsupported
    # rather than producing confusing parse errors.
    if "\x00" in src:
        raise ValueError(f"{dsn_path}: contains NUL bytes; not a valid text DSN")
    # Quick sanity: Specctra DSN is parenthesized text; if parens are wildly imbalanced,
    # fail fast for clearer diagnostics.
    if src.count("(") - src.count(")") != 0:
        raise ValueError(f"{dsn_path}: unbalanced parentheses; likely corrupted DSN")
    ast = _parse_sexpr(src)
    if not ast or not _is_list(ast) or not ast[0] or _as_str(ast[0][0]).lower() not in {"pcb", "PCB", "Pcb"}:
        raise SystemExit("Expected a DSN (pcb ...) root expression")
    root = ast[0]

    res_um = _dsn_resolution_um(root)
    if grid_resolution_um is None:
        grid_resolution_um = res_um
    if grid_resolution_um <= 0:
        grid_resolution_um = 10

    layers = _dsn_layers(root)
    x0, y0, x1, y1 = _dsn_boundary_bbox(root)
    origin_um = (int(math.floor(x0)), int(math.floor(y0)))
    rule_w, rule_cl = _dsn_default_rule(root)

    placements = _dsn_placements(root)
    fp_by_ref = _dsn_component_footprints(root)
    pin_offsets = _dsn_pin_offsets(root)

    nets = _dsn_nets(root)
    if net_limit is not None:
        nets = dict(list(nets.items())[: int(net_limit)])

    def abs_pin(p: PinRef) -> Tuple[int, int]:
        place = placements.get(p.ref)
        fp = fp_by_ref.get(p.ref)
        if place is None or fp is None:
            return origin_um  # fallback
        dx, dy = pin_offsets.get((fp, p.pin), (0.0, 0.0))
        axf, ayf = _apply_place_transform(place, dx, dy)
        ax = int(round(axf))
        ay = int(round(ayf))
        return ax, ay

    def to_grid(x_um: int, y_um: int) -> Tuple[int, int]:
        gx = int(round((x_um - origin_um[0]) / grid_resolution_um))
        gy = int(round((y_um - origin_um[1]) / grid_resolution_um))
        return gx, gy

    # Build endpoints in grid coords.
    # Multi-pin nets: emit an MST over pins to produce multiple 2-terminal specs.
    net_specs: List[Dict[str, Any]] = []
    net_id_by_name: Dict[str, int] = {}
    for net_name, pins in nets.items():
        if len(pins) < 2:
            continue
        if net_name not in net_id_by_name:
            net_id_by_name[net_name] = len(net_id_by_name) + 1
        net_id = net_id_by_name[net_name]

        pts_um = [abs_pin(p) for p in pins]
        # Prim MST (O(n^2)) is fine for fixture sizes.
        n = len(pts_um)
        in_tree = [False] * n
        best = [float("inf")] * n
        parent = [-1] * n
        best[0] = 0.0
        for _ in range(n):
            u = -1
            bu = float("inf")
            for i in range(n):
                if not in_tree[i] and best[i] < bu:
                    bu = best[i]
                    u = i
            if u == -1:
                break
            in_tree[u] = True
            ux, uy = pts_um[u]
            for v in range(n):
                if in_tree[v]:
                    continue
                vx, vy = pts_um[v]
                d = (ux - vx) * (ux - vx) + (uy - vy) * (uy - vy)
                if d < best[v]:
                    best[v] = d
                    parent[v] = u

        for v in range(1, n):
            u = parent[v]
            if u < 0:
                continue
            ax_um, ay_um = pts_um[u]
            bx_um, by_um = pts_um[v]
            ax, ay = to_grid(ax_um, ay_um)
            bx, by = to_grid(bx_um, by_um)
            net_specs.append(
                {
                    "net": net_name,
                    "net_id": net_id,
                    "start": {"layer": 0, "x": ax, "y": ay},
                    "goal": {"layer": 0, "x": bx, "y": by},
                    "track_width_mm": grid_resolution_um / 1000.0,
                    "via_diameter_mm": 0.6,
                    "via_drill_mm": 0.3,
                    "uvia_diameter_mm": 0.35,
                    "uvia_drill_mm": 0.15,
                }
            )

    keepouts = _dsn_keepouts(root)
    keepout_polys = _dsn_keepout_polygons(root)
    circles: List[Dict[str, Any]] = []
    polygons: List[Dict[str, Any]] = []
    layer_ids_all = list(range(len(layers)))
    for layer_name, x, y, r in keepouts:
        lname = layer_name
        # Map keepout layers:
        # - exact layer name: that layer only
        # - "signal": all copper layers
        # Otherwise: all copper layers (safe default).
        if lname in layers:
            keep_layers = [layers.index(lname)]
        elif lname.lower() == "signal":
            keep_layers = layer_ids_all
        else:
            keep_layers = layer_ids_all
        gx, gy = to_grid(int(round(x)), int(round(y)))
        gr = int(math.ceil(r / grid_resolution_um))
        circles.append(
            {
                "net_id": 0,
                "layers": keep_layers,
                "center": {"x": gx, "y": gy},
                "r": gr,
            }
        )
    for layer_name, pts in keepout_polys:
        lname = layer_name
        if lname in layers:
            keep_layers = [layers.index(lname)]
        elif lname.lower() == "signal":
            keep_layers = layer_ids_all
        else:
            keep_layers = layer_ids_all
        gpts = [to_grid(int(round(x)), int(round(y))) for (x, y) in pts]
        polygons.append(
            {
                "net_id": 0,
                "layers": keep_layers,
                "points": [{"x": x, "y": y} for (x, y) in gpts],
            }
        )

    # Board dimensions in grid cells from boundary bbox.
    w = int(math.ceil((x1 - x0) / grid_resolution_um)) + 1
    h = int(math.ceil((y1 - y0) / grid_resolution_um)) + 1

    if keepout_inflate_um is None:
        keepout_inflate_um = grid_resolution_um

    payload: Dict[str, Any] = {
        "source": str(dsn_path),
        "format": "dsn_mvp",
        "layers": layers,
        "resolution_mm": grid_resolution_um / 1000.0,
        "origin_mm": {"x": origin_um[0] / 1000.0, "y": origin_um[1] / 1000.0},
        "width": w,
        "height": h,
        "nets": net_specs,
        "circles": circles,
        "polygons": polygons,
        "net_defaults": {
            "track_width_mm": ((rule_w if rule_w is not None else grid_resolution_um) / 1000.0),
            "clearance_mm": ((rule_cl if rule_cl is not None else keepout_inflate_um) / 1000.0),
            "via_diameter_mm": 0.6,
            "via_drill_mm": 0.3,
            "uvia_diameter_mm": 0.35,
            "uvia_drill_mm": 0.15,
        },
        "existing_vias": [],
        "pad_stacks": [],
    }

    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dsn", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--grid-resolution-um", type=int, default=None)
    ap.add_argument("--keepout-inflate-um", type=int, default=None)
    ap.add_argument("--net-limit", type=int, default=None)
    ns = ap.parse_args()
    convert_dsn_to_problem(
        dsn_path=ns.dsn,
        out_json=ns.out,
        grid_resolution_um=ns.grid_resolution_um,
        keepout_inflate_um=ns.keepout_inflate_um,
        net_limit=ns.net_limit,
    )


if __name__ == "__main__":
    main()
