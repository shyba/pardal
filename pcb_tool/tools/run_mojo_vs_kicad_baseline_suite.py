#!/usr/bin/env python3
"""Run Mojo-vs-baseline checks across all KiCad fixtures in the FreeRouting corpus.

Uses:
- `parity_fixtures/freerouting_fixture_manifest.json` for the fixture list
- `pcb_tool.tools.check_mojo_against_kicad_baseline` for per-fixture evaluation
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass(frozen=True)
class SuiteRow:
    fixture: str
    exit_code: int
    baseline_v: int | None
    baseline_u: int | None
    mojo_v: int | None
    mojo_u: int | None
    runtime_s: float
    note: str | None


def _extract_last_json_obj(text: str) -> dict:
    # The per-fixture runner may print progress lines from docker/pcbnew
    # before printing its final JSON report. Find the last line that starts
    # a JSON object (`{`) and parse from there.
    lines = text.splitlines()
    start = None
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == "{":
            start = i
            break
    if start is None:
        # Fallback: try parsing the whole stdout.
        return json.loads(text)
    payload = "\n".join(lines[start:]) + "\n"
    return json.loads(payload)

def _baseline_counts_for_fixture(*, repo_root: Path, pcb_path: Path) -> tuple[int | None, int | None]:
    # Best-effort fallback: if the per-fixture checker output is truncated,
    # load the baseline.json directly.
    parts = list(pcb_path.parts)
    try:
        idx = parts.index("freerouting")
        rel = Path(*parts[idx + 2 :])  # skip freerouting/tests
        fixture_id = str(rel).replace("/", "__")
    except ValueError:
        fixture_id = pcb_path.name.replace("/", "__")
    baseline_json = repo_root / "parity_fixtures" / "baselines" / fixture_id / "baseline.json"
    if not baseline_json.exists():
        return None, None
    try:
        d = json.loads(baseline_json.read_text(encoding="utf-8"))
        drc = d.get("drc") or {}
        return int(drc.get("violations", 0)), int(drc.get("unconnected", 0))
    except Exception:
        return None, None


def _load_manifest(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("manifest must be a list")
    return data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--manifest",
        type=Path,
        default=Path("parity_fixtures/freerouting_fixture_manifest.json"),
    )
    ap.add_argument("--out", type=Path, default=Path("parity_out/mojo_vs_baseline_suite.json"))
    ap.add_argument("--timeout-s", type=float, default=60.0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only-match", type=str, default="")
    ap.add_argument("--mojo-cfg", type=Path, default=None)
    ap.add_argument("--mojo-resolution", type=float, default=0.2)
    ap.add_argument("--drc-timeout-s", type=float, default=60.0)
    ap.add_argument(
        "--fixture-timeout-s",
        type=float,
        default=150.0,
        help="Hard wall-clock cap per fixture (kills the whole process group).",
    )
    args = ap.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[2]
    workspace_root = repo_root.parent

    manifest = _load_manifest(repo_root / args.manifest)
    fixtures = [
        (workspace_root / Path(it["path"])).resolve()
        for it in manifest
        if isinstance(it, dict) and it.get("type") == "kicad"
    ]
    if args.only_match:
        fixtures = [p for p in fixtures if args.only_match in str(p)]
    if args.limit and args.limit > 0:
        fixtures = fixtures[: int(args.limit)]

    rows: list[SuiteRow] = []
    started = time.perf_counter()

    out_path = (repo_root / args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    for i, pcb in enumerate(fixtures, start=1):
        t0 = time.perf_counter()
        cmd = [
            str(repo_root / "venv" / "bin" / "python"),
            "-m",
            "pcb_tool.tools.check_mojo_against_kicad_baseline",
            str(pcb),
            "--timeout-s",
            str(float(args.timeout_s)),
            "--drc-timeout-s",
            str(float(args.drc_timeout_s)),
            "--mojo-resolution",
            str(float(args.mojo_resolution)),
        ]
        if args.mojo_cfg is not None:
            cmd += ["--mojo-cfg", str(args.mojo_cfg)]

        print(f"[{i}/{len(fixtures)}] {pcb}")
        # Run in a new process group so we can reliably kill nested docker/java
        # processes if something wedges.
        proc = subprocess.Popen(
            cmd,
            cwd=str(repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=float(args.fixture_timeout_s))
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                proc.kill()
            stdout, stderr = proc.communicate(timeout=5)
            rc = 124
        else:
            rc = int(proc.returncode or 0)
        dt = time.perf_counter() - t0

        baseline_v = baseline_u = mojo_v = mojo_u = None
        note = None
        try:
            payload = _extract_last_json_obj(stdout) if stdout.strip() else {}
            bc = payload.get("baseline_counts") or {}
            mc = payload.get("mojo_counts") or {}
            baseline_v = bc.get("violations")
            baseline_u = bc.get("unconnected")
            mojo_v = mc.get("violations")
            mojo_u = mc.get("unconnected")
            note = payload.get("note")
        except Exception:
            note = "failed to parse per-fixture JSON; see stderr"
            baseline_v, baseline_u = _baseline_counts_for_fixture(repo_root=repo_root, pcb_path=pcb)

        if rc not in (0, 1, 2, 3):
            note = f"unexpected exit_code={rc}"
            if baseline_v is None and baseline_u is None:
                baseline_v, baseline_u = _baseline_counts_for_fixture(repo_root=repo_root, pcb_path=pcb)
        if stderr.strip():
            note = (note + "; " if note else "") + "stderr present"

        rows.append(
            SuiteRow(
                fixture=str(pcb),
                exit_code=int(rc),
                baseline_v=baseline_v,
                baseline_u=baseline_u,
                mojo_v=mojo_v,
                mojo_u=mojo_u,
                runtime_s=float(dt),
                note=note,
            )
        )

        # Write incremental progress so long runs can be resumed/inspected.
        partial = {
            "summary": {"completed": len(rows), "total": len(fixtures), "runtime_s": time.perf_counter() - started},
            "rows": [asdict(r) for r in rows],
        }
        out_path.write_text(json.dumps(partial, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    total_s = time.perf_counter() - started
    ok = sum(1 for r in rows if r.exit_code == 0)
    diff = sum(1 for r in rows if r.exit_code == 1)
    basefail = sum(1 for r in rows if r.exit_code == 2)
    timeout = sum(1 for r in rows if r.exit_code == 3)

    out_payload = {
        "summary": {
            "total": len(rows),
            "ok": ok,
            "diff": diff,
            "baseline_fail": basefail,
            "timeout": timeout,
            "runtime_s": total_s,
        },
        "rows": [asdict(r) for r in rows],
    }

    out_path.write_text(json.dumps(out_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"suite: total={len(rows)} ok={ok} diff={diff} baseline_fail={basefail} timeout={timeout} runtime_s={total_s:.1f}")
    print(f"wrote: {out_path}")
    return 0 if (diff == 0 and timeout == 0 and basefail == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
