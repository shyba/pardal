#!/usr/bin/env python3
"""Run a Mojo-only parity fixture capture with structured per-net trace output."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURES_JSON = PROJECT_ROOT / "tests/fixtures/parity_fixtures" / "fpga_large_only.json"
DEFAULT_TRACE_NETS = "U1_B10,U1_B11,U1_C10,U1_R10"
ROUTER_BIN = PROJECT_ROOT / "routing" / "mojo_router" / "build" / "pardal-router-mojo"
ROUTER_BUILD_SCRIPT = PROJECT_ROOT / "routing" / "mojo_router" / "build.sh"
ROUTER_SOURCE = PROJECT_ROOT / "routing" / "mojo_router" / "pardal_router_mojo" / "router.mojo"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _maybe_build_router() -> None:
    if not ROUTER_BIN.exists() or ROUTER_SOURCE.stat().st_mtime_ns > ROUTER_BIN.stat().st_mtime_ns:
        subprocess.run([str(ROUTER_BUILD_SCRIPT)], cwd=str(ROUTER_BUILD_SCRIPT.parent), check=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fixtures-json", type=Path, default=DEFAULT_FIXTURES_JSON)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--trace-nets", type=str, default=DEFAULT_TRACE_NETS)
    ap.add_argument("--trace-max-events", type=int, default=200000)
    ap.add_argument("--run-label", type=str, default="")
    ap.add_argument("--allow-unpinned-mojo-cfg", action="store_true")
    ap.add_argument("--kicad-drc-timeout-s", type=float, default=None)
    args = ap.parse_args(argv)

    out_dir = args.out_dir.resolve()
    suite_out_dir = out_dir / "suite_run"
    suite_out_dir.mkdir(parents=True, exist_ok=True)
    trace_path = out_dir / "mojo_trace.jsonl"
    summary_path = suite_out_dir / "suite_summary.json"
    capture_json = out_dir / "mojo_trace_capture.json"

    env = os.environ.copy()
    env["PARDAL_TRACE_JSONL"] = str(trace_path)
    env["PARDAL_TRACE_NETS"] = args.trace_nets
    env["PARDAL_TRACE_MAX_EVENTS"] = str(args.trace_max_events)

    _maybe_build_router()

    cmd = [
        str(PROJECT_ROOT / "venv" / "bin" / "python"),
        "-m",
        "pardal.tools.run_parity_suite",
        "--fixtures-json",
        str(args.fixtures_json.resolve()),
        "--out-dir",
        str(suite_out_dir),
        "--skip-freerouting",
        "--no-update-diary",
        "--no-cache",
    ]
    if args.allow_unpinned_mojo_cfg:
        cmd.append("--allow-unpinned-mojo-cfg")
    if args.kicad_drc_timeout_s is not None:
        cmd.extend(["--kicad-drc-timeout-s", str(args.kicad_drc_timeout_s)])

    started = time.time()
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=env, check=False)
    finished = time.time()
    if result.returncode != 0 and not summary_path.exists():
        raise SystemExit(result.returncode)

    summary = _load_json(summary_path) if summary_path.exists() else {}
    summaries = summary.get("summaries") or []
    fixture_summary = summaries[0] if isinstance(summaries, list) and summaries else {}
    trace_rows = _load_jsonl(trace_path)
    watched_nets = [x.strip() for x in args.trace_nets.split(",") if x.strip()]
    seen_nets = sorted({str(row.get("net_name", "")).strip() for row in trace_rows if str(row.get("net_name", "")).strip()})

    payload = {
        "run_label": args.run_label or time.strftime("mojo_trace_%Y%m%d_%H%M%S"),
        "fixtures_json": str(args.fixtures_json.resolve()),
        "suite_summary_json": str(summary_path),
        "trace_jsonl": str(trace_path),
        "trace_present": trace_path.exists(),
        "trace_events": len(trace_rows),
        "trace_max_events": args.trace_max_events,
        "watched_nets": watched_nets,
        "seen_nets": seen_nets,
        "missing_watched_nets": [n for n in watched_nets if n not in seen_nets],
        "process_exit_code": result.returncode,
        "elapsed_s": finished - started,
        "mojo_failed_nets": fixture_summary.get("mojo_failed_nets", -1),
        "mojo_violations": fixture_summary.get("mojo_drc", {}).get("violations", -1) if isinstance(fixture_summary.get("mojo_drc"), dict) else -1,
        "mojo_unconnected": fixture_summary.get("mojo_drc", {}).get("unconnected", -1) if isinstance(fixture_summary.get("mojo_drc"), dict) else -1,
        "mojo_violations_routing_only": fixture_summary.get("mojo_drc_routing_only", {}).get("violations", -1) if isinstance(fixture_summary.get("mojo_drc_routing_only"), dict) else -1,
        "mojo_unconnected_routing_only": fixture_summary.get("mojo_drc_routing_only", {}).get("unconnected", -1) if isinstance(fixture_summary.get("mojo_drc_routing_only"), dict) else -1,
        "timing_s": fixture_summary.get("timing_s", {}) if isinstance(fixture_summary.get("timing_s"), dict) else {},
    }
    _write_json(capture_json, payload)
    print(capture_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
