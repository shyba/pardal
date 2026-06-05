#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def _run(cmd: list[str], *, cwd: Path, timeout_s: Optional[float] = None) -> float:
    t0 = time.perf_counter()
    if timeout_s is None:
        subprocess.run(cmd, cwd=cwd, check=True)
        return time.perf_counter() - t0

    proc = subprocess.Popen(cmd, cwd=cwd, start_new_session=True)
    try:
        rc = proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        raise
    if rc != 0:
        raise subprocess.CalledProcessError(rc, cmd)
    return time.perf_counter() - t0


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _drc_summary(drc_json: Path) -> tuple[int, int]:
    payload = _load_json(drc_json)
    violations = payload.get("violations", []) or []
    unconnected = payload.get("unconnected_items", []) or []
    return len(violations), len(unconnected)


def _router_summary(routes_json: Path) -> Dict[str, Any]:
    payload = _load_json(routes_json)
    failed = payload.get("failed_nets", []) or []
    stats_total = payload.get("stats_total") or {}
    astar = (stats_total.get("astar") or {}) if isinstance(stats_total, dict) else {}
    return {
        "failed_nets": len(failed),
        "completed_specs": None,
        "total_specs": None,
        "elapsed_ms_router_reported": stats_total.get("elapsed_ms"),
        "astar_heap_pop": astar.get("heap_pop"),
        "astar_heap_push": astar.get("heap_push"),
        "astar_relax_success": astar.get("relax_success"),
        "astar_relax_attempts": astar.get("relax_attempts"),
        "astar_rej_bounds": astar.get("rej_bounds"),
        "astar_rej_base_blocked": astar.get("rej_base_blocked"),
        "astar_rej_forbidden": astar.get("rej_forbidden"),
        "astar_rej_occ_other": astar.get("rej_occ_other"),
        "astar_rej_ko_track": astar.get("rej_ko_track"),
        "astar_rej_ko_via": astar.get("rej_ko_via"),
    }


def _router_summary_progress(progress_json: Path) -> Dict[str, Any]:
    payload = _load_json(progress_json)
    stats_total = payload.get("stats_total") or {}
    astar = (stats_total.get("astar") or {}) if isinstance(stats_total, dict) else {}
    return {
        "failed_nets": payload.get("failed_specs"),
        "completed_specs": payload.get("completed_specs"),
        "total_specs": payload.get("total_specs"),
        "elapsed_ms_router_reported": stats_total.get("elapsed_ms"),
        "astar_heap_pop": astar.get("heap_pop"),
        "astar_heap_push": astar.get("heap_push"),
        "astar_relax_success": astar.get("relax_success"),
        "astar_relax_attempts": astar.get("relax_attempts"),
        "astar_rej_bounds": astar.get("rej_bounds"),
        "astar_rej_base_blocked": astar.get("rej_base_blocked"),
        "astar_rej_forbidden": astar.get("rej_forbidden"),
        "astar_rej_occ_other": astar.get("rej_occ_other"),
        "astar_rej_ko_track": astar.get("rej_ko_track"),
        "astar_rej_ko_via": astar.get("rej_ko_via"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Run Rust-router + KiCad DRC benchmark and append to CSV.")
    ap.add_argument("--pcb", type=Path, required=True, help="Input .kicad_pcb")
    ap.add_argument("--out", type=Path, required=True, help="Output .kicad_pcb")
    ap.add_argument("--cfg", type=Path, default=None, help="Rust router config JSON")
    ap.add_argument("--resolution", type=float, default=0.1)
    ap.add_argument("--inflate", type=float, default=None, help="Extractor inflate override (mm)")
    ap.add_argument("--label", type=str, default="rust", help="Label for results.csv row")
    ap.add_argument(
        "--kicad-image",
        type=str,
        default="kicad/kicad:9.0.6-full",
        help="Docker image for kicad-cli pcb drc",
    )
    ap.add_argument("--skip-drc", action="store_true", help="Skip kicad-cli DRC")
    ap.add_argument(
        "--timeout-route-s",
        type=float,
        default=None,
        help="Optional routing timeout (seconds)",
    )
    ap.add_argument(
        "--timeout-drc-s",
        type=float,
        default=None,
        help="Optional DRC timeout (seconds)",
    )
    ap.add_argument(
        "--results-csv",
        type=Path,
        default=Path("pardal-pcb/bench/results.csv"),
        help="Where to append results",
    )
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    pcb = args.pcb.resolve()
    out = args.out.resolve()

    routes_json = out.with_suffix(".routes.json")
    drc_json = out.with_suffix(".drc.json")
    progress_json = Path(str(routes_json) + ".progress.json")

    cmd = [
        str(repo_root / "pardal-pcb" / "venv" / "bin" / "python"),
        "-m",
        "pardal.cli",
        "rust-route",
        str(pcb),
        "-o",
        str(out),
        "--resolution",
        str(float(args.resolution)),
    ]
    if args.cfg is not None:
        cmd.extend(["--cfg", str(args.cfg.resolve())])
    if args.inflate is not None:
        cmd.extend(["--inflate", str(float(args.inflate))])

    status = "ok"
    try:
        elapsed_route_s = _run(cmd, cwd=repo_root, timeout_s=args.timeout_route_s)
    except subprocess.TimeoutExpired:
        status = "timeout"
        elapsed_route_s = float(args.timeout_route_s or 0.0)
    except subprocess.CalledProcessError:
        status = "error"
        raise

    drc_violations = None
    drc_unconnected = None
    elapsed_drc_s = None
    if status == "ok" and not args.skip_drc:
        elapsed_drc_s = _run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{repo_root}:/work",
                "-w",
                "/work",
                args.kicad_image,
                "kicad-cli",
                "pcb",
                "drc",
                "--format",
                "json",
                "-o",
                str(drc_json.relative_to(repo_root)),
                str(out.relative_to(repo_root)),
            ],
            cwd=repo_root,
            timeout_s=args.timeout_drc_s,
        )
        drc_violations, drc_unconnected = _drc_summary(drc_json)

    if routes_json.exists():
        router = _router_summary(routes_json)
    elif progress_json.exists():
        router = _router_summary_progress(progress_json)
    else:
        router = {"failed_nets": None}

    row = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "label": args.label,
        "status": status,
        "pcb": str(pcb),
        "out": str(out),
        "cfg": str(args.cfg.resolve()) if args.cfg else "",
        "resolution_mm": f"{args.resolution:.4f}",
        "inflate_mm": "" if args.inflate is None else f"{args.inflate:.4f}",
        "elapsed_route_s": f"{elapsed_route_s:.3f}",
        "elapsed_drc_s": "" if elapsed_drc_s is None else f"{elapsed_drc_s:.3f}",
        "drc_violations": "" if drc_violations is None else str(drc_violations),
        "drc_unconnected": "" if drc_unconnected is None else str(drc_unconnected),
        **{k: "" if v is None else str(v) for k, v in router.items()},
    }

    args.results_csv.parent.mkdir(parents=True, exist_ok=True)
    write_header = not args.results_csv.exists()
    with args.results_csv.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if write_header:
            w.writeheader()
        w.writerow(row)

    print(json.dumps(row, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
