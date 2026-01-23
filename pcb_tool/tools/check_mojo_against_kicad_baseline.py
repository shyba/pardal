#!/usr/bin/env python3
"""Run Mojo routing on a KiCad fixture and compare to a frozen oracle baseline.

This avoids rerunning FreeRouting repeatedly during Mojo development: we treat
`parity_fixtures/baselines/<fixture_id>/baseline.json` as the spec.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from dataclasses import dataclass, asdict
from pathlib import Path

from pcb_tool.freerouting_backend import run_kicad9_drc


@dataclass(frozen=True)
class Counts:
    violations: int
    unconnected: int


@dataclass(frozen=True)
class Report:
    fixture_pcb: str
    baseline_dir: str
    baseline_ok: bool
    baseline_counts: Counts
    mojo_counts: Counts | None
    mojo_runtime_s: float | None
    ok: bool
    note: str | None


def _counts_from_kicad_json(path: Path) -> Counts:
    d = json.loads(path.read_text(encoding="utf-8"))
    return Counts(
        violations=int(len(d.get("violations", []) or [])),
        unconnected=int(len(d.get("unconnected_items", []) or [])),
    )


def _fixture_id_from_path(pcb: Path) -> str:
    # Mirror `generate_freerouting_baselines._fixture_id()`.
    parts = list(pcb.parts)
    try:
        idx = parts.index("freerouting")  # .../freerouting/tests/<...>
        rel = Path(*parts[idx + 2 :])  # skip freerouting/tests
        return str(rel).replace("/", "__")
    except ValueError:
        return pcb.name.replace("/", "__")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pcb", type=Path)
    ap.add_argument("--baselines-root", type=Path, default=Path("parity_fixtures/baselines"))
    ap.add_argument("--out-dir", type=Path, default=Path("parity_out/mojo_vs_baseline"))
    ap.add_argument("--mojo-cfg", type=Path, default=None)
    ap.add_argument("--mojo-resolution", type=float, default=0.2)
    ap.add_argument("--docker-image", type=str, default="kicad/kicad:9.0.6-full")
    ap.add_argument("--timeout-s", type=float, default=60.0)
    args = ap.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[2]
    pcb = args.pcb.resolve()
    if not pcb.exists():
        raise SystemExit(f"missing pcb: {pcb}")
    if pcb.suffix.lower() != ".kicad_pcb":
        raise SystemExit("expected .kicad_pcb input")

    fixture_id = _fixture_id_from_path(pcb)
    baseline_dir = (repo_root / args.baselines_root / fixture_id).resolve()
    baseline_json = baseline_dir / "baseline.json"
    if not baseline_json.exists():
        raise SystemExit(f"missing baseline.json for fixture_id={fixture_id}: {baseline_json}")

    baseline = json.loads(baseline_json.read_text(encoding="utf-8"))
    baseline_ok = bool(baseline.get("oracle_ok", True))
    baseline_counts = Counts(
        violations=int((baseline.get("drc") or {}).get("violations", 0)),
        unconnected=int((baseline.get("drc") or {}).get("unconnected", 0)),
    )

    out_dir = (repo_root / args.out_dir / fixture_id).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not baseline_ok:
        rep = Report(
            fixture_pcb=str(pcb),
            baseline_dir=str(baseline_dir),
            baseline_ok=False,
            baseline_counts=baseline_counts,
            mojo_counts=None,
            mojo_runtime_s=None,
            ok=False,
            note=f"baseline oracle failed: {baseline.get('oracle_error')}",
        )
        (out_dir / "report.json").write_text(json.dumps(asdict(rep), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(asdict(rep), indent=2, sort_keys=True))
        return 2

    out_pcb = out_dir / "mojo_routed.kicad_pcb"
    drc_json = out_dir / "mojo_kicad_drc.json"

    cmd = [
        str(repo_root / "venv" / "bin" / "python"),
        "-m",
        "pcb_tool.cli",
        "backend-route",
        str(pcb),
        "-o",
        str(out_pcb),
        "--docker-image",
        str(args.docker_image),
        "--resolution",
        str(float(args.mojo_resolution)),
    ]
    if args.mojo_cfg is not None:
        cmd += ["--cfg", str(args.mojo_cfg)]

    t0 = time.perf_counter()
    try:
        subprocess.run(cmd, cwd=str(repo_root), check=True, timeout=float(args.timeout_s))
    except subprocess.TimeoutExpired:
        rep = Report(
            fixture_pcb=str(pcb),
            baseline_dir=str(baseline_dir),
            baseline_ok=True,
            baseline_counts=baseline_counts,
            mojo_counts=None,
            mojo_runtime_s=float(time.perf_counter() - t0),
            ok=False,
            note=f"mojo backend-route timed out after {args.timeout_s}s",
        )
        (out_dir / "report.json").write_text(json.dumps(asdict(rep), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(asdict(rep), indent=2, sort_keys=True))
        return 3

    mojo_runtime = time.perf_counter() - t0
    run_kicad9_drc(out_pcb, drc_json)
    mojo_counts = _counts_from_kicad_json(drc_json)

    ok = (mojo_counts.violations == baseline_counts.violations) and (mojo_counts.unconnected == baseline_counts.unconnected)
    rep = Report(
        fixture_pcb=str(pcb),
        baseline_dir=str(baseline_dir),
        baseline_ok=True,
        baseline_counts=baseline_counts,
        mojo_counts=mojo_counts,
        mojo_runtime_s=float(mojo_runtime),
        ok=ok,
        note=None if ok else "counts differ from baseline",
    )
    (out_dir / "report.json").write_text(json.dumps(asdict(rep), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(asdict(rep), indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

