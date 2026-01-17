#!/usr/bin/env python3
from __future__ import annotations

import argparse
import itertools
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
CORE = ROOT / "pardal-pcb" / "pardal_router_core"
BUILD = CORE / "build" / "bga_sweep"


@dataclass
class RunResult:
    ok: bool
    time_ms: int
    extra: dict[str, Any]


def run_cmd(cmd: list[str], *, env: dict[str, str] | None = None, timeout_s: int | None = None) -> RunResult:
    t0 = time.perf_counter()
    try:
        p = subprocess.run(
            cmd,
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        dt = int((time.perf_counter() - t0) * 1000)
        return RunResult(
            ok=(p.returncode == 0),
            time_ms=dt,
            extra={"returncode": p.returncode, "stdout": p.stdout, "stderr": p.stderr},
        )
    except subprocess.TimeoutExpired as e:
        dt = int((time.perf_counter() - t0) * 1000)
        return RunResult(
            ok=False,
            time_ms=dt,
            extra={"timeout": True, "stdout": (e.stdout or ""), "stderr": (e.stderr or "")},
        )


def ensure_built() -> None:
    subprocess.run(
        ["cargo", "build", "-q", "--bin", "pardal_route_dsn", "--bin", "pardal_dsn_check"],
        cwd=str(CORE),
        check=True,
    )


def gen_dsn(
    pin_count: int,
    out: Path,
    *,
    scenario: str,
    pitch_mil: float,
    target_pitch_mil: float,
    pad_diam_mil: float,
    via_diam_mil: float,
    gap_mil: float,
    margin_mil: float,
    clear_mil: float,
    width_mil: float,
    bga_pad_layers: str,
    tgt_pad_layers: str,
    via_costs: float,
    plane_via_costs: float,
    start_ripup_costs: float,
) -> None:
    gen = CORE / "tools" / "gen_bga_dsn.py"
    subprocess.run(
        [
            str(gen),
            "--pins",
            str(pin_count),
            "--out",
            str(out),
            "--scenario",
            scenario,
            "--pitch-mil",
            str(pitch_mil),
            "--target-pitch-mil",
            str(target_pitch_mil),
            "--pad-diam-mil",
            str(pad_diam_mil),
            "--via-diam-mil",
            str(via_diam_mil),
            "--gap-mil",
            str(gap_mil),
            "--margin-mil",
            str(margin_mil),
            "--clear-mil",
            str(clear_mil),
            "--width-mil",
            str(width_mil),
            "--bga-pad-layers",
            str(bga_pad_layers),
            "--tgt-pad-layers",
            str(tgt_pad_layers),
            "--via-costs",
            str(via_costs),
            "--plane-via-costs",
            str(plane_via_costs),
            "--start-ripup-costs",
            str(start_ripup_costs),
        ],
        cwd=str(ROOT),
        check=True,
    )


def parse_routed_count(stdout: str) -> tuple[int | None, int | None]:
    req = None
    got = None
    for line in stdout.splitlines():
        if line.startswith("requested:"):
            try:
                req = int(line.split(":")[1].strip())
            except Exception:
                pass
        if line.startswith("routed:"):
            try:
                got = int(line.split(":")[1].strip())
            except Exception:
                pass
    return req, got


def dsn_check(dsn_path: Path, *, timeout_s: int) -> tuple[RunResult, dict[str, Any] | None]:
    cmd = [
        str(CORE / "target" / "debug" / "pardal_dsn_check"),
        str(dsn_path),
        "--drc",
        "all",
        "--json",
    ]
    r = run_cmd(cmd, timeout_s=timeout_s)
    if not r.ok:
        return r, None
    try:
        return r, json.loads(r.extra.get("stdout", ""))
    except Exception:
        return r, None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pins", type=str, default="100,200")
    ap.add_argument("--timeout-s", type=int, default=40)
    ap.add_argument("--scenario", type=str, default="ring_escape_multi", choices=["ring_escape", "ring_escape_multi", "grid_match"])
    ap.add_argument("--pitch-mil", type=float, default=31.5)
    ap.add_argument("--target-pitch-mil", type=float, default=50.0)
    ap.add_argument("--pad-diam-mil", type=float, default=16.0)
    ap.add_argument("--via-diam-mil", type=float, default=6.0)
    ap.add_argument("--gap-mil", type=float, default=800.0)
    ap.add_argument("--margin-mil", type=float, default=400.0)
    ap.add_argument("--clear-mil", type=float, default=4.0)
    ap.add_argument("--width-mil", type=float, default=4.0)
    ap.add_argument("--bga-pad-layers", type=str, default="top", choices=["top", "all"])
    ap.add_argument("--tgt-pad-layers", type=str, default="top", choices=["top", "all"])
    ap.add_argument("--dsn-via-costs", type=float, default=10.0)
    ap.add_argument("--dsn-plane-via-costs", type=float, default=5.0)
    ap.add_argument("--dsn-start-ripup-costs", type=float, default=10.0)
    ap.add_argument("--out-tag", type=str, default="")

    ap.add_argument("--pitch", type=str, default="4,6,8")
    ap.add_argument("--via-cost", type=str, default="1,2,4")
    ap.add_argument("--order", type=str, default="angle,median")
    ap.add_argument("--brush-shape", type=str, default="euclidean,chebyshev")
    ap.add_argument("--dyn-rebuild-every", type=str, default="0,8,16,32")
    args = ap.parse_args()

    ensure_built()
    BUILD.mkdir(parents=True, exist_ok=True)

    pins_list = [int(x.strip()) for x in args.pins.split(",") if x.strip()]
    pitch_list = [x.strip() for x in args.pitch.split(",") if x.strip()]
    via_cost_list = [x.strip() for x in args.via_cost.split(",") if x.strip()]
    order_list = [x.strip() for x in args.order.split(",") if x.strip()]
    brush_shape_list = [x.strip() for x in args.brush_shape.split(",") if x.strip()]
    dyn_list = [x.strip() for x in args.dyn_rebuild_every.split(",") if x.strip()]

    out_tag = args.out_tag.strip() or f"{args.scenario}.t{args.timeout_s}.pins{'-'.join(map(str,pins_list))}"
    out_root = BUILD / out_tag
    out_root.mkdir(parents=True, exist_ok=True)

    # Pre-generate DSNs once per pin count.
    dsns: dict[int, Path] = {}
    for pins in pins_list:
        dsn = out_root / f"bga_{pins}.{args.scenario}.dsn"
        gen_dsn(
            pins,
            dsn,
            scenario=args.scenario,
            pitch_mil=args.pitch_mil,
            target_pitch_mil=args.target_pitch_mil,
            pad_diam_mil=args.pad_diam_mil,
            via_diam_mil=args.via_diam_mil,
            gap_mil=args.gap_mil,
            margin_mil=args.margin_mil,
            clear_mil=args.clear_mil,
            width_mil=args.width_mil,
            bga_pad_layers=args.bga_pad_layers,
            tgt_pad_layers=args.tgt_pad_layers,
            via_costs=args.dsn_via_costs,
            plane_via_costs=args.dsn_plane_via_costs,
            start_ripup_costs=args.dsn_start_ripup_costs,
        )
        dsns[pins] = dsn

    rows: list[dict[str, Any]] = []
    configs = list(itertools.product(order_list, brush_shape_list, dyn_list, pitch_list, via_cost_list))

    for (order, brush_shape, dyn_every, pitch, via_cost) in configs:
        for pins, dsn in dsns.items():
            case_dir = out_root / f"case.o{order}.b{brush_shape}.d{dyn_every}.p{pitch}.v{via_cost}.{pins}"
            case_dir.mkdir(parents=True, exist_ok=True)
            out_dsn = case_dir / f"{dsn.stem}.rust.off.dsn"

            env = dict(os.environ)
            env["PARDAL_ROUTE_ORDER"] = order
            env["PARDAL_BRUSH_SHAPE"] = brush_shape
            env["PARDAL_DYNAMIC_COST_REBUILD_EVERY"] = dyn_every
            env["PARDAL_ROUTE_DSN_OUT"] = str(out_dsn)

            cmd = [
                str(CORE / "target" / "debug" / "pardal_route_dsn"),
                str(dsn),
                "ALL",
                pitch,
                via_cost,
                str(pins),
                "auto",
                "none",
                "off",
            ]
            r = run_cmd(cmd, env=env, timeout_s=args.timeout_s)
            req, got = parse_routed_count(r.extra.get("stdout", ""))

            drc_r, drc = (None, None)
            if out_dsn.exists():
                drc_r, drc = dsn_check(out_dsn, timeout_s=args.timeout_s)

            disconnected = None
            clearance = None
            shorts = None
            if isinstance(drc, dict):
                dn = drc.get("disconnected_nets")
                disconnected = len(dn) if isinstance(dn, list) else None
                dd = drc.get("drc")
                if isinstance(dd, dict):
                    clearance = dd.get("clearance") if isinstance(dd.get("clearance"), int) else None
                    shorts = dd.get("shorts") if isinstance(dd.get("shorts"), int) else None

            row = {
                "pins": pins,
                "order": order,
                "brush_shape": brush_shape,
                "dyn_rebuild_every": int(dyn_every),
                "pitch": pitch,
                "via_cost": via_cost,
                "route_ok": r.ok,
                "route_time_ms": r.time_ms,
                "requested": req,
                "routed": got,
                "drc_ok": (drc_r.ok if drc_r is not None else None),
                "drc_time_ms": (drc_r.time_ms if drc_r is not None else None),
                "drc_clearance": clearance,
                "drc_shorts": shorts,
                "drc_disconnected_nets": disconnected,
                "notes": ("timeout" if r.extra.get("timeout") else ""),
                "out_dsn": str(out_dsn),
            }
            rows.append(row)
            (case_dir / "row.json").write_text(json.dumps(row, indent=2), encoding="utf-8")

    keys = list(rows[0].keys()) if rows else []
    csv_path = CORE / "build" / f"bga_sweep.{out_tag}.csv"
    csv_path.write_text(
        "\n".join(
            [",".join(keys)]
            + [",".join("" if r.get(k) is None else str(r.get(k)) for k in keys) for r in rows]
        )
        + "\n",
        encoding="utf-8",
    )

    def score(r: dict[str, Any]) -> tuple[int, int, int]:
        routed = int(r.get("routed") or 0)
        clear = int(r.get("drc_clearance") or 0)
        shorts = int(r.get("drc_shorts") or 0)
        return (routed, -clear, -shorts)

    md_path = CORE / "build" / f"bga_sweep.{out_tag}.md"
    top = sorted(rows, key=score, reverse=True)[:25]
    md: list[str] = []
    md.append("# BGA Sweep (Rust, internal DRC)")
    md.append("")
    md.append(f"- scenario: `{args.scenario}`")
    md.append(f"- per-run-timeout: `{args.timeout_s}s`")
    md.append(f"- pins: `{args.pins}`")
    md.append("")
    md.append("| Pins | routed/requested | time (ms) | drc_clear | drc_shorts | drc_disconnected_nets | order | brush | dyn | pitch | via_cost | out_dsn |")
    md.append("|---:|---:|---:|---:|---:|---:|---|---|---:|---:|---:|---|")
    for r in top:
        md.append(
            "| "
            + " | ".join(
                [
                    str(r["pins"]),
                    f'{r.get("routed")}/{r.get("requested")}',
                    str(r.get("route_time_ms")),
                    str(r.get("drc_clearance")),
                    str(r.get("drc_shorts")),
                    str(r.get("drc_disconnected_nets")),
                    str(r.get("order")),
                    str(r.get("brush_shape")),
                    str(r.get("dyn_rebuild_every")),
                    str(r.get("pitch")),
                    str(r.get("via_cost")),
                    f'`{r.get("out_dsn")}`',
                ]
            )
            + " |"
        )
    md.append("")
    md.append(f"- CSV: `{csv_path}`")
    md.append(f"- Cases: `{out_root}`")
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"wrote: {md_path}")


if __name__ == "__main__":
    main()

