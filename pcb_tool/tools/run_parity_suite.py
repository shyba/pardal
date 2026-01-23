#!/usr/bin/env python3
"""Run a suite of parity fixtures via `run_parity_fixture.run_fixture`.

This is a convenience wrapper for the parity plan:
- runs a list of `.kicad_pcb` fixtures (FreeRouting oracle + Mojo backend-route)
- writes per-fixture artifacts into a single out directory
- emits `suite_summary.json` and a human-readable summary table
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pcb_tool.freerouting_backend import FreeroutingRunConfig
from pcb_tool.kicad_docker import DEFAULT_IMAGE
from pcb_tool.tools.run_parity_fixture import FixtureSummary, run_fixture


@dataclass(frozen=True)
class SuiteRow:
    fixture: str
    input_pcb: str
    freerouting_ok: bool
    freerouting_violations: int
    freerouting_unconnected: int
    mojo_violations: int
    mojo_unconnected: int
    mojo_failed_nets: int
    runtime_s: float


def _load_fixture_list(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("fixture list must be a JSON list of objects")
    out: list[dict[str, Any]] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"fixture[{i}] must be an object")
        if "name" not in item or "pcb" not in item:
            raise ValueError(f"fixture[{i}] must include 'name' and 'pcb'")
        out.append(item)
    return out


def _resolve_pcb_path(*, workspace_root: Path, project_root: Path, raw: str) -> Path:
    p = Path(raw)
    if p.is_absolute():
        return p
    # Prefer workspace-root-relative (can reference freerouting/, etc)
    cand = (workspace_root / p).resolve()
    if cand.exists():
        return cand
    # Fallback: project-root-relative
    return (project_root / p).resolve()


def _resolve_optional_path(*, workspace_root: Path, project_root: Path, raw: str | None) -> Path | None:
    if raw is None:
        return None
    p = Path(raw)
    if p.is_absolute():
        return p
    cand = (workspace_root / p).resolve()
    if cand.exists():
        return cand
    return (project_root / p).resolve()


def _default_tier_a(workspace_root: Path, project_root: Path) -> list[dict[str, Any]]:
    # Keep this intentionally small. Add more once this is stable in CI.
    return [
        {
            "name": "tier_a_issue269_min_fr_test",
            "pcb": str(workspace_root / "freerouting" / "tests" / "Issue269-min_fr_test" / "min_fr_test.kicad_pcb"),
            "freerouting_max_passes": 1,
            "mojo_resolution": 0.2,
        },
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--fixtures-json", type=Path, default=None, help="JSON list: [{name, pcb, ...}, ...]")
    ap.add_argument("--tier", choices=["a"], default=None, help="Use a built-in tier fixture list.")
    ap.add_argument("--kicad-image", default=DEFAULT_IMAGE)
    ap.add_argument("--freerouting-seed", type=int, default=1)
    ap.add_argument("--freerouting-max-passes", type=int, default=1)
    ap.add_argument("--freerouting-job-timeout", type=str, default=None)
    ap.add_argument("--freerouting-no-fanout", action="store_true")
    ap.add_argument("--freerouting-strip-planes", action="store_true")
    ap.add_argument("--mojo-cfg", type=Path, default=None)
    ap.add_argument("--mojo-resolution", type=float, default=0.2)
    ap.add_argument("--skip-freerouting", action="store_true")
    ap.add_argument("--skip-mojo", action="store_true")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--kicad-drc-timeout-s", type=float, default=300.0)
    ap.add_argument("--mojo-dsn-dump", action="store_true")
    ap.add_argument("--mojo-dsn-ir", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)

    project_root = Path(__file__).resolve().parents[2]
    workspace_root = Path(__file__).resolve().parents[3]

    if args.fixtures_json and args.tier:
        raise SystemExit("Use exactly one of --fixtures-json or --tier.")

    if args.fixtures_json:
        fixtures = _load_fixture_list(args.fixtures_json)
    elif args.tier == "a":
        fixtures = _default_tier_a(workspace_root=workspace_root, project_root=project_root)
    else:
        raise SystemExit("Provide --fixtures-json or --tier a.")

    if args.limit and args.limit > 0:
        fixtures = fixtures[: int(args.limit)]

    args.out_dir.mkdir(parents=True, exist_ok=True)

    suite_started = time.perf_counter()
    rows: list[SuiteRow] = []
    summaries: list[FixtureSummary] = []

    for i, fx in enumerate(fixtures, start=1):
        name = str(fx["name"])
        pcb = _resolve_pcb_path(workspace_root=workspace_root, project_root=project_root, raw=str(fx["pcb"]))
        if not pcb.exists():
            print(f"[{i}/{len(fixtures)}] {name}: SKIP missing pcb={pcb}")
            continue

        fr_cfg = FreeroutingRunConfig(
            kicad_docker_image=str(args.kicad_image),
            max_passes=int(fx.get("freerouting_max_passes", args.freerouting_max_passes)),
            fanout=not bool(fx.get("freerouting_no_fanout", args.freerouting_no_fanout)),
            strip_planes=bool(fx.get("freerouting_strip_planes", args.freerouting_strip_planes)),
            random_seed=int(fx.get("freerouting_seed", args.freerouting_seed)),
            router_job_timeout=str(fx.get("freerouting_job_timeout", args.freerouting_job_timeout))
            if (fx.get("freerouting_job_timeout", args.freerouting_job_timeout) is not None)
            else None,
        )

        mojo_resolution = float(fx.get("mojo_resolution", args.mojo_resolution))
        mojo_cfg = _resolve_optional_path(
            workspace_root=workspace_root,
            project_root=project_root,
            raw=str(fx["mojo_cfg"]) if ("mojo_cfg" in fx and fx["mojo_cfg"] is not None) else (str(args.mojo_cfg) if args.mojo_cfg else None),
        )

        out_dir = args.out_dir / name
        out_dir.mkdir(parents=True, exist_ok=True)

        print(f"[{i}/{len(fixtures)}] {name} (pcb={pcb})")
        t0 = time.perf_counter()
        summary = run_fixture(
            workspace_root=workspace_root,
            project_root=project_root,
            fixture_name=name,
            input_pcb=pcb,
            out_dir=out_dir,
            kicad_image=str(args.kicad_image),
            freerouting_cfg=fr_cfg,
            mojo_cfg_json=mojo_cfg,
            mojo_resolution_mm=mojo_resolution,
            run_freerouting=not bool(args.skip_freerouting),
            run_mojo=not bool(args.skip_mojo),
            cache=not bool(args.no_cache),
            drc_timeout_s=float(args.kicad_drc_timeout_s),
            mojo_dump_dsn=bool(args.mojo_dsn_dump),
            mojo_dump_ir=bool(args.mojo_dsn_ir),
        )
        dt = time.perf_counter() - t0

        # Write per-fixture summary.
        (out_dir / f"{name}.summary.json").write_text(
            json.dumps(asdict(summary), indent=2, sort_keys=True), encoding="utf-8"
        )

        rows.append(
            SuiteRow(
                fixture=name,
                input_pcb=str(pcb),
                freerouting_ok=bool(summary.freerouting_ok),
                freerouting_violations=int(summary.freerouting_drc.violations),
                freerouting_unconnected=int(summary.freerouting_drc.unconnected),
                mojo_violations=int(summary.mojo_drc.violations),
                mojo_unconnected=int(summary.mojo_drc.unconnected),
                mojo_failed_nets=int(summary.mojo_failed_nets),
                runtime_s=float(dt),
            )
        )
        summaries.append(summary)

    total_dt = time.perf_counter() - suite_started
    out = {
        "cwd": os.getcwd(),
        "count": len(rows),
        "runtime_s": total_dt,
        "rows": [asdict(r) for r in rows],
        "summaries": [asdict(s) for s in summaries],
    }
    (args.out_dir / "suite_summary.json").write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")

    # Print a compact table.
    print("\nfixture,fr_ok,fr_v,fr_u,mojo_v,mojo_u,mojo_failed,sec")
    for r in rows:
        print(
            f"{r.fixture},{int(r.freerouting_ok)},{r.freerouting_violations},{r.freerouting_unconnected},"
            f"{r.mojo_violations},{r.mojo_unconnected},{r.mojo_failed_nets},{r.runtime_s:.2f}"
        )
    print(f"\nwrote {args.out_dir / 'suite_summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
