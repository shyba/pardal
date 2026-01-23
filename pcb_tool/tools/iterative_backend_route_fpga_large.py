#!/usr/bin/env python3
"""Two-pass fpga_large routing loop.

Pass 1: Extract full problem -> route -> apply -> KiCad DRC.
Pass 2: Reroute only the failed nets (and optionally nets mentioned in DRC) on top of pass-1 PCB.

This script intentionally uses docker pcbnew for IO and the host Mojo backend for routing.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import shutil
import sys
from pathlib import Path


KICAD_IMAGE_DEFAULT = "kicad/kicad:9.0.6-full"


def _run(cmd: list[str], *, cwd: Path | None = None) -> None:
    # KiCad's pcbnew SWIG bindings are very noisy ("memory leak" messages) and can
    # dominate logs (and slow CI). Default to quiet for docker-based pcbnew runs.
    quiet = bool(cmd) and cmd[0] == "docker"
    try:
        subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            check=True,
            stdout=subprocess.DEVNULL if quiet else None,
            stderr=subprocess.DEVNULL if quiet else None,
        )
    except subprocess.CalledProcessError:
        if quiet:
            # Re-run once without suppression so the user sees the error.
            subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)
        raise


def _kicad_drc_json(*, repo_root: Path, in_pcb: Path, out_json: Path, image: str) -> dict:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{repo_root}:/work",
            "-w",
            "/work",
            image,
            "kicad-cli",
            "pcb",
            "drc",
            "--format",
            "json",
            "--output",
            f"/work/{out_json}",
            f"/work/{in_pcb}",
        ]
    )
    return json.loads(out_json.read_text(encoding="utf-8", errors="replace"))

def _drc_counts(drc: dict) -> tuple[int, int]:
    violations = drc.get("violations")
    if isinstance(violations, list):
        viol_n = len(violations)
    else:
        viol_n = -1
    unconn = drc.get("unconnected_items")
    if isinstance(unconn, list):
        unconn_n = len(unconn)
    else:
        # Some KiCad versions embed a summary only.
        unconn_n = int(drc.get("unconnected", -1)) if isinstance(drc.get("unconnected", None), int) else -1
    return viol_n, unconn_n


def _drc_type_counts(drc: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in drc.get("violations") or []:
        t = str(v.get("type") or "unknown")
        out[t] = out.get(t, 0) + 1
    return out


def _bbox_mm_from_violation(v: dict, *, pad_mm: float) -> tuple[float, float, float, float] | None:
    xs: list[float] = []
    ys: list[float] = []
    for item in v.get("items") or []:
        pos = item.get("pos") or {}
        x = pos.get("x")
        y = pos.get("y")
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            xs.append(float(x))
            ys.append(float(y))
    if not xs:
        return None
    xmin = min(xs) - float(pad_mm)
    xmax = max(xs) + float(pad_mm)
    ymin = min(ys) - float(pad_mm)
    ymax = max(ys) + float(pad_mm)
    return xmin, ymin, xmax, ymax


def _uuids_from_violation(v: dict) -> set[str]:
    out: set[str] = set()
    for it in v.get("items") or []:
        u = it.get("uuid")
        if isinstance(u, str) and u:
            out.add(u)
    return out


def _extract_problem(
    *,
    repo_root: Path,
    in_pcb: Path,
    out_problem: Path,
    image: str,
    resolution_mm: float,
    inflate_mm: float | None,
    nets_file: Path | None,
) -> None:
    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{repo_root}:/work",
        "-w",
        "/work",
        image,
        "python3",
        "pardal-pcb/pcb_tool/tools/extract_routing_problem_pcbnew.py",
        "--pcb",
        f"/work/{in_pcb}",
        "--out",
        f"/work/{out_problem}",
        "--resolution",
        str(resolution_mm),
    ]
    if inflate_mm is not None:
        cmd += ["--inflate", str(float(inflate_mm))]
    if nets_file is not None:
        cmd += ["--nets-file", f"/work/{nets_file}"]
    _run(cmd)


def _apply_routes(
    *,
    repo_root: Path,
    in_pcb: Path,
    out_pcb: Path,
    routes_json: Path,
    image: str,
    clear_nets_file: Path | None,
) -> None:
    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{repo_root}:/work",
        "-w",
        "/work",
        image,
        "python3",
        "pardal-pcb/pcb_tool/tools/apply_routes_pcbnew.py",
        "--in",
        f"/work/{in_pcb}",
        "--out",
        f"/work/{out_pcb}",
        "--routes",
        f"/work/{routes_json}",
    ]
    if clear_nets_file is not None:
        cmd += ["--clear-nets-file", f"/work/{clear_nets_file}"]
        cmd += ["--clear-tracks-only"]
    _run(cmd)


def _clear_window(
    *,
    repo_root: Path,
    in_pcb: Path,
    out_pcb: Path,
    image: str,
    bbox_mm: tuple[float, float, float, float],
    nets_file: Path | None,
    tracks_only: bool,
    out_nets_file: Path | None,
) -> None:
    xmin, ymin, xmax, ymax = bbox_mm
    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{repo_root}:/work",
        "-w",
        "/work",
        image,
        "python3",
        "pardal-pcb/pcb_tool/tools/clear_window_pcbnew.py",
        "--pcb",
        f"/work/{in_pcb}",
        "--out",
        f"/work/{out_pcb}",
        "--bbox",
        f"{xmin},{ymin},{xmax},{ymax}",
    ]
    if nets_file is not None:
        cmd += ["--nets-file", f"/work/{nets_file}"]
    if out_nets_file is not None:
        cmd += ["--out-nets-file", f"/work/{out_nets_file}"]
    if tracks_only:
        cmd += ["--tracks-only"]
    _run(cmd)


def _clear_uuids(
    *,
    repo_root: Path,
    in_pcb: Path,
    out_pcb: Path,
    image: str,
    uuids_file: Path,
    out_nets_file: Path | None,
    tracks_only: bool,
) -> None:
    # Prefer fast text-based ripup; avoids pcbnew SWIG noise/crashes.
    cmd = [
        sys.executable,
        "pardal-pcb/pcb_tool/tools/clear_uuids_text.py",
        "--pcb",
        str(in_pcb),
        "--out",
        str(out_pcb),
        "--uuids-file",
        str(uuids_file),
    ]
    if out_nets_file is not None:
        cmd += ["--out-nets-file", str(out_nets_file)]
    if tracks_only:
        cmd += ["--tracks-only"]
    _run(cmd)


def _route_mojo(*, router_bin: Path, problem_json: Path, routes_json: Path, cfg: Path) -> dict:
    routes_json.unlink(missing_ok=True)
    _run([str(router_bin), str(problem_json), str(routes_json), str(cfg)])
    return json.loads(routes_json.read_text(encoding="utf-8", errors="replace"))


def _bbox_mm_from_problem(problem: dict, net_name: str, pad_mm: float = 5.0) -> tuple[float, float, float, float] | None:
    origin = problem.get("origin_mm") or {"x": 0.0, "y": 0.0}
    ox = float(origin.get("x") or 0.0)
    oy = float(origin.get("y") or 0.0)
    res = float(problem.get("resolution_mm") or 0.2)
    for n in problem.get("nets") or []:
        if str(n.get("net")) != net_name:
            continue
        s = n.get("start") or {}
        g = n.get("goal") or {}
        sx = ox + float(s.get("x", 0)) * res
        sy = oy + float(s.get("y", 0)) * res
        gx = ox + float(g.get("x", 0)) * res
        gy = oy + float(g.get("y", 0)) * res
        minx = min(sx, gx) - pad_mm
        miny = min(sy, gy) - pad_mm
        maxx = max(sx, gx) + pad_mm
        maxy = max(sy, gy) + pad_mm
        return (minx, miny, maxx, maxy)
    return None


def _nets_overlapping_bbox(routes: dict, bbox: tuple[float, float, float, float]) -> set[str]:
    minx, miny, maxx, maxy = bbox
    out: set[str] = set()
    for t in routes.get("tracks") or []:
        try:
            net = str(t["net"])
            (sx, sy) = t["start_mm"]
            (ex, ey) = t["end_mm"]
        except Exception:
            continue
        if (minx <= sx <= maxx and miny <= sy <= maxy) or (minx <= ex <= maxx and miny <= ey <= maxy):
            out.add(net)
    for v in routes.get("vias") or []:
        try:
            net = str(v["net"])
            (x, y) = v["pos_mm"]
        except Exception:
            continue
        if minx <= x <= maxx and miny <= y <= maxy:
            out.add(net)
    return out

_NETS_PAREN_RE = re.compile(r"\(nets?\s+([^\)]+)\)")
_BRACKET_NET_RE = re.compile(r"\[([^\]]+)\]")
_WORD_NET_RE = re.compile(r"\bnet\s+([A-Za-z0-9_\-\.]+)\b", re.IGNORECASE)


def _nets_from_drc(drc: dict) -> set[str]:
    nets: set[str] = set()
    violations = drc.get("violations") or []
    for v in violations:
        # 1) Top-level description may include "(nets A and B)".
        desc = str(v.get("description") or "")
        m = _NETS_PAREN_RE.search(desc)
        if m:
            frag = m.group(1)
            for tok in re.split(r"[^A-Za-z0-9_\-\.]+", frag):
                if tok and tok.lower() not in {"and", "net", "nets"}:
                    nets.add(tok)
        # 2) Many KiCad DRC items include sub-items like "Track [U1_A15] ..." or "Via [GND] ...".
        for it in v.get("items") or []:
            idesc = str(it.get("description") or "")
            for m2 in _BRACKET_NET_RE.finditer(idesc):
                tok = m2.group(1).strip()
                if tok:
                    nets.add(tok)
            for m3 in _WORD_NET_RE.finditer(idesc):
                tok = m3.group(1).strip()
                if tok:
                    nets.add(tok)
    return nets


def _nets_from_violation(v: dict) -> set[str]:
    nets: set[str] = set()
    desc = str(v.get("description") or "")
    m = _NETS_PAREN_RE.search(desc)
    if m:
        frag = m.group(1)
        for tok in re.split(r"[^A-Za-z0-9_\-\.]+", frag):
            if tok and tok.lower() not in {"and", "net", "nets"}:
                nets.add(tok)
    for it in v.get("items") or []:
        idesc = str(it.get("description") or "")
        for m2 in _BRACKET_NET_RE.finditer(idesc):
            tok = m2.group(1).strip()
            if tok:
                nets.add(tok)
        for m3 in _WORD_NET_RE.finditer(idesc):
            tok = m3.group(1).strip()
            if tok:
                nets.add(tok)
    return nets


def _pick_violation_for_chunk(drc: dict, *, chunk_nets: set[str], types: set[str] | None) -> dict | None:
    for v in drc.get("violations") or []:
        vtype = str(v.get("type") or "")
        if types is not None and vtype not in types:
            continue
        if _nets_from_violation(v) & chunk_nets:
            return v
    return None


def _violation_groups(drc: dict, *, types: set[str] | None, max_groups: int) -> list[set[str]]:
    out: list[set[str]] = []
    for v in drc.get("violations") or []:
        vtype = str(v.get("type") or "")
        if types is not None and vtype not in types:
            continue
        nets = _nets_from_violation(v)
        # Ignore groups that don't look like real nets.
        nets = {n for n in nets if n and n != "<no net>"}
        if not nets:
            continue
        out.append(nets)
        if len(out) >= max_groups:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    ap.add_argument("--in", dest="in_pcb", type=Path, required=True, help="Input PCB for pass1/2 pipeline.")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument(
        "--start-pcb",
        type=Path,
        default=None,
        help="If set, skip pass1/pass2 and start pass3 cleanup from this PCB (still requires --cfg-pass3).",
    )
    ap.add_argument("--cfg-pass1", type=Path, required=True)
    ap.add_argument("--cfg-pass2", type=Path, required=True)
    ap.add_argument(
        "--cfg-pass3",
        type=Path,
        default=None,
        help="Optional cleanup pass config. When set with --pass3-rounds>0, reroutes nets mentioned in DRC.",
    )
    ap.add_argument("--resolution", type=float, default=0.2)
    ap.add_argument("--inflate", type=float, default=None)
    ap.add_argument(
        "--pass2-resolution",
        type=float,
        default=None,
        help="Optional different grid resolution (mm) for pass2 extraction/routing. "
        "If omitted, uses --resolution.",
    )
    ap.add_argument(
        "--pass2-inflate",
        type=float,
        default=None,
        help="Optional different inflate (mm) for pass2 extraction/routing. If omitted, uses --inflate.",
    )
    ap.add_argument("--pass3-resolution", type=float, default=None, help="Optional grid resolution (mm) for pass3.")
    ap.add_argument("--pass3-inflate", type=float, default=None, help="Optional inflate (mm) for pass3.")
    ap.add_argument("--kicad-image", type=str, default=KICAD_IMAGE_DEFAULT)
    ap.add_argument("--include-drc-nets", action="store_true")
    ap.add_argument(
        "--pass2-max-nets",
        type=int,
        default=128,
        help="Cap the number of nets rerouted in pass 2 (including any expanded neighbors).",
    )
    ap.add_argument(
        "--pass2-bbox-pad-mm",
        type=float,
        default=2.0,
        help="Padding (mm) around each failed net's start/goal bbox when collecting neighbor nets to reroute.",
    )
    ap.add_argument(
        "--pass2-rounds",
        type=int,
        default=1,
        help="Number of chunked reroute rounds to run after pass1. Each round reroutes chunks of the failed set.",
    )
    ap.add_argument(
        "--pass2-chunk-size",
        type=int,
        default=24,
        help="How many failed nets to include per chunk when chunked rerouting is enabled.",
    )
    ap.add_argument(
        "--pass2-drc-every",
        type=int,
        default=0,
        help="If >0, run KiCad DRC every N chunks (for progress tracking).",
    )
    ap.add_argument(
        "--pass2-eval-drc",
        action="store_true",
        help="Run KiCad DRC after each chunk and only accept the chunk if it improves (or keeps) "
        "unconnected/violations. This is slower but prevents DRC regressions.",
    )
    ap.add_argument(
        "--pass2-accept-eps",
        type=int,
        default=0,
        help="Allow violations to increase by at most this amount when unconnected decreases (default 0).",
    )
    ap.add_argument(
        "--pass2-stop-on-no-improve",
        action="store_true",
        help="Stop early if a full round yields no reduction in unconnected items (requires final DRC per round).",
    )
    ap.add_argument("--pass3-rounds", type=int, default=0, help="Number of cleanup rounds to run (requires --cfg-pass3).")
    ap.add_argument("--pass3-chunk-size", type=int, default=32, help="Chunk size for pass3 reroutes.")
    ap.add_argument("--pass3-max-nets", type=int, default=128, help="Cap the number of nets rerouted per pass3 round.")
    ap.add_argument(
        "--pass3-window-ripup",
        action="store_true",
        help="When --pass3-mode=violations, rip up tracks in each violation window before rerouting.",
    )
    ap.add_argument(
        "--pass3-window-pad-mm",
        type=float,
        default=2.0,
        help="When --pass3-window-ripup is set, expand each violation item's bbox by this padding (mm).",
    )
    ap.add_argument(
        "--pass3-window-tracks-only",
        action="store_true",
        help="When used with --pass3-window-ripup, only delete tracks (preserve vias). Recommended for via-in-pad seeds.",
    )
    ap.add_argument(
        "--pass3-uuid-delete-vias-for",
        type=str,
        default="hole_clearance,hole_to_hole",
        help="Comma-separated DRC violation types for which UUID-ripup is allowed to delete vias "
        "(even if --pass3-window-tracks-only is set). Useful for fixing hole clearance violations.",
    )
    ap.add_argument(
        "--pass3-window-clear-all",
        action="store_true",
        help="When used with --pass3-window-ripup, clear tracks in the violation window for ALL nets (not just chunk nets). "
        "The router will then reroute the nets that were actually affected by the ripup.",
    )
    ap.add_argument(
        "--pass3-ripup-mode",
        choices=["none", "bbox", "uuid"],
        default="bbox",
        help="How to rip up around each violation when --pass3-window-ripup is enabled.",
    )
    ap.add_argument(
        "--pass3-bundle-size",
        type=int,
        default=1,
        help="Number of pass3 chunks to apply before evaluating DRC and accepting/rolling back as a unit. "
        "Allows multi-step DRC repair where intermediate chunks may temporarily worsen DRC.",
    )
    ap.add_argument(
        "--pass3-bundle-accept-eps",
        type=int,
        default=0,
        help="When pass3-bundle-size>1, allow total violation count to increase by at most this amount "
        "if unconnected decreases at the end of the bundle.",
    )
    ap.add_argument(
        "--pass3-mode",
        choices=["nets", "violations"],
        default="nets",
        help="Select pass3 targets by either net list from DRC (nets) or by per-violation net groups (violations).",
    )
    ap.add_argument(
        "--pass3-focus-types",
        type=str,
        default="shorting_items,hole_clearance,hole_to_hole,clearance",
        help="Comma-separated DRC violation types to focus on when --pass3-mode=violations.",
    )
    ap.add_argument(
        "--pass3-pick-one-net",
        action="store_true",
        help="When --pass3-mode=violations, reroute only one net from each violation group (heuristic).",
    )
    ap.add_argument(
        "--pass3-max-groups",
        type=int,
        default=64,
        help="Maximum number of violation groups to attempt per pass3 round.",
    )
    ap.add_argument(
        "--pass3-eval-drc",
        action="store_true",
        help="Evaluate DRC per chunk in pass3 and only accept improvements (recommended).",
    )
    ap.add_argument(
        "--pass3-accept-types",
        type=str,
        default="",
        help="Comma-separated violation types to prioritize improving in pass3 (e.g. shorting_items,hole_clearance). "
        "When set, pass3 accepts a chunk if unconnected doesn't increase and at least one of these types decreases.",
    )
    ap.add_argument(
        "--pass3-accept-eps",
        type=int,
        default=0,
        help="Allow total violation count to increase by at most this amount when pass3 achieves the accept-types improvement.",
    )
    ap.add_argument(
        "--pass3-clear-nets",
        action="store_true",
        help="Before applying pass3 chunk routes, clear existing tracks (not vias) for the chunk net set.",
    )
    ap.add_argument(
        "--clear-pass2-nets",
        action="store_true",
        help="If set, delete existing tracks/vias for pass-2 net set before applying pass-2 routes. "
        "Default is off because many boards use pre-existing via-in-pad seeds on those nets.",
    )
    args = ap.parse_args()

    repo_root: Path = args.repo_root.resolve()
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    router_bin = repo_root / "pardal-pcb" / "pardal_router_mojo" / "build" / "pardal-router-mojo"
    if not router_bin.exists():
        _run([str(repo_root / "pardal-pcb" / "pardal_router_mojo" / "build.sh")], cwd=repo_root / "pardal-pcb" / "pardal_router_mojo")
    if not router_bin.exists():
        raise SystemExit(f"Missing router binary: {router_bin}")

    pcb1 = out_dir / "pass1.kicad_pcb"
    prob1 = out_dir / "pass1.problem.json"
    routes1 = out_dir / "pass1.routes.json"
    drc1 = out_dir / "pass1.drc.json"
    r1: dict = {}
    d1: dict = {}
    failed_nets: set[str] = set()

    if args.start_pcb is None:
        _extract_problem(
            repo_root=repo_root,
            in_pcb=args.in_pcb,
            out_problem=prob1,
            image=args.kicad_image,
            resolution_mm=float(args.resolution),
            inflate_mm=args.inflate,
            nets_file=None,
        )
        r1 = _route_mojo(router_bin=router_bin, problem_json=prob1, routes_json=routes1, cfg=args.cfg_pass1)
        _apply_routes(
            repo_root=repo_root,
            in_pcb=args.in_pcb,
            out_pcb=pcb1,
            routes_json=routes1,
            image=args.kicad_image,
            clear_nets_file=None,
        )
        d1 = _kicad_drc_json(repo_root=repo_root, in_pcb=pcb1, out_json=drc1, image=args.kicad_image)

        failed_nets = set(r1.get("failed_nets") or [])
        # Expand reroute set to include nearby nets. Rerouting only the failed nets
        # tends to stall because the required corridors are owned by other already-
        # routed nets that never get reconsidered.
        try:
            prob1_payload = json.loads(prob1.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            prob1_payload = {}
        expanded = set(failed_nets)
        if prob1_payload:
            for net in list(failed_nets):
                if len(expanded) >= int(args.pass2_max_nets):
                    break
                bb = _bbox_mm_from_problem(prob1_payload, net, pad_mm=float(args.pass2_bbox_pad_mm))
                if bb is None:
                    continue
                for n2 in sorted(_nets_overlapping_bbox(r1, bb)):
                    expanded.add(n2)
                    if len(expanded) >= int(args.pass2_max_nets):
                        break
        failed_nets = expanded
        if args.include_drc_nets:
            for n2 in sorted(_nets_from_drc(d1)):
                failed_nets.add(n2)
                if len(failed_nets) >= int(args.pass2_max_nets):
                    break
    else:
        # Start from an already-routed board (typically the output of a prior run).
        pcb1 = args.start_pcb
        d1 = _kicad_drc_json(repo_root=repo_root, in_pcb=pcb1, out_json=drc1, image=args.kicad_image)

    nets_file = out_dir / "pass2.nets.txt"
    nets_file.write_text("\n".join(sorted(failed_nets)) + ("\n" if failed_nets else ""), encoding="utf-8")

    # Pass 2: chunked reroute loop. We reuse the current PCB as the base and
    # reroute a bounded set of nets per chunk to avoid blowing up the whole board.
    current_pcb = pcb1
    current_drc = d1
    cur_viol, cur_unconn = _drc_counts(current_drc)
    round_idx = 0
    failed_order = sorted(failed_nets)
    while round_idx < int(args.pass2_rounds) and failed_order:
        out_round_dir = out_dir / f"pass2_round{round_idx+1}"
        out_round_dir.mkdir(parents=True, exist_ok=True)

        # Optional: record DRC baseline for the round.
        if args.pass2_stop_on_no_improve:
            _v0, baseline_unconn = _drc_counts(current_drc)
        else:
            baseline_unconn = -1

        chunks = [
            failed_order[i : i + int(args.pass2_chunk_size)]
            for i in range(0, len(failed_order), int(args.pass2_chunk_size))
        ]
        chunk_idx = 0
        for chunk in chunks:
            chunk_dir = out_round_dir / f"chunk{chunk_idx+1:03d}"
            chunk_dir.mkdir(parents=True, exist_ok=True)

            prob2 = chunk_dir / "problem.json"
            routes2 = chunk_dir / "routes.json"
            pcb2 = chunk_dir / "pcb.kicad_pcb"
            drc2 = chunk_dir / "drc.json"

            # Expand the chunk with local neighbors, but cap total.
            try:
                # We extract full problem for bbox lookup (fast; inside docker but manageable).
                # Use pass1.problem.json as bbox reference (stable endpoints).
                prob_ref = json.loads(prob1.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                prob_ref = {}
            selected = set(chunk)
            if prob_ref:
                for net in list(chunk):
                    if len(selected) >= int(args.pass2_max_nets):
                        break
                    bb = _bbox_mm_from_problem(prob_ref, net, pad_mm=float(args.pass2_bbox_pad_mm))
                    if bb is None:
                        continue
                    for n2 in sorted(_nets_overlapping_bbox(r1, bb)):
                        selected.add(n2)
                        if len(selected) >= int(args.pass2_max_nets):
                            break
            nets_file2 = chunk_dir / "nets.txt"
            nets_file2.write_text("\n".join(sorted(selected)) + "\n", encoding="utf-8")

            clear_file = None
            if args.clear_pass2_nets:
                clear_file = chunk_dir / "clear_nets.txt"
                clear_file.write_text(nets_file2.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")

            _extract_problem(
                repo_root=repo_root,
                in_pcb=current_pcb,
                out_problem=prob2,
                image=args.kicad_image,
                resolution_mm=float(args.pass2_resolution if args.pass2_resolution is not None else args.resolution),
                inflate_mm=args.pass2_inflate if args.pass2_inflate is not None else args.inflate,
                nets_file=nets_file2,
            )
            _route_mojo(router_bin=router_bin, problem_json=prob2, routes_json=routes2, cfg=args.cfg_pass2)
            _apply_routes(
                repo_root=repo_root,
                in_pcb=current_pcb,
                out_pcb=pcb2,
                routes_json=routes2,
                image=args.kicad_image,
                clear_nets_file=clear_file,
            )

            accept = True
            if args.pass2_eval_drc:
                cand_drc = _kicad_drc_json(repo_root=repo_root, in_pcb=pcb2, out_json=drc2, image=args.kicad_image)
                cand_viol, cand_unconn = _drc_counts(cand_drc)
                # Accept if unconnected decreases, or if unconnected is equal and violations decrease.
                if cur_unconn >= 0 and cand_unconn >= 0:
                    if cand_unconn < cur_unconn:
                        # Allow a small violation regression if connectivity improves.
                        if cur_viol >= 0 and cand_viol >= 0 and cand_viol > cur_viol + int(args.pass2_accept_eps):
                            accept = False
                        else:
                            accept = True
                    elif cand_unconn == cur_unconn:
                        if cur_viol >= 0 and cand_viol >= 0 and cand_viol <= cur_viol:
                            accept = True
                        else:
                            accept = False
                    else:
                        accept = False
                else:
                    # If we can't parse counts, be conservative and reject.
                    accept = False

                if accept:
                    current_drc = cand_drc
                    cur_viol, cur_unconn = cand_viol, cand_unconn
                else:
                    # Keep the previous PCB; discard candidate.
                    pcb2.unlink(missing_ok=True)

            if accept:
                current_pcb = pcb2
            chunk_idx += 1

            if (not args.pass2_eval_drc) and int(args.pass2_drc_every) > 0 and (chunk_idx % int(args.pass2_drc_every)) == 0:
                current_drc = _kicad_drc_json(repo_root=repo_root, in_pcb=current_pcb, out_json=drc2, image=args.kicad_image)
                cur_viol, cur_unconn = _drc_counts(current_drc)

        # End of round: always run DRC once for summary/progress.
        current_drc = _kicad_drc_json(repo_root=repo_root, in_pcb=current_pcb, out_json=(out_round_dir / "round.drc.json"), image=args.kicad_image)
        cur_viol, cur_unconn = _drc_counts(current_drc)

        if args.pass2_stop_on_no_improve and baseline_unconn >= 0:
            # Attempt to extract unconnected count from the DRC JSON. If missing, keep going.
            _v1, unconn = _drc_counts(current_drc)
            if unconn >= 0 and unconn >= baseline_unconn:
                break

        round_idx += 1

    # Final output for compatibility with earlier runs.
    shutil.copyfile(current_pcb, out_dir / "pass2.kicad_pcb")
    # The project files (.kicad_pro/.kicad_prl) are already copied per-apply.
    (out_dir / "pass2.drc.json").write_text(json.dumps(current_drc, indent=2, sort_keys=True), encoding="utf-8")

    # Pass 3: cleanup. Reroute nets mentioned in DRC and accept only if DRC improves.
    if args.cfg_pass3 is not None and int(args.pass3_rounds) > 0:
        pass3_round = 0
        while pass3_round < int(args.pass3_rounds):
            round_dir = out_dir / f"pass3_round{pass3_round+1}"
            round_dir.mkdir(parents=True, exist_ok=True)
            viol0, unconn0 = _drc_counts(current_drc)
            type0 = _drc_type_counts(current_drc)
            accept_types = {t.strip() for t in str(args.pass3_accept_types).split(",") if t.strip()}

            chunks: list[list[str]] = []
            if args.pass3_mode == "violations":
                types = {t.strip() for t in str(args.pass3_focus_types).split(",") if t.strip()}
                groups = _violation_groups(current_drc, types=types if types else None, max_groups=int(args.pass3_max_groups))
                for g in groups:
                    nets = sorted(g)
                    if args.pass3_pick_one_net and nets:
                        # Simple heuristic: prefer rerouting the second net if present (often the track net
                        # rather than the via-in-pad net for shorting_items).
                        pick = nets[1] if len(nets) > 1 else nets[0]
                        chunks.append([pick])
                    else:
                        chunks.append(nets[: int(args.pass3_max_nets)])
            else:
                drc_nets = sorted(_nets_from_drc(current_drc))
                if not drc_nets:
                    break
                drc_nets = drc_nets[: int(args.pass3_max_nets)]
                chunks = [
                    drc_nets[i : i + int(args.pass3_chunk_size)]
                    for i in range(0, len(drc_nets), int(args.pass3_chunk_size))
                ]
            if not chunks:
                break
            chunk_idx = 0
            bundle_size = max(1, int(args.pass3_bundle_size))
            bundle_start_pcb = current_pcb
            bundle_start_drc = current_drc
            b_viol0, b_unconn0 = viol0, unconn0
            b_type0 = type0

            # Optimization: when doing UUID ripup, run the whole bundle as a single extraction/router/apply
            # to avoid per-chunk docker overhead.
            if (
                args.pass3_eval_drc
                and args.pass3_mode == "violations"
                and args.pass3_window_ripup
                and args.pass3_ripup_mode == "uuid"
                and bundle_size > 1
            ):
                allow_vias_for = {
                    t.strip() for t in str(args.pass3_uuid_delete_vias_for).split(",") if t.strip()
                }
                focus_types = {t.strip() for t in str(args.pass3_focus_types).split(",") if t.strip()}
                bundles = [chunks[i : i + bundle_size] for i in range(0, len(chunks), bundle_size)]
                bundle_no = 0
                for bundle_chunks in bundles:
                    bundle_dir = round_dir / f"bundle{bundle_no+1:03d}"
                    bundle_dir.mkdir(parents=True, exist_ok=True)

                    # Collect UUIDs from the matched violations and compute a conservative tracks_only setting.
                    all_uuids: set[str] = set()
                    any_allows_vias = False
                    for ch in bundle_chunks:
                        v = _pick_violation_for_chunk(
                            current_drc,
                            chunk_nets=set(ch),
                            types=focus_types if focus_types else None,
                        )
                        if v is None:
                            continue
                        all_uuids |= _uuids_from_violation(v)
                        if str(v.get("type") or "") in allow_vias_for:
                            any_allows_vias = True

                    if not all_uuids:
                        bundle_no += 1
                        continue

                    uuids_file = bundle_dir / "uuids.txt"
                    uuids_file.write_text("\n".join(sorted(all_uuids)) + "\n", encoding="utf-8")

                    ripped = bundle_dir / "ripped.kicad_pcb"
                    touched = bundle_dir / "touched_nets.txt"
                    tracks_only = bool(args.pass3_window_tracks_only) and (not any_allows_vias)
                    _clear_uuids(
                        repo_root=repo_root,
                        in_pcb=current_pcb,
                        out_pcb=ripped,
                        image=args.kicad_image,
                        uuids_file=uuids_file,
                        out_nets_file=touched,
                        tracks_only=tracks_only,
                    )

                    # Route nets for both the original bundle chunk nets and anything we touched by ripup.
                    extra: set[str] = set()
                    if touched.exists():
                        extra |= {
                            ln.strip()
                            for ln in touched.read_text(encoding="utf-8", errors="replace").splitlines()
                            if ln.strip()
                        }
                    for ch in bundle_chunks:
                        extra |= set(ch)
                    extra_list = sorted(extra)[: int(args.pass3_max_nets)]
                    nets_file3 = bundle_dir / "nets.txt"
                    nets_file3.write_text("\n".join(extra_list) + "\n", encoding="utf-8")

                    prob3 = bundle_dir / "problem.json"
                    routes3 = bundle_dir / "routes.json"
                    pcb3 = bundle_dir / "pcb.kicad_pcb"
                    drc3 = bundle_dir / "drc.json"

                    _extract_problem(
                        repo_root=repo_root,
                        in_pcb=ripped,
                        out_problem=prob3,
                        image=args.kicad_image,
                        resolution_mm=float(args.pass3_resolution if args.pass3_resolution is not None else args.resolution),
                        inflate_mm=args.pass3_inflate if args.pass3_inflate is not None else args.inflate,
                        nets_file=nets_file3,
                    )
                    _route_mojo(router_bin=router_bin, problem_json=prob3, routes_json=routes3, cfg=args.cfg_pass3)
                    _apply_routes(
                        repo_root=repo_root,
                        in_pcb=ripped,
                        out_pcb=pcb3,
                        routes_json=routes3,
                        image=args.kicad_image,
                        clear_nets_file=(nets_file3 if args.pass3_clear_nets else None),
                    )

                    cand_drc = _kicad_drc_json(repo_root=repo_root, in_pcb=pcb3, out_json=drc3, image=args.kicad_image)
                    cand_viol, cand_unconn = _drc_counts(cand_drc)
                    type1 = _drc_type_counts(cand_drc)

                    accept = True
                    if b_unconn0 >= 0 and cand_unconn >= 0 and cand_unconn > b_unconn0:
                        accept = False
                    else:
                        if b_unconn0 >= 0 and cand_unconn >= 0 and cand_unconn < b_unconn0:
                            if b_viol0 >= 0 and cand_viol >= 0 and cand_viol > b_viol0 + int(args.pass3_bundle_accept_eps):
                                accept = False
                        if accept:
                            improved = False
                            if accept_types:
                                for t in accept_types:
                                    if type1.get(t, 0) < b_type0.get(t, 0):
                                        improved = True
                                        break
                            if improved:
                                if b_viol0 >= 0 and cand_viol >= 0 and cand_viol > b_viol0 + int(args.pass3_accept_eps):
                                    accept = False
                            else:
                                if b_viol0 >= 0 and cand_viol >= 0 and cand_viol < b_viol0:
                                    accept = True
                                else:
                                    accept = False

                    if accept:
                        current_pcb = pcb3
                        current_drc = cand_drc
                        viol0, unconn0 = cand_viol, cand_unconn
                        type0 = type1
                        bundle_start_pcb = current_pcb
                        bundle_start_drc = current_drc
                        b_viol0, b_unconn0 = viol0, unconn0
                        b_type0 = type0
                    else:
                        current_pcb = bundle_start_pcb
                        current_drc = bundle_start_drc
                        viol0, unconn0 = b_viol0, b_unconn0
                        type0 = b_type0

                    bundle_no += 1

                current_drc = _kicad_drc_json(
                    repo_root=repo_root,
                    in_pcb=current_pcb,
                    out_json=(round_dir / "round.drc.json"),
                    image=args.kicad_image,
                )
                viol1, unconn1 = _drc_counts(current_drc)
                if viol0 >= 0 and viol1 >= 0 and viol1 >= viol0:
                    break
                if unconn0 >= 0 and unconn1 >= 0 and unconn1 > unconn0:
                    break
                pass3_round += 1
                continue

            bundle_idx = 0
            for chunk in chunks:
                chunk_dir = round_dir / f"chunk{chunk_idx+1:03d}"
                chunk_dir.mkdir(parents=True, exist_ok=True)
                nets_file3 = chunk_dir / "nets.txt"
                nets_file3.write_text("\n".join(chunk) + "\n", encoding="utf-8")

                prob3 = chunk_dir / "problem.json"
                routes3 = chunk_dir / "routes.json"
                pcb3 = chunk_dir / "pcb.kicad_pcb"
                drc3 = chunk_dir / "drc.json"

                pcb_in = current_pcb
                if args.pass3_window_ripup and args.pass3_mode == "violations":
                    types = {t.strip() for t in str(args.pass3_focus_types).split(",") if t.strip()}
                    v = _pick_violation_for_chunk(
                        current_drc,
                        chunk_nets=set(chunk),
                        types=types if types else None,
                    )
                    if v is not None:
                        ripped = chunk_dir / "ripped.kicad_pcb"
                        touched = chunk_dir / "touched_nets.txt"
                        if args.pass3_ripup_mode == "uuid":
                            uuids = sorted(_uuids_from_violation(v))
                            if uuids:
                                uuids_file = chunk_dir / "uuids.txt"
                                uuids_file.write_text("\n".join(uuids) + "\n", encoding="utf-8")
                                allow_vias_for = {
                                    t.strip()
                                    for t in str(args.pass3_uuid_delete_vias_for).split(",")
                                    if t.strip()
                                }
                                tracks_only = bool(args.pass3_window_tracks_only)
                                if str(v.get("type") or "") in allow_vias_for:
                                    tracks_only = False
                                _clear_uuids(
                                    repo_root=repo_root,
                                    in_pcb=current_pcb,
                                    out_pcb=ripped,
                                    image=args.kicad_image,
                                    uuids_file=uuids_file,
                                    out_nets_file=touched,
                                    tracks_only=tracks_only,
                                )
                                pcb_in = ripped
                                if touched.exists():
                                    extra = {
                                        ln.strip()
                                        for ln in touched.read_text(encoding="utf-8", errors="replace").splitlines()
                                        if ln.strip()
                                    }
                                    extra |= set(chunk)
                                    extra_list = sorted(extra)[: int(args.pass3_max_nets)]
                                    nets_file3.write_text("\n".join(extra_list) + "\n", encoding="utf-8")
                        else:
                            bb = _bbox_mm_from_violation(v, pad_mm=float(args.pass3_window_pad_mm))
                            if bb is not None:
                                _clear_window(
                                    repo_root=repo_root,
                                    in_pcb=current_pcb,
                                    out_pcb=ripped,
                                    image=args.kicad_image,
                                    bbox_mm=bb,
                                    nets_file=None if args.pass3_window_clear_all else nets_file3,
                                    tracks_only=bool(args.pass3_window_tracks_only),
                                    out_nets_file=touched,
                                )
                                pcb_in = ripped

                        if args.pass3_window_clear_all and touched.exists():
                            extra = {
                                ln.strip()
                                for ln in touched.read_text(encoding="utf-8", errors="replace").splitlines()
                                if ln.strip()
                            }
                            extra |= set(chunk)
                            extra_list = sorted(extra)[: int(args.pass3_max_nets)]
                            nets_file3.write_text("\n".join(extra_list) + "\n", encoding="utf-8")

                _extract_problem(
                    repo_root=repo_root,
                    in_pcb=pcb_in,
                    out_problem=prob3,
                    image=args.kicad_image,
                    resolution_mm=float(args.pass3_resolution if args.pass3_resolution is not None else args.resolution),
                    inflate_mm=args.pass3_inflate if args.pass3_inflate is not None else args.inflate,
                    nets_file=nets_file3,
                )
                _route_mojo(router_bin=router_bin, problem_json=prob3, routes_json=routes3, cfg=args.cfg_pass3)
                _apply_routes(
                    repo_root=repo_root,
                    in_pcb=pcb_in,
                    out_pcb=pcb3,
                    routes_json=routes3,
                    image=args.kicad_image,
                    clear_nets_file=(nets_file3 if args.pass3_clear_nets else None),
                )

                # Apply candidate without immediate DRC evaluation when bundling.
                current_pcb = pcb3
                chunk_idx += 1
                bundle_idx += 1

                do_eval = bool(args.pass3_eval_drc) and (bundle_idx >= bundle_size or chunk_idx >= len(chunks))
                if do_eval:
                    cand_drc = _kicad_drc_json(repo_root=repo_root, in_pcb=current_pcb, out_json=drc3, image=args.kicad_image)
                    cand_viol, cand_unconn = _drc_counts(cand_drc)
                    type1 = _drc_type_counts(cand_drc)

                    accept = True
                    if b_unconn0 >= 0 and cand_unconn >= 0 and cand_unconn > b_unconn0:
                        accept = False
                    else:
                        # If connectivity improves, allow small violation regression.
                        if b_unconn0 >= 0 and cand_unconn >= 0 and cand_unconn < b_unconn0:
                            if b_viol0 >= 0 and cand_viol >= 0 and cand_viol > b_viol0 + int(args.pass3_bundle_accept_eps):
                                accept = False
                        # Otherwise use existing accept criteria against bundle baseline.
                        if accept:
                            improved = False
                            if accept_types:
                                for t in accept_types:
                                    if type1.get(t, 0) < b_type0.get(t, 0):
                                        improved = True
                                        break
                            if improved:
                                if b_viol0 >= 0 and cand_viol >= 0 and cand_viol > b_viol0 + int(args.pass3_accept_eps):
                                    accept = False
                            else:
                                if b_viol0 >= 0 and cand_viol >= 0 and cand_viol < b_viol0:
                                    accept = True
                                else:
                                    accept = False

                    if accept:
                        current_drc = cand_drc
                        viol0, unconn0 = cand_viol, cand_unconn
                        type0 = type1
                        bundle_start_pcb = current_pcb
                        bundle_start_drc = current_drc
                        b_viol0, b_unconn0 = viol0, unconn0
                        b_type0 = type0
                    else:
                        # Roll back to the bundle baseline PCB.
                        current_pcb = bundle_start_pcb
                        current_drc = bundle_start_drc
                        viol0, unconn0 = b_viol0, b_unconn0
                        type0 = b_type0

                    bundle_idx = 0

            current_drc = _kicad_drc_json(repo_root=repo_root, in_pcb=current_pcb, out_json=(round_dir / "round.drc.json"), image=args.kicad_image)
            viol1, unconn1 = _drc_counts(current_drc)
            if viol0 >= 0 and viol1 >= 0 and viol1 >= viol0:
                break
            if unconn0 >= 0 and unconn1 >= 0 and unconn1 > unconn0:
                break
            pass3_round += 1

        shutil.copyfile(current_pcb, out_dir / "pass3.kicad_pcb")
        (out_dir / "pass3.drc.json").write_text(json.dumps(current_drc, indent=2, sort_keys=True), encoding="utf-8")

    print(out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
