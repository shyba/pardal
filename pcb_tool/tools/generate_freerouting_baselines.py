#!/usr/bin/env python3
"""Generate oracle baselines for FreeRouting fixtures.

This script is Phase 0 of `FREEROUTING_FULL_PARITY_PLAN.md`.

It scans `freerouting/tests/` for:
- Specctra DSN fixtures (`.dsn`)
- KiCad fixtures (`.kicad_pcb`)

For each fixture it runs FreeRouting with fixed settings and writes:
- `baseline.json` (settings + summary + content hashes)
- routed outputs under the fixture's baseline directory
  - DSN fixtures: routed `.dsn` + `freerouting_drc.json`
  - KiCad fixtures: routed `.kicad_pcb` + `kicad_drc.json`
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pcb_tool.freerouting_backend import (
    FreeroutingRunConfig,
    freeroute_kicad_pcb,
    run_kicad9_drc,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _drc_counts(report: dict[str, Any]) -> dict[str, int]:
    return {
        "violations": int(len(report.get("violations", []) or [])),
        "unconnected": int(len(report.get("unconnected_items", []) or [])),
    }


def _rel_to_workspace(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE_ROOT))
    except Exception:
        return str(path.resolve())


def _fixture_id(path: Path) -> str:
    # Keep a stable ID derived from the path under freerouting/tests.
    rel = path.resolve().relative_to(WORKSPACE_ROOT / "freerouting" / "tests")
    return str(rel).replace("/", "__")


@dataclass(frozen=True)
class Baseline:
    fixture_type: str  # "dsn" | "kicad"
    fixture_relpath: str
    fixture_id: str
    oracle_ok: bool
    oracle_error: str | None
    seed: int | None
    max_passes: int
    fanout: bool
    strip_planes: bool
    job_timeout: str | None
    generated_at_unix_s: int
    runtime_s: float
    outputs: dict[str, str]
    hashes: dict[str, str]
    drc: dict[str, Any]


def _scan_fixtures(tests_root: Path) -> tuple[list[Path], list[Path]]:
    dsns: list[Path] = []
    pcbs: list[Path] = []
    for p in sorted(tests_root.rglob("*")):
        if p.name.startswith("._"):
            continue
        if "__MACOSX" in p.parts:
            continue
        if p.suffix.lower() == ".dsn":
            dsns.append(p)
        elif p.suffix.lower() == ".kicad_pcb":
            pcbs.append(p)
    return dsns, pcbs


def _run_freerouting_oracle_dsn(
    *,
    input_dsn: Path,
    out_dir: Path,
    seed: int | None,
    max_passes: int,
    fanout: bool,
    job_timeout: str,
) -> None:
    # Uses the `freerouting:oracleBaseline` gradle task (local Java 25).
    cmd = [
        "./gradlew",
        "-q",
        "oracleBaseline",
        f"-Pinput={input_dsn.resolve()}",
        f"-Pout={out_dir.resolve()}",
        f"-Pseed={seed if seed is not None else 'null'}",
        f"-PmaxPasses={int(max_passes)}",
        f"-Pfanout={'true' if fanout else 'false'}",
        f"-PjobTimeout={job_timeout}",
    ]
    subprocess.run(cmd, cwd=str(WORKSPACE_ROOT / "freerouting"), check=True)


def _write_baseline(out_dir: Path, baseline: Baseline) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "baseline.json").write_text(
        json.dumps(asdict(baseline), indent=2, sort_keys=True), encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out-root",
        type=Path,
        default=REPO_ROOT / "parity_fixtures" / "baselines",
        help="Where to write baselines (default: parity_fixtures/baselines/)",
    )
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--max-passes", type=int, default=50)
    ap.add_argument("--no-fanout", action="store_true")
    ap.add_argument("--strip-planes", action="store_true")
    ap.add_argument("--job-timeout", type=str, default="00:05:00", help="FreeRouting job timeout (HH:MM:SS).")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", choices=["dsn", "kicad", "all"], default="all")
    ap.add_argument(
        "--match",
        type=str,
        default="",
        help="Only process fixtures whose workspace-relative path contains this substring.",
    )
    ap.add_argument("--force", action="store_true", help="Overwrite existing baselines.")
    args = ap.parse_args(argv)

    tests_root = WORKSPACE_ROOT / "freerouting" / "tests"
    dsns, pcbs = _scan_fixtures(tests_root)
    items: list[tuple[str, Path]] = []
    if args.only in {"dsn", "all"}:
        items.extend([("dsn", p) for p in dsns])
    if args.only in {"kicad", "all"}:
        items.extend([("kicad", p) for p in pcbs])

    if args.limit and args.limit > 0:
        items = items[: int(args.limit)]
    if args.match:
        items = [(k, p) for (k, p) in items if args.match in _rel_to_workspace(p)]

    cfg = FreeroutingRunConfig(
        max_passes=int(args.max_passes),
        fanout=not bool(args.no_fanout),
        strip_planes=bool(args.strip_planes),
        random_seed=int(args.seed),
        router_job_timeout=str(args.job_timeout) if args.job_timeout else None,
    )

    out_root: Path = args.out_root
    out_root.mkdir(parents=True, exist_ok=True)

    for i, (kind, path) in enumerate(items, start=1):
        fixture_rel = _rel_to_workspace(path)
        fixture_id = _fixture_id(path)
        out_dir = out_root / fixture_id

        # Skip already-generated baselines (idempotent).
        if (out_dir / "baseline.json").exists() and not args.force:
            print(f"[{i}/{len(items)}] SKIP {kind}: {fixture_rel}")
            continue
        if args.force and out_dir.exists():
            for child in out_dir.rglob("*"):
                if child.is_file():
                    child.unlink(missing_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)

        print(f"[{i}/{len(items)}] {kind}: {fixture_rel}")
        t0 = time.perf_counter()
        generated_at = int(time.time())

        outputs: dict[str, str] = {}
        hashes: dict[str, str] = {}
        drc: dict[str, Any] = {}
        oracle_ok = True
        oracle_error: str | None = None

        if kind == "dsn":
            try:
                _run_freerouting_oracle_dsn(
                    input_dsn=path,
                    out_dir=out_dir,
                    seed=int(args.seed),
                    max_passes=int(args.max_passes),
                    fanout=not bool(args.no_fanout),
                    job_timeout=str(args.job_timeout),
                )
            except subprocess.CalledProcessError as e:
                oracle_ok = False
                oracle_error = f"freerouting oracleBaseline failed: {e}"

            ses = out_dir / "routed.ses"
            fr_drc = out_dir / "freerouting_drc.json"
            stats = out_dir / "board_statistics.json"
            job_state = out_dir / "job_state.json"

            outputs["routed_ses"] = str(ses)
            outputs["freerouting_drc_json"] = str(fr_drc)
            outputs["board_statistics_json"] = str(stats)
            outputs["job_state_json"] = str(job_state)

            if ses.exists():
                hashes["routed_ses_sha256"] = _sha256(ses)
            if fr_drc.exists():
                hashes["freerouting_drc_sha256"] = _sha256(fr_drc)
            if stats.exists():
                hashes["board_statistics_sha256"] = _sha256(stats)
            if job_state.exists():
                hashes["job_state_sha256"] = _sha256(job_state)

            drc_report = json.loads(fr_drc.read_text(encoding="utf-8")) if fr_drc.exists() else {}
            drc.update(_drc_counts(drc_report))
            drc["freerouting_drc"] = drc_report
            if job_state.exists():
                drc["freerouting_job_state"] = json.loads(job_state.read_text(encoding="utf-8"))

        elif kind == "kicad":
            routed_pcb = out_dir / "routed.kicad_pcb"
            try:
                freeroute_kicad_pcb(path, routed_pcb, config=cfg)
            except Exception as e:
                oracle_ok = False
                oracle_error = f"freeroute_kicad_pcb failed: {e}"

            kicad_drc = out_dir / "kicad_drc.json"
            if oracle_ok and routed_pcb.exists():
                try:
                    run_kicad9_drc(routed_pcb, kicad_drc)
                except Exception as e:
                    oracle_ok = False
                    oracle_error = f"kicad drc failed: {e}"

            outputs["routed_pcb"] = str(routed_pcb)
            outputs["kicad_drc_json"] = str(kicad_drc)
            hashes["routed_pcb_sha256"] = _sha256(routed_pcb)
            hashes["kicad_drc_sha256"] = _sha256(kicad_drc) if kicad_drc.exists() else ""

            report = json.loads(kicad_drc.read_text(encoding="utf-8")) if kicad_drc.exists() else {}
            drc.update(_drc_counts(report))
            drc["kicad_drc"] = report

        else:
            raise AssertionError(kind)

        runtime_s = time.perf_counter() - t0
        baseline = Baseline(
            fixture_type=kind,
            fixture_relpath=fixture_rel,
            fixture_id=fixture_id,
            oracle_ok=oracle_ok,
            oracle_error=oracle_error,
            seed=int(args.seed),
            max_passes=int(args.max_passes),
            fanout=not bool(args.no_fanout),
            strip_planes=bool(args.strip_planes),
            job_timeout=str(args.job_timeout) if args.job_timeout else None,
            generated_at_unix_s=generated_at,
            runtime_s=float(runtime_s),
            outputs={k: _rel_to_workspace(Path(v)) for k, v in outputs.items()},
            hashes=hashes,
            drc=drc,
        )
        _write_baseline(out_dir, baseline)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
