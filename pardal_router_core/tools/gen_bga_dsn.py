#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BgaGeom:
    pins: int
    rows: int
    cols: int
    pitch_mil: float
    pad_diam_mil: float
    via_diam_mil: float
    gap_mil: float
    target_pitch_mil: float
    margin_mil: float
    clear_mil: float
    width_mil: float
    scenario: str
    bga_pad_layers: str
    tgt_pad_layers: str
    via_costs: float
    plane_via_costs: float
    start_ripup_costs: float


def pick_grid(pins: int) -> tuple[int, int]:
    rows = int(math.ceil(math.sqrt(pins)))
    cols = int(math.ceil(pins / rows))
    return rows, cols


def fmt(x: float) -> str:
    s = f"{x:.6f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _bga_pin_xy(g: BgaGeom, *, bga_x0: float, bga_y0: float, idx0: int) -> tuple[float, float]:
    r = idx0 // g.cols
    c = idx0 % g.cols
    return bga_x0 + c * g.pitch_mil, bga_y0 + r * g.pitch_mil


def gen_bga_dsn(name: str, g: BgaGeom) -> str:
    # Coordinate system: mils. DSN uses (resolution mil 1000) and floating coordinates.
    bga_w = (g.cols - 1) * g.pitch_mil
    bga_h = (g.rows - 1) * g.pitch_mil

    # Place BGA at origin, centered.
    bga_x0 = -bga_w * 0.5
    bga_y0 = -bga_h * 0.5

    bga_pts = [_bga_pin_xy(g, bga_x0=bga_x0, bga_y0=bga_y0, idx0=i) for i in range(g.pins)]

    scenario = g.scenario
    if scenario not in {"grid_match", "ring_escape", "ring_escape_multi"}:
        raise ValueError(f"unknown scenario: {scenario}")

    if g.bga_pad_layers not in {"top", "all"}:
        raise ValueError(f"unknown bga_pad_layers: {g.bga_pad_layers}")
    if g.tgt_pad_layers not in {"top", "all"}:
        raise ValueError(f"unknown tgt_pad_layers: {g.tgt_pad_layers}")

    if scenario == "grid_match":
        tgt_w = (g.cols - 1) * g.target_pitch_mil
        tgt_h = (g.rows - 1) * g.target_pitch_mil

        # Place target grid to the right.
        tgt_x0 = bga_w * 0.5 + g.gap_mil
        tgt_y0 = -tgt_h * 0.5

        def tgt_pin_xy(idx0: int) -> tuple[float, float]:
            r = idx0 // g.cols
            c = idx0 % g.cols
            return tgt_x0 + c * g.target_pitch_mil, tgt_y0 + r * g.target_pitch_mil

        tgt_pts = [tgt_pin_xy(i) for i in range(g.pins)]
    elif scenario == "ring_escape":
        # Place one "breakout" pad per ball on a ring around the BGA. The mapping keeps the cyclic
        # order of the BGA points (by angle) to reduce crossings, while keeping all targets unique.
        max_r = 0.0
        for x, y in bga_pts:
            max_r = max(max_r, math.hypot(x, y))
        # Ensure pads on the ring don't overlap: require arc length spacing to exceed pad diameter
        # plus a clearance margin. Without this, dense cases (300+ pins) become physically impossible
        # and both routers appear to "stall" with no progress.
        min_spacing = g.pad_diam_mil + 2.0 * g.clear_mil
        required_r = float(g.pins) * min_spacing / (2.0 * math.pi)
        ring_r = max(max_r + g.gap_mil, required_r)

        def key(i: int) -> tuple[float, float, int]:
            x, y = bga_pts[i]
            return (math.atan2(y, x), math.hypot(x, y), i)

        order = sorted(range(g.pins), key=key)
        tgt_pts = [(0.0, 0.0) for _ in range(g.pins)]
        for rank, idx in enumerate(order):
            a = (2.0 * math.pi * rank) / max(g.pins, 1)
            tgt_pts[idx] = (ring_r * math.cos(a), ring_r * math.sin(a))
    else:
        # Like `ring_escape`, but distribute targets across multiple concentric rings so dense cases
        # don't require an enormous outer radius (and therefore an enormous board bbox).
        max_r = 0.0
        for x, y in bga_pts:
            max_r = max(max_r, math.hypot(x, y))

        min_spacing = g.pad_diam_mil + 2.0 * g.clear_mil
        ring_step = min_spacing * 1.25
        start_r = max_r + g.gap_mil

        def ring_capacity(r: float) -> int:
            if r <= 0.0 or min_spacing <= 0.0:
                return 0
            return max(8, int((2.0 * math.pi * r) // min_spacing))

        # Assign pins (in angular order) onto ring slots.
        def key(i: int) -> tuple[float, float, int]:
            x, y = bga_pts[i]
            return (math.atan2(y, x), math.hypot(x, y), i)

        order = sorted(range(g.pins), key=key)
        tgt_pts = [(0.0, 0.0) for _ in range(g.pins)]

        remaining = g.pins
        cursor = 0
        ring_r = start_r
        while remaining > 0:
            cap = min(remaining, ring_capacity(ring_r))
            if cap <= 0:
                # Fallback: avoid infinite loop.
                cap = remaining
            for j in range(cap):
                idx = order[cursor + j]
                a = (2.0 * math.pi * j) / cap
                tgt_pts[idx] = (ring_r * math.cos(a), ring_r * math.sin(a))
            cursor += cap
            remaining -= cap
            ring_r += ring_step

    # Board bbox around both components.
    min_x = min([x for x, _ in bga_pts] + [x for x, _ in tgt_pts]) - g.margin_mil
    max_x = max([x for x, _ in bga_pts] + [x for x, _ in tgt_pts]) + g.margin_mil
    min_y = min([y for _, y in bga_pts] + [y for _, y in tgt_pts]) - g.margin_mil
    max_y = max([y for _, y in bga_pts] + [y for _, y in tgt_pts]) + g.margin_mil

    # Boundary path is a closed rectangle.
    boundary = [
        (min_x, min_y),
        (max_x, min_y),
        (max_x, max_y),
        (min_x, max_y),
        (min_x, min_y),
    ]

    # Layer rules: typical 4-layer alternation.
    layer_rules = [
        (1, "horizontal"),
        (2, "vertical"),
        (3, "horizontal"),
        (4, "vertical"),
    ]

    lines: list[str] = []
    # FreeRouting DSN header: keep it close to FreeRouting's own emitted format to avoid unit/parser quirks.
    lines.append(f'(PCB "{name}"')
    lines.append('  (parser (string_quote ") (space_in_quoted_tokens on) (case_sensitive off))')
    lines.append("  (resolution mil 2540)")
    lines.append("  (unit mil)")
    lines.append("  (structure")
    # Boundary.
    pts = " ".join(f"{fmt(x)} {fmt(y)}" for x, y in boundary)
    lines.append(f"    (boundary (path signal 0 {pts}))")
    # Via padstack(s) allowed.
    lines.append("    (via via0)")
    lines.append("    (control (via_at_smd on))")
    # Use FreeRouting's canonical rule spelling: an untyped default (wire-wire) plus typed clearances.
    # This keeps the DSN consistent between our Rust parser and FreeRouting's own DRC.
    lines.append(f"    (rule (width {fmt(g.width_mil)})(clearance {fmt(g.clear_mil)}))")
    for t in (
        "wire_via",
        "pin_pin",
        "pin_via",
        "via_via",
        "smd_pin",
        "smd_via",
        "smd_smd",
        "area_wire",
        "area_via",
    ):
        lines.append(f"    (rule (clearance {fmt(g.clear_mil)} (type {t})))")
    for layer in (1, 2, 3, 4):
        lines.append(f"    (layer {layer} (type signal))")
    lines.append("")
    lines.append("    (autoroute_settings")
    lines.append("      (vias on)")
    lines.append(f"      (via_costs {fmt(g.via_costs)})")
    lines.append(f"      (plane_via_costs {fmt(g.plane_via_costs)})")
    lines.append(f"      (start_ripup_costs {fmt(g.start_ripup_costs)})")
    lines.append("      (start_pass_no 1)")
    lines.append("      (eu.mihosoft.freerouting.autoroute on)")
    for layer, pref in layer_rules:
        lines.append(f"      (layer_rule {layer}")
        lines.append("        (active on)")
        lines.append(f"        (preferred_direction {pref})")
        lines.append("        (preferred_direction_trace_costs 1.0)")
        lines.append("        (against_preferred_direction_trace_costs 5.0)")
        lines.append("      )")
    lines.append("    )")
    lines.append("  )")
    lines.append("")
    # Placement.
    lines.append("  (placement")
    lines.append("    (component u1 (place u1 0 0 front 0))")
    lines.append("    (component j1 (place j1 0 0 front 0))")
    lines.append("  )")
    lines.append("")
    # Library / pin definitions.
    lines.append("  (library")
    lines.append("    (image u1")
    for i in range(g.pins):
        x, y = bga_pts[i]
        pin_no = i + 1
        lines.append(f"      (pin bga_pad {pin_no} {fmt(x)} {fmt(y)})")
    lines.append("    )")
    lines.append("")
    lines.append("    (image j1")
    for i in range(g.pins):
        x, y = tgt_pts[i]
        pin_no = i + 1
        lines.append(f"      (pin tgt_pad {pin_no} {fmt(x)} {fmt(y)})")
    lines.append("    )")
    lines.append("")
    # Padstacks.
    lines.append("    (padstack via0")
    for layer in (1, 2, 3, 4):
        lines.append(f"      (shape (circle {layer} {fmt(g.via_diam_mil)}))")
    lines.append("    )")
    lines.append("    (padstack bga_pad")
    if g.bga_pad_layers == "all":
        for layer in (1, 2, 3, 4):
            lines.append(f"      (shape (circle {layer} {fmt(g.pad_diam_mil)} 0 0))")
    else:
        lines.append(f"      (shape (circle 1 {fmt(g.pad_diam_mil)} 0 0))")
    lines.append("    )")
    lines.append("    (padstack tgt_pad")
    if g.tgt_pad_layers == "all":
        for layer in (1, 2, 3, 4):
            lines.append(f"      (shape (circle {layer} {fmt(g.pad_diam_mil)} 0 0))")
    else:
        lines.append(f"      (shape (circle 1 {fmt(g.pad_diam_mil)} 0 0))")
    lines.append("    )")
    lines.append("  )")
    lines.append("")
    # Network: one 2-pin net per BGA ball.
    lines.append("  (network")
    for i in range(g.pins):
        pin_no = i + 1
        lines.append(f"    (net N{pin_no} (pins u1-{pin_no} j1-{pin_no}))")
    lines.append("  )")
    lines.append(")")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pins", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--name", type=str, default=None)
    ap.add_argument(
        "--scenario",
        type=str,
        default="ring_escape",
        choices=["ring_escape", "ring_escape_multi", "grid_match"],
    )
    ap.add_argument("--pitch-mil", type=float, default=31.5)  # ~0.8mm
    ap.add_argument("--target-pitch-mil", type=float, default=50.0)
    ap.add_argument("--pad-diam-mil", type=float, default=18.0)
    ap.add_argument("--via-diam-mil", type=float, default=10.0)
    ap.add_argument("--gap-mil", type=float, default=400.0)
    ap.add_argument("--margin-mil", type=float, default=400.0)
    ap.add_argument("--clear-mil", type=float, default=4.0)
    ap.add_argument("--width-mil", type=float, default=4.0)
    ap.add_argument("--bga-pad-layers", type=str, default="top", choices=["top", "all"])
    ap.add_argument("--tgt-pad-layers", type=str, default="top", choices=["top", "all"])
    ap.add_argument("--via-costs", type=float, default=10.0)
    ap.add_argument("--plane-via-costs", type=float, default=5.0)
    ap.add_argument("--start-ripup-costs", type=float, default=10.0)
    args = ap.parse_args()

    if args.pins < 1:
        raise SystemExit("--pins must be >= 1")

    rows, cols = pick_grid(args.pins)
    name = args.name or f"bga_{args.pins}_{rows}x{cols}_{args.scenario}_4l"
    geom = BgaGeom(
        pins=args.pins,
        rows=rows,
        cols=cols,
        pitch_mil=args.pitch_mil,
        pad_diam_mil=args.pad_diam_mil,
        via_diam_mil=args.via_diam_mil,
        gap_mil=args.gap_mil,
        target_pitch_mil=args.target_pitch_mil,
        margin_mil=args.margin_mil,
        clear_mil=args.clear_mil,
        width_mil=args.width_mil,
        scenario=args.scenario,
        bga_pad_layers=args.bga_pad_layers,
        tgt_pad_layers=args.tgt_pad_layers,
        via_costs=args.via_costs,
        plane_via_costs=args.plane_via_costs,
        start_ripup_costs=args.start_ripup_costs,
    )

    txt = gen_bga_dsn(name, geom)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(txt, encoding="utf-8")


if __name__ == "__main__":
    main()
