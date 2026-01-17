#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
CORE = ROOT / "pardal-pcb" / "pardal_router_core"
BUILD = CORE / "build" / "bga_bench"


@dataclass
class RunResult:
    ok: bool
    time_ms: int
    extra: dict[str, Any]
    stderr_tail: str | None = None


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
        stderr_tail = "\n".join(p.stderr.splitlines()[-30:]) if p.stderr else None
        return RunResult(
            ok=(p.returncode == 0),
            time_ms=dt,
            extra={"returncode": p.returncode, "stdout": p.stdout, "stderr": p.stderr},
            stderr_tail=stderr_tail,
        )
    except subprocess.TimeoutExpired as e:
        dt = int((time.perf_counter() - t0) * 1000)
        return RunResult(
            ok=False,
            time_ms=dt,
            extra={"timeout": True, "stdout": (e.stdout or ""), "stderr": (e.stderr or "")},
            stderr_tail=(e.stderr or "")[-2000:] if e.stderr else None,
        )


def ensure_built() -> None:
    subprocess.run(
        [
            "cargo",
            "build",
            "-q",
            "--bin",
            "pardal_route_dsn",
            "--bin",
            "pardal_parity_extract",
            "--bin",
            "pardal_dsn_check",
        ],
        cwd=str(CORE),
        check=True,
    )


def parity_extract(json_path: Path) -> dict[str, Any] | None:
    if not json_path.exists():
        return None
    p = subprocess.run(
        [str(CORE / "target" / "debug" / "pardal_parity_extract"), str(json_path)],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout)
    except Exception:
        return None


def get_metric(m: dict[str, Any] | None, key: str) -> int | None:
    if not m:
        return None
    v = m.get(key)
    return int(v) if isinstance(v, int) else None


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    r = run_cmd(["docker", "ps"], timeout_s=2)
    return r.ok


def dsn_check_metrics(dsn_path: Path, *, timeout_s: int) -> tuple[RunResult, dict[str, Any] | None]:
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


def run_rust_route(
    dsn: Path,
    out_dir: Path,
    *,
    net_limit: int,
    negotiation: str,
    pitch: str,
    via_cost: str,
    timeout_s: int,
) -> RunResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dsn = out_dir / f"{dsn.stem}.rust.{negotiation}.dsn"
    env = dict(os.environ)
    env["PARDAL_ROUTE_DSN_OUT"] = str(out_dsn)
    cmd = [
        str(CORE / "target" / "debug" / "pardal_route_dsn"),
        str(dsn),
        "ALL",
        pitch,
        via_cost,
        str(net_limit),
        "auto",
        "none",
        negotiation,
    ]
    r = run_cmd(cmd, env=env, timeout_s=timeout_s)
    r.extra["out_dsn"] = str(out_dsn)
    return r


