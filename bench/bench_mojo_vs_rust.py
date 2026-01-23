#!/usr/bin/env python3
"""Benchmark Mojo router vs Rust router on the same KiCad fixture.

This script measures *router* runtime (parse+route), not KiCad IO:
- Exports Specctra DSN once via KiCad docker.
- Extracts a `problem.json` once via KiCad docker.
- Times:
  - Rust: `pardal_router_core/target/release/pardal_route_dsn <dsn> ALL ...`
  - Mojo: `pardal_router_mojo/build/pardal-router-mojo <problem.json> <routes.json>`

Outputs a JSON summary per fixture and prints a short table.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


KICAD_IMAGE_DEFAULT = "kicad/kicad:9.0.6-full"


def _run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, check=True)

def _run_timeout(
    cmd: list[str],
    *,
    cwd: Path | None,
    env: dict[str, str] | None,
    timeout_s: float,
    stdout_path: Path | None = None,
    stderr_path: Path | None = None,
) -> None:
    stdout_f = None
    stderr_f = None
    try:
        if stdout_path is not None:
            stdout_path.parent.mkdir(parents=True, exist_ok=True)
            stdout_f = stdout_path.open("wb")
        if stderr_path is not None:
            stderr_path.parent.mkdir(parents=True, exist_ok=True)
            stderr_f = stderr_path.open("wb")
        subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=env,
            stdout=stdout_f if stdout_f else None,
            stderr=stderr_f if stderr_f else None,
            check=True,
            timeout=float(timeout_s),
        )
    finally:
        if stdout_f:
            stdout_f.close()
        if stderr_f:
            stderr_f.close()


def _docker_run(
    image: str,
    *,
    workdir: str,
    mounts: list[tuple[Path, str]],
    env: dict[str, str] | None,
    args: list[str],
) -> None:
    cmd = ["docker", "run", "--rm", "--user", f"{os.getuid()}:{os.getgid()}"]
    for host_path, container_path in mounts:
        cmd.extend(["-v", f"{host_path}:{container_path}"])
    cmd.extend(["-w", workdir])
    if env:
        for k, v in env.items():
            cmd.extend(["-e", f"{k}={v}"])
    cmd.append(image)
    cmd.extend(args)
    _run(cmd)


def _require(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def _export_dsn(*, workspace_root: Path, pcb: Path, out_dsn: Path, kicad_image: str) -> None:
    out_dsn.parent.mkdir(parents=True, exist_ok=True)
    _docker_run(
        kicad_image,
        workdir="/work",
        mounts=[(workspace_root, "/work")],
        env={
            "IN_PCB": f"/work/{os.path.relpath(pcb.resolve(), workspace_root)}",
            "OUT_DSN": f"/work/{os.path.relpath(out_dsn.resolve(), workspace_root)}",
        },
        args=[
            "python3",
            "-c",
            "import os, pcbnew\n"
            "b = pcbnew.LoadBoard(os.environ['IN_PCB'])\n"
            "ok = pcbnew.ExportSpecctraDSN(b, os.environ['OUT_DSN'])\n"
            "raise SystemExit(0 if ok else 1)\n",
        ],
    )


def _extract_problem_json(
    *,
    workspace_root: Path,
    repo_root: Path,
    pcb: Path,
    out_problem: Path,
    kicad_image: str,
) -> None:
    out_problem.parent.mkdir(parents=True, exist_ok=True)
    script = _require(repo_root / "pcb_tool" / "tools" / "extract_routing_problem_pcbnew.py")
    _docker_run(
        kicad_image,
        workdir="/work",
        mounts=[(workspace_root, "/work")],
        env=None,
        args=[
            "python3",
            f"/work/{os.path.relpath(script.resolve(), workspace_root)}",
            "--pcb",
            str(Path("/work") / os.path.relpath(pcb.resolve(), workspace_root)),
            "--out",
            str(Path("/work") / os.path.relpath(out_problem.resolve(), workspace_root)),
        ],
    )


def _time_once(fn) -> float:
    t0 = time.perf_counter()
    fn()
    return time.perf_counter() - t0


def _median(xs: list[float]) -> float:
    xs = sorted(xs)
    n = len(xs)
    if n == 0:
        return 0.0
    mid = n // 2
    return xs[mid] if (n % 2 == 1) else 0.5 * (xs[mid - 1] + xs[mid])


@dataclass(frozen=True)
class RouterTiming:
    runs: int
    times_s: list[float]
    median_s: float
    ok_runs: int
    timeout_runs: int
    error_runs: int
    failed: bool


@dataclass(frozen=True)
class FixtureBench:
    fixture_pcb: str
    dsn: str
    problem_json: str
    rust: RouterTiming
    mojo: RouterTiming
    notes: dict[str, Any]


def _bench_rust(
    *,
    repo_root: Path,
    dsn: Path,
    out_dir: Path,
    runs: int,
    negotiation: str,
    request_limit: int,
    timeout_s: float,
) -> RouterTiming:
    exe = _require(repo_root / "pardal_router_core" / "target" / "release" / "pardal_route_dsn")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dsn = out_dir / "rust_out.dsn"
    out_ses = out_dir / "rust_out.ses"

    times: list[float] = []
    ok_runs = 0
    timeout_runs = 0
    error_runs = 0
    for i in range(runs):
        # Force fresh outputs each run.
        out_dsn.unlink(missing_ok=True)
        out_ses.unlink(missing_ok=True)
        env = os.environ.copy()
        env["PARDAL_ROUTE_DSN_OUT"] = str(out_dsn)
        env["PARDAL_ROUTE_SES_OUT"] = str(out_ses)
        env["PARDAL_TIMING"] = "1"

        stdout_path = out_dir / f"run{i}.stdout.log"
        stderr_path = out_dir / f"run{i}.stderr.log"
        t0 = time.perf_counter()
        try:
            _run_timeout(
                [str(exe), str(dsn), "ALL", "auto", "auto", str(int(request_limit)), "auto", "auto", negotiation],
                cwd=repo_root,
                env=env,
                timeout_s=timeout_s,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
            dt = time.perf_counter() - t0
            times.append(dt)
            ok_runs += 1
        except subprocess.TimeoutExpired:
            timeout_runs += 1
        except subprocess.CalledProcessError:
            error_runs += 1

    return RouterTiming(
        runs=runs,
        times_s=times,
        median_s=_median(times),
        ok_runs=ok_runs,
        timeout_runs=timeout_runs,
        error_runs=error_runs,
        failed=(ok_runs != runs),
    )


def _bench_mojo(
    *,
    repo_root: Path,
    problem: Path,
    out_dir: Path,
    runs: int,
    timeout_s: float,
) -> RouterTiming:
    exe = _require(repo_root / "pardal_router_mojo" / "build" / "pardal-router-mojo")
    out_dir.mkdir(parents=True, exist_ok=True)
    routes = out_dir / "mojo_routes.json"

    times: list[float] = []
    ok_runs = 0
    timeout_runs = 0
    error_runs = 0
    for i in range(runs):
        routes.unlink(missing_ok=True)
        stdout_path = out_dir / f"run{i}.stdout.log"
        stderr_path = out_dir / f"run{i}.stderr.log"

        t0 = time.perf_counter()
        try:
            _run_timeout(
                [str(exe), str(problem), str(routes)],
                cwd=repo_root,
                env=None,
                timeout_s=timeout_s,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
            dt = time.perf_counter() - t0
            times.append(dt)
            ok_runs += 1
        except subprocess.TimeoutExpired:
            timeout_runs += 1
        except subprocess.CalledProcessError:
            error_runs += 1

    return RouterTiming(
        runs=runs,
        times_s=times,
        median_s=_median(times),
        ok_runs=ok_runs,
        timeout_runs=timeout_runs,
        error_runs=error_runs,
        failed=(ok_runs != runs),
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("fixture", type=Path, help="Fixture to benchmark (.dsn or .kicad_pcb)")
    ap.add_argument("--out-dir", type=Path, default=Path("bench/out_mojo_vs_rust"))
    ap.add_argument("--kicad-image", default=KICAD_IMAGE_DEFAULT)
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--negotiation", choices=["off", "basic", "seeded_basic"], default="seeded_basic")
    ap.add_argument("--request-limit", type=int, default=1_000_000, help="Rust: max number of route requests to attempt.")
    ap.add_argument("--net-limit", type=int, default=0, help="DSN->problem: cap number of nets for Mojo (0=all).")
    ap.add_argument("--timeout-s", type=float, default=60.0, help="Hard timeout per router run; timeout is a failure.")
    args = ap.parse_args(argv)

    if shutil.which("docker") is None:
        raise SystemExit("docker not found in PATH")

    repo_root = Path(__file__).resolve().parents[1]
    workspace_root = repo_root.parent

    out_dir = (repo_root / args.out_dir).resolve()
    fixture = args.fixture.resolve()
    if not fixture.exists():
        raise SystemExit(f"missing fixture: {fixture}")

    fixture_name = fixture.stem
    suffix = ""
    if fixture.suffix.lower() == ".dsn" and int(args.net_limit) > 0:
        suffix = f"_net{int(args.net_limit)}"
    fixture_dir = out_dir / f"{fixture_name}{suffix}"
    fixture_dir.mkdir(parents=True, exist_ok=True)

    dsn = fixture_dir / "fixture.dsn"
    problem = fixture_dir / "problem.json"

    if fixture.suffix.lower() == ".dsn":
        # Use DSN directly and convert to problem.json for Mojo routing.
        if not dsn.exists() or dsn.stat().st_size == 0:
            dsn.write_text(fixture.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        if not problem.exists() or problem.stat().st_size == 0:
            conv = _require(repo_root / "pcb_tool" / "tools" / "convert_dsn_to_problem.py")
            cmd = [str(repo_root / "venv" / "bin" / "python"), str(conv), str(dsn), "--out", str(problem)]
            if int(args.net_limit) > 0:
                cmd += ["--net-limit", str(int(args.net_limit))]
            _run(cmd, cwd=repo_root)
    elif fixture.suffix.lower() == ".kicad_pcb":
        # Export DSN + extract problem.json via KiCad docker.
        if not dsn.exists() or dsn.stat().st_size == 0:
            _export_dsn(workspace_root=workspace_root, pcb=fixture, out_dsn=dsn, kicad_image=str(args.kicad_image))
        if not problem.exists() or problem.stat().st_size == 0:
            _extract_problem_json(workspace_root=workspace_root, repo_root=repo_root, pcb=fixture, out_problem=problem, kicad_image=str(args.kicad_image))
    else:
        raise SystemExit("fixture must be .dsn or .kicad_pcb")

    rust_t = _bench_rust(
        repo_root=repo_root,
        dsn=dsn,
        out_dir=fixture_dir / "rust",
        runs=int(args.runs),
        negotiation=str(args.negotiation),
        request_limit=int(args.request_limit),
        timeout_s=float(args.timeout_s),
    )
    mojo_t = _bench_mojo(
        repo_root=repo_root,
        problem=problem,
        out_dir=fixture_dir / "mojo",
        runs=int(args.runs),
        timeout_s=float(args.timeout_s),
    )

    bench = FixtureBench(
        fixture_pcb=str(fixture),
        dsn=str(dsn),
        problem_json=str(problem),
        rust=rust_t,
        mojo=mojo_t,
        notes={"runs": int(args.runs), "negotiation": str(args.negotiation), "kicad_image": str(args.kicad_image)},
    )
    out_json = fixture_dir / "bench.json"
    out_json.write_text(json.dumps(asdict(bench), indent=2, sort_keys=True), encoding="utf-8")

    print("fixture:", fixture)
    print(
        f"rust  median_s={bench.rust.median_s:.3f}  ok={bench.rust.ok_runs}/{bench.rust.runs}  timeouts={bench.rust.timeout_runs}  errors={bench.rust.error_runs}"
    )
    print(
        f"mojo  median_s={bench.mojo.median_s:.3f}  ok={bench.mojo.ok_runs}/{bench.mojo.runs}  timeouts={bench.mojo.timeout_runs}  errors={bench.mojo.error_runs}"
    )
    print("wrote:", out_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
