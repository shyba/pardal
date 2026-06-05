#!/usr/bin/env python3
"""Run a small FreeRouting DSN corpus through the DSN→problem converter and Mojo router.

This is a developer harness for parity work. It:
- converts DSN fixtures to problem.json
- runs the Mojo router with a conservative config
- records basic stats (failed nets, track count)

It is intentionally lightweight and does not require KiCad.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from pardal.tools.convert_dsn_to_problem import convert_dsn_to_problem


@dataclass
class Result:
    dsn: Path
    ok: bool
    failed_nets: int
    tracks: int
    error: str | None = None


def _run_one(dsn: Path, out_dir: Path, mojo_bin: Path, cfg: Dict) -> Result:
    out_dir.mkdir(parents=True, exist_ok=True)
    problem = out_dir / (dsn.stem + ".problem.json")
    routes = out_dir / (dsn.stem + ".routes.json")
    cfg_path = out_dir / "cfg.json"
    cfg_path.write_text(json.dumps(cfg, indent=2))
    try:
        convert_dsn_to_problem(dsn_path=dsn, out_json=problem)
        subprocess.run([str(mojo_bin), str(problem), str(routes), str(cfg_path)], check=True)
        data = json.loads(routes.read_text())
        failed_list = data.get("failed_nets", [])
        failed = len(failed_list)
        tracks = len(data.get("tracks", []))
        # Heuristic completion ratio: failed unique nets over unique nets present.
        unique_nets = {t.get("net") for t in data.get("tracks", []) if isinstance(t, dict) and t.get("net")}
        unique_failed = set(failed_list)
        denom = max(1, len(unique_nets | unique_failed))
        completion = 1.0 - (len(unique_failed) / denom)
        # Save a per-case report.
        report = {
            "dsn": str(dsn),
            "problem": str(problem),
            "routes": str(routes),
            "failed_nets": failed_list,
            "tracks": tracks,
            "completion": completion,
        }
        (out_dir / (dsn.stem + ".report.json")).write_text(json.dumps(report, indent=2))
        return Result(dsn=dsn, ok=failed == 0, failed_nets=failed, tracks=tracks, error=None)
    except Exception as e:  # noqa: BLE001 - corpus harness should continue.
        return Result(dsn=dsn, ok=False, failed_nets=999999, tracks=0, error=str(e))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--freerouting-root", type=Path, required=True, help="Path to ee/freerouting")
    ap.add_argument("--mojo-bin", type=Path, required=True, help="Path to pardal-router-mojo binary")
    ap.add_argument("--out", type=Path, default=Path("corpus_out"))
    ap.add_argument("--limit", type=int, default=20)
    ns = ap.parse_args()

    tests_dir = ns.freerouting_root / "tests"
    dsns = sorted(tests_dir.glob("*.dsn")) + sorted(tests_dir.glob("Issue*/**/*.dsn"))
    dsns = [p for p in dsns if p.is_file()]
    dsns = dsns[: max(0, int(ns.limit))]

    cfg = {
        "commit_routes": True,
        "ncr_iters": 0,
        "ripup_passes": 0,
        "attempts": 1,
        "margin_init": 64,
        "margin_step": 128,
        "margin_max": 512,
        "enforce_spacing": False,
        "enforce_touch": True,
        "escape_enable": False,
        "astar_max_expansions": 200000,
        "max_time_ms": 10000,
        "per_net_time_ms": 500,
        "precommit_drc_enable": True,
    }

    results: List[Result] = []
    for dsn in dsns:
        r = _run_one(dsn, ns.out, ns.mojo_bin, cfg)
        results.append(r)
        extra = f" err={r.error}" if r.error else ""
        print(f"{dsn.name}: ok={r.ok} failed={r.failed_nets} tracks={r.tracks}{extra}")

    summary = {
        "count": len(results),
        "ok": sum(1 for r in results if r.ok),
        "failed": sum(1 for r in results if not r.ok),
        "avg_tracks": (sum(r.tracks for r in results) / max(1, len(results))),
        "details": [
            {"dsn": str(r.dsn), "ok": r.ok, "failed_nets": r.failed_nets, "tracks": r.tracks, "error": r.error}
            for r in results
        ],
    }
    (ns.out / "summary.json").write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