def run_freerouting_oracle(dsn: Path, out_dir: Path, *, seed: str, passes: int, threads: int, timeout_s: int) -> RunResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "bash",
        str(CORE / "tools" / "freerouting_oracle.sh"),
        str(dsn),
        str(out_dir),
        seed,
        str(passes),
        str(threads),
    ]
    r = run_cmd(cmd, timeout_s=timeout_s)
    return r


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pins", type=str, default="100,200,300,400,500,600")
    ap.add_argument("--seed", type=str, default="0xDEADBEEF")
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--timeout-s", type=int, default=180)
    ap.add_argument("--run-freerouting", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument(
        "--scenario",
        type=str,
        default="ring_escape",
        choices=["ring_escape", "ring_escape_multi", "grid_match"],
    )
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
    ap.add_argument("--rust-pitch", type=str, default="auto")
    ap.add_argument("--rust-via-cost", type=str, default="auto")
    ap.add_argument("--run-rust-off", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--run-rust-basic", action=argparse.BooleanOptionalAction, default=False)
    args = ap.parse_args()

    pin_counts = [int(x.strip()) for x in args.pins.split(",") if x.strip()]
    BUILD.mkdir(parents=True, exist_ok=True)
    out_tag = args.out_tag.strip() or (
        f"{args.scenario}.p{args.passes}.t{args.timeout_s}."
        f"rustpitch{args.rust_pitch}.rustvia{args.rust_via_cost}."
        f"rustoff{int(args.run_rust_off)}.rustbasic{int(args.run_rust_basic)}"
    )
    out_root = BUILD / out_tag
    out_root.mkdir(parents=True, exist_ok=True)
    ensure_built()

    have_docker = docker_available()
    run_freerouting = bool(args.run_freerouting and have_docker)
    if args.run_freerouting and not have_docker:
        print("warn: docker not available; skipping FreeRouting oracle/DRC and using internal `pardal_dsn_check` only")

    report_md = CORE / "build" / f"bga_bench_report.{out_tag}.md"
    report_csv = CORE / "build" / f"bga_bench_report.{out_tag}.csv"

    rows: list[dict[str, Any]] = []

    for pins in pin_counts:
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

        case_dir = out_root / f"bga_{pins}.{args.scenario}"
        if case_dir.exists():
            shutil.rmtree(case_dir)
        case_dir.mkdir(parents=True, exist_ok=True)

        # FreeRouting oracle (routes the full netlist). Optional: requires docker.
        fr: RunResult | None = None
        fr_stats: dict[str, Any] | None = None
        fr_drc: dict[str, Any] | None = None
        fr_routed_path = case_dir / f"{dsn.stem}.oracle.routed.dsn"
        if run_freerouting:
            fr = run_freerouting_oracle(
                dsn,
                case_dir,
                seed=args.seed,
                passes=args.passes,
                threads=args.threads,
                timeout_s=args.timeout_s,
            )

            fr_stats_path = case_dir / f"{dsn.stem}.oracle.stats.json"
            fr_drc_path = case_dir / f"{dsn.stem}.oracle.drc.json"
            fr_stats = parity_extract(fr_stats_path)
            fr_drc = parity_extract(fr_drc_path)

        # Rust routes: sequential (off) and basic negotiation.
        rust_off = (
            run_rust_route(
                dsn,
                case_dir,
                net_limit=pins,
                negotiation="off",
                pitch=args.rust_pitch,
                via_cost=args.rust_via_cost,
                timeout_s=args.timeout_s,
            )
            if args.run_rust_off
            else None
        )
        rust_basic = (
            run_rust_route(
                dsn,
                case_dir,
                net_limit=pins,
                negotiation="basic",
                pitch=args.rust_pitch,
                via_cost=args.rust_via_cost,
                timeout_s=args.timeout_s,
            )
            if args.run_rust_basic
            else None
        )

        # DRC on Rust output DSNs.
        #
        # Prefer FreeRouting (docker) when available, but fall back to internal nm-level checks
        # when docker isn't usable in this environment.
        def freerouting_drc_on(dsn_path: Path, out_json: Path) -> RunResult:
            img_tag = os.environ.get("FREEROUTING_ORACLE_IMAGE", "ee-freerouting-oracle:local")
            cmd = [
                "docker",
                "run",
                "--rm",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "-v",
                f"{dsn_path}:/mnt/in/board.dsn:ro",
                "-v",
                f"{out_json.parent}:/mnt/out",
                img_tag,
                "java",
                "-jar",
                "/app/freerouting-executable.jar",
                "--gui-enabled=false",
                "--api_server-enabled=false",
                "--feature_flags-logging=0",
                "--usage_and_diagnostic_data-disableAnalytics=1",
                "--user_data_path=/tmp/freerouting_userdata",
                "-de",
                "/mnt/in/board.dsn",
                "-drc",
                f"/mnt/out/{out_json.name}",
            ]
            return run_cmd(cmd, timeout_s=args.timeout_s)

        rust_off_dsn = (
            Path(str(rust_off.extra.get("out_dsn"))) if (rust_off is not None) else None
        )
        rust_basic_dsn = (
            Path(str(rust_basic.extra.get("out_dsn"))) if (rust_basic is not None) else None
        )
        rust_off_drc_json = case_dir / f"{dsn.stem}.rust.off.freerouting.drc.json"
        rust_basic_drc_json = case_dir / f"{dsn.stem}.rust.basic.freerouting.drc.json"

        rust_off_drc_run = (
            freerouting_drc_on(rust_off_dsn, rust_off_drc_json)
            if (run_freerouting and rust_off_dsn is not None and rust_off_dsn.exists())
            else None
        )
        rust_basic_drc_run = (
            freerouting_drc_on(rust_basic_dsn, rust_basic_drc_json)
            if (run_freerouting and rust_basic_dsn is not None and rust_basic_dsn.exists())
            else None
        )

        rust_off_drc = parity_extract(rust_off_drc_json) if rust_off_drc_run is not None else None
        rust_basic_drc = parity_extract(rust_basic_drc_json) if rust_basic_drc_run is not None else None
        rust_off_internal_run, rust_off_internal = (
            dsn_check_metrics(rust_off_dsn, timeout_s=args.timeout_s)
            if (rust_off_dsn is not None and rust_off_dsn.exists())
            else (None, None)
        )
        rust_basic_internal_run, rust_basic_internal = (
            dsn_check_metrics(rust_basic_dsn, timeout_s=args.timeout_s)
            if (rust_basic_dsn is not None and rust_basic_dsn.exists())
            else (None, None)
        )

        def internal_unconn(m: dict[str, Any] | None) -> int | None:
            if not m:
                return None
            v = m.get("disconnected_nets")
            return len(v) if isinstance(v, list) else None

        def internal_drc_clear(m: dict[str, Any] | None) -> int | None:
            if not m:
                return None
            drc = m.get("drc")
            if not isinstance(drc, dict):
                return None
            v = drc.get("clearance")
            return int(v) if isinstance(v, int) else None

        def internal_drc_shorts(m: dict[str, Any] | None) -> int | None:
            if not m:
                return None
            drc = m.get("drc")
            if not isinstance(drc, dict):
                return None
            v = drc.get("shorts")
            return int(v) if isinstance(v, int) else None

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

        off_req, off_got = (None, None)
        if rust_off is not None:
            off_req, off_got = parse_routed_count(rust_off.extra.get("stdout", ""))
        basic_req, basic_got = (None, None)
        if rust_basic is not None:
            basic_req, basic_got = parse_routed_count(rust_basic.extra.get("stdout", ""))

        rows.append(
            {
                "pins": pins,
                "docker_ok": have_docker,
                "freerouting_ok": (fr.ok if fr is not None else None),
                "freerouting_time_ms": (fr.time_ms if fr is not None else None),
                "freerouting_incomplete": get_metric(fr_stats, "connections_incomplete"),
                "freerouting_routed_dsn": (fr_routed_path.exists() if run_freerouting else None),
                "freerouting_drc_unconn": get_metric(fr_drc, "unconnected_items_total"),
                "freerouting_drc_clear": get_metric(fr_drc, "clearance_violations_total"),
                "rust_off_ok": (rust_off.ok if rust_off is not None else None),
                "rust_off_time_ms": (rust_off.time_ms if rust_off is not None else None),
                "rust_off_requested": off_req,
                "rust_off_routed": off_got,
                "rust_off_drc_tool": ("freerouting" if rust_off_drc is not None else "internal"),
                "rust_off_drc_unconn": (
                    get_metric(rust_off_drc, "unconnected_items_total")
                    if rust_off_drc is not None
                    else internal_unconn(rust_off_internal)
                ),
                "rust_off_drc_clear": (
                    get_metric(rust_off_drc, "clearance_violations_total")
                    if rust_off_drc is not None
                    else internal_drc_clear(rust_off_internal)
                ),
                "rust_off_drc_shorts": (
                    None if rust_off_drc is not None else internal_drc_shorts(rust_off_internal)
                ),
                "rust_basic_ok": (rust_basic.ok if rust_basic is not None else None),
                "rust_basic_time_ms": (rust_basic.time_ms if rust_basic is not None else None),
                "rust_basic_requested": basic_req,
                "rust_basic_routed": basic_got,
                "rust_basic_drc_tool": ("freerouting" if rust_basic_drc is not None else "internal"),
                "rust_basic_drc_unconn": (
                    get_metric(rust_basic_drc, "unconnected_items_total")
                    if rust_basic_drc is not None
                    else internal_unconn(rust_basic_internal)
                ),
                "rust_basic_drc_clear": (
                    get_metric(rust_basic_drc, "clearance_violations_total")
                    if rust_basic_drc is not None
                    else internal_drc_clear(rust_basic_internal)
                ),
                "rust_basic_drc_shorts": (
                    None if rust_basic_drc is not None else internal_drc_shorts(rust_basic_internal)
                ),
                "rust_off_internal_ok": (
                    rust_off_internal_run.ok if rust_off_internal_run is not None else None
                ),
                "rust_off_internal_time_ms": (
                    rust_off_internal_run.time_ms if rust_off_internal_run is not None else None
                ),
                "rust_basic_internal_ok": (
                    rust_basic_internal_run.ok if rust_basic_internal_run is not None else None
                ),
                "rust_basic_internal_time_ms": (
                    rust_basic_internal_run.time_ms if rust_basic_internal_run is not None else None
                ),
                "notes": (
                    ("FR timeout; " if (fr is not None and fr.extra.get("timeout")) else "")
                    + ("rust_off timeout; " if (rust_off is not None and rust_off.extra.get("timeout")) else "")
                    + ("rust_basic timeout; " if (rust_basic is not None and rust_basic.extra.get("timeout")) else "")
                    + ("no_docker; " if not have_docker else "")
                ).strip(),
            }
        )

        # Keep per-case JSON for later inspection.
        (case_dir / "case.json").write_text(json.dumps(rows[-1], indent=2), encoding="utf-8")

    # Write CSV + markdown report.
    keys = list(rows[0].keys()) if rows else []
    report_csv.write_text(
        "\n".join(
            [",".join(keys)]
            + [",".join("" if r.get(k) is None else str(r.get(k)) for k in keys) for r in rows]
        )
        + "\n",
        encoding="utf-8",
    )

    def cell(v: Any) -> str:
        return "?" if v is None else str(v)

    md: list[str] = []
    md.append("# BGA Benchmark (Rust vs FreeRouting)")
    md.append("")
    md.append(f"- seed: `{args.seed}`")
    md.append(f"- freerouting_passes: `{args.passes}`")
    md.append(f"- freerouting_threads: `{args.threads}`")
    md.append(f"- per-run-timeout: `{args.timeout_s}s`")
    md.append(f"- scenario: `{args.scenario}`")
    md.append(f"- geom_pitch_mil: `{args.pitch_mil}`")
    md.append(f"- geom_target_pitch_mil: `{args.target_pitch_mil}`")
    md.append(f"- geom_pad_diam_mil: `{args.pad_diam_mil}`")
    md.append(f"- geom_via_diam_mil: `{args.via_diam_mil}`")
    md.append(f"- geom_gap_mil: `{args.gap_mil}`")
    md.append(f"- geom_margin_mil: `{args.margin_mil}`")
    md.append(f"- rules_clear_mil: `{args.clear_mil}`")
    md.append(f"- rules_width_mil: `{args.width_mil}`")
    md.append(f"- bga_pad_layers: `{args.bga_pad_layers}`")
    md.append(f"- tgt_pad_layers: `{args.tgt_pad_layers}`")
    md.append(f"- dsn_via_costs: `{args.dsn_via_costs}`")
    md.append(f"- dsn_plane_via_costs: `{args.dsn_plane_via_costs}`")
    md.append(f"- dsn_start_ripup_costs: `{args.dsn_start_ripup_costs}`")
    md.append(f"- out_tag: `{out_tag}`")
    md.append(f"- rust_pitch: `{args.rust_pitch}`")
    md.append(f"- rust_via_cost: `{args.rust_via_cost}`")
    md.append(f"- docker_ok: `{have_docker}`")
    md.append(f"- run_freerouting: `{run_freerouting}`")
    md.append(f"- rust_off: `{args.run_rust_off}`")
    md.append(f"- rust_basic: `{args.run_rust_basic}`")
    md.append("")
    md.append("| Pins | FR time (ms) | FR routed DSN | FR incomplete | FR DRC unconn | FR DRC clear | Rust(off) time (ms) | Rust(off) routed | Rust(off) DRC tool | Rust(off) DRC unconn | Rust(off) DRC clear | Rust(off) DRC shorts | Rust(basic) time (ms) | Rust(basic) routed | Rust(basic) DRC tool | Rust(basic) DRC unconn | Rust(basic) DRC clear | Rust(basic) DRC shorts | Notes |")
    md.append("|---:|---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for r in rows:
        md.append(
            "| "
            + " | ".join(
                [
                    cell(r["pins"]),
                    cell(r["freerouting_time_ms"]),
                    ("yes" if r.get("freerouting_routed_dsn") else "no"),
                    cell(r["freerouting_incomplete"]),
                    cell(r["freerouting_drc_unconn"]),
                    cell(r["freerouting_drc_clear"]),
                    cell(r["rust_off_time_ms"]),
                    f'{cell(r["rust_off_routed"])}/{cell(r["rust_off_requested"])}',
                    cell(r["rust_off_drc_tool"]),
                    cell(r["rust_off_drc_unconn"]),
                    cell(r["rust_off_drc_clear"]),
                    cell(r["rust_off_drc_shorts"]),
                    cell(r["rust_basic_time_ms"]),
                    f'{cell(r["rust_basic_routed"])}/{cell(r["rust_basic_requested"])}',
                    cell(r["rust_basic_drc_tool"]),
                    cell(r["rust_basic_drc_unconn"]),
                    cell(r["rust_basic_drc_clear"]),
                    cell(r["rust_basic_drc_shorts"]),
                    cell(r["notes"]),
                ]
            )
            + " |"
        )
    md.append("")
    md.append(f"- CSV: `{report_csv}`")
    md.append(f"- Cases: `{out_root}`")
    report_md.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"wrote: {report_md}")


if __name__ == "__main__":
    main()
