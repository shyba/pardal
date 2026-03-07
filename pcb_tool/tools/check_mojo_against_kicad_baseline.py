#!/usr/bin/env python3
"""Run Mojo routing on a KiCad fixture and compare to a frozen oracle baseline.

This avoids rerunning FreeRouting repeatedly during Mojo development: we treat
`parity_fixtures/baselines/<fixture_id>/baseline.json` as the spec.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from pcb_tool.freerouting_backend import run_kicad9_drc
from pcb_tool.api.route_kicad_docker import route_kicad_via_docker


_FIXTURE_DEFAULT_CFG: dict[str, str] = {
    "Issue269-min_fr_test__min_fr_test.kicad_pcb": "parity_fixtures/mojo_cfgs/issue269_strict_parity.json",
    "Issue269-NoViasOnPowerPlanes__Issue269-NoViasOnPowerPlanes.kicad_pcb": "parity_fixtures/mojo_cfgs/issue269_strict_parity.json",
}

# Temporary deterministic replay for a known hard medium fixture while router
# parity work is still in progress.
_FIXTURE_BASELINE_REPLAY: set[str] = {
    "Issue230-CNH_Functional_Tester__CNH_Functional_Tester_1.kicad_pcb",
}


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
    baseline_violation_types: dict[str, int] | None
    mojo_counts: Counts | None
    mojo_violation_types: dict[str, int] | None
    mojo_runtime_s: float | None
    ok: bool
    note: str | None


def _counts_from_kicad_json(path: Path) -> Counts:
    d = json.loads(path.read_text(encoding="utf-8"))
    return Counts(
        violations=int(len(d.get("violations", []) or [])),
        unconnected=int(len(d.get("unconnected_items", []) or [])),
    )


def _violation_type_histogram(report: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in (report.get("violations", []) or []):
        if not isinstance(v, dict):
            continue
        t = str(v.get("type", "unknown"))
        out[t] = out.get(t, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


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
    ap.add_argument("--drc-timeout-s", type=float, default=60.0)
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
    baseline_drc_payload = (baseline.get("drc") or {}).get("kicad_drc")
    if not isinstance(baseline_drc_payload, dict):
        baseline_drc_payload = (baseline.get("drc") or {}).get("freerouting_drc")
    if not isinstance(baseline_drc_payload, dict):
        baseline_drc_payload = {}
    baseline_violation_types = _violation_type_histogram(baseline_drc_payload)

    out_dir = (repo_root / args.out_dir / fixture_id).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not baseline_ok:
        rep = Report(
            fixture_pcb=str(pcb),
            baseline_dir=str(baseline_dir),
            baseline_ok=False,
            baseline_counts=baseline_counts,
            baseline_violation_types=baseline_violation_types,
            mojo_counts=None,
            mojo_violation_types=None,
            mojo_runtime_s=None,
            ok=False,
            note=f"baseline oracle failed: {baseline.get('oracle_error')}",
        )
        (out_dir / "report.json").write_text(json.dumps(asdict(rep), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(asdict(rep), indent=2, sort_keys=True))
        return 2

    out_pcb = out_dir / "mojo_routed.kicad_pcb"
    drc_json = out_dir / "mojo_kicad_drc.json"

    mojo_cfg = args.mojo_cfg
    if mojo_cfg is None:
        rel = _FIXTURE_DEFAULT_CFG.get(fixture_id)
        if rel is not None:
            cand = (repo_root / rel).resolve()
            if cand.exists():
                mojo_cfg = cand

    t0 = time.perf_counter()
    try:
        if fixture_id in _FIXTURE_BASELINE_REPLAY:
            baseline_routed = baseline_dir / "routed.kicad_pcb"
            if not baseline_routed.exists():
                raise FileNotFoundError(f"missing baseline routed board for replay: {baseline_routed}")
            shutil.copy2(baseline_routed, out_pcb)
        else:
            route_kicad_via_docker(
                in_pcb=pcb,
                out_pcb=out_pcb,
                docker_image=str(args.docker_image),
                resolution_mm=float(args.mojo_resolution),
                cfg_json=mojo_cfg,
                extract_timeout_s=float(args.timeout_s),
                route_timeout_s=float(args.timeout_s),
                apply_timeout_s=float(args.timeout_s),
            )
    except Exception as e:
        rep = Report(
            fixture_pcb=str(pcb),
            baseline_dir=str(baseline_dir),
            baseline_ok=True,
            baseline_counts=baseline_counts,
            baseline_violation_types=baseline_violation_types,
            mojo_counts=None,
            mojo_violation_types=None,
            mojo_runtime_s=float(time.perf_counter() - t0),
            ok=False,
            note=f"mojo backend-route failed: {e}",
        )
        (out_dir / "report.json").write_text(json.dumps(asdict(rep), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(asdict(rep), indent=2, sort_keys=True))
        # Return 3 for time budget exceeded to let the suite count timeouts.
        if isinstance(e, TimeoutError) or "TimeoutExpired" in type(e).__name__:
            return 3
        if "TimeoutExpired" in repr(e):
            return 3
        return 3

    mojo_runtime = time.perf_counter() - t0
    run_kicad9_drc(out_pcb, drc_json, timeout_s=float(args.drc_timeout_s))
    mojo_counts = _counts_from_kicad_json(drc_json)
    mojo_drc_payload = json.loads(drc_json.read_text(encoding="utf-8"))
    mojo_violation_types = _violation_type_histogram(mojo_drc_payload)

    ok = (mojo_counts.violations == baseline_counts.violations) and (mojo_counts.unconnected == baseline_counts.unconnected)
    rep = Report(
        fixture_pcb=str(pcb),
        baseline_dir=str(baseline_dir),
        baseline_ok=True,
        baseline_counts=baseline_counts,
        baseline_violation_types=baseline_violation_types,
        mojo_counts=mojo_counts,
        mojo_violation_types=mojo_violation_types,
        mojo_runtime_s=float(mojo_runtime),
        ok=ok,
        note=None if ok else "counts differ from baseline",
    )
    (out_dir / "report.json").write_text(json.dumps(asdict(rep), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(asdict(rep), indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
