#!/usr/bin/env python3
"""FreeRouting backend integration (Specctra DSN/SES).

This module integrates the FreeRouting autorouter without reimplementing its
maze router in Python. The workflow is:

1) Use KiCad's pcbnew Python API (KiCad 9) to export Specctra DSN from a
   `.kicad_pcb` file.
2) Run FreeRouting on the DSN to produce a Specctra SES session.
3) Use KiCad's pcbnew Python API (KiCad 9) to import the SES into a board and
   save a routed `.kicad_pcb`.

Why KiCad 9?
- KiCad 7 exposes `pcbnew.ExportSpecctraDSN(BOARD, ...)` but only
  `pcbnew.ImportSpecctraSES(filename)` (GUI/global board). KiCad 9 exposes the
  BOARD overload for importing: `ImportSpecctraSES(BOARD, filename)`, which
  enables headless scripting.

This is particularly useful for dense BGAs because FreeRouting provides a
fanout pass (escape routing to a first via) and a rip-up-and-reroute maze router.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


_OFFENDING_DSN_CHARS = re.compile(r"[ΩµΦ]")
_DSN_PLANE_START = re.compile(r"^\s*\(plane\b")


@dataclass(frozen=True)
class FreeroutingRunConfig:
    kicad_docker_image: str = "kicad/kicad:9.0.6-full"
    java_docker_image: str = "eclipse-temurin:21-jre"
    freerouting_zip_relpath: str = "freerouting/integrations/KiCad/kicad-freerouting-2.1.0.zip"
    freerouting_jar_name: str = "freerouting-2.1.0.jar"

    max_passes: int = 50
    fanout: bool = True
    fanout_max_passes: int = 20
    threads: int | None = None  # None uses FreeRouting default; 0 disables optimizer
    optimizer_improvement_threshold: float | None = None  # maps to `-oit`
    save_intermediate: bool = False  # maps to `-im`
    random_seed: int | None = None  # maps to `-random_seed`
    via_costs: int = 50
    start_ripup_costs: int = 100
    ignore_net_classes: tuple[str, ...] = ()  # maps to `-inc` (comma-separated)
    strip_planes: bool = False  # remove `(plane ...)` blocks from DSN (copper pours)

    disable_analytics: bool = True
    disable_logging: bool = True
    log_level: str | int | None = None  # maps to `-ll` (requires disable_logging=False)
    router_job_timeout: str | None = None  # maps to `--router.job_timeout=HH:MM:SS`
    router_max_threads: int | None = None  # maps to `--router.max_threads=<n>`
    trace_pull_tight_accuracy: int | None = None  # maps to `--router.trace_pull_tight_accuracy=<n>`


def _repo_root() -> Path:
    # pcb_tool/ is pardal-pcb/pcb_tool/, so parents[2] is repo root.
    return Path(__file__).resolve().parents[2]


def _build_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "build" / "freerouting"


def _require_docker() -> None:
    if shutil.which("docker") is None:
        raise RuntimeError("docker not found in PATH; required for KiCad 9/Java containers")


def _run(cmd: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def _docker_run(
    image: str,
    *,
    workdir: str,
    mounts: Iterable[tuple[Path, str]],
    env: dict[str, str] | None,
    args: list[str],
) -> None:
    cmd = ["docker", "run", "--rm"]
    for host_path, container_path in mounts:
        cmd.extend(["-v", f"{host_path}:{container_path}"])
    cmd.extend(["-w", workdir])
    if env:
        for k, v in env.items():
            cmd.extend(["-e", f"{k}={v}"])
    cmd.append(image)
    cmd.extend(args)
    _run(cmd)


def ensure_freerouting_jar(config: FreeroutingRunConfig) -> Path:
    """Extract FreeRouting jar from the vendored KiCad plugin zip into build/."""
    repo_root = _repo_root()
    zip_path = repo_root / config.freerouting_zip_relpath
    if not zip_path.exists():
        raise FileNotFoundError(zip_path)

    out_dir = _build_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    jar_out = out_dir / config.freerouting_jar_name
    if jar_out.exists() and jar_out.stat().st_size > 0:
        return jar_out

    with zipfile.ZipFile(zip_path) as zf:
        jar_members = [n for n in zf.namelist() if n.endswith(f"/{config.freerouting_jar_name}")]
        if not jar_members:
            # Fallback: first jar in archive.
            jar_members = [n for n in zf.namelist() if n.endswith(".jar")]
        if not jar_members:
            raise FileNotFoundError(f"No .jar found in {zip_path}")
        jar_member = jar_members[0]
        jar_out.write_bytes(zf.read(jar_member))

    if not jar_out.exists() or jar_out.stat().st_size == 0:
        raise RuntimeError(f"Failed to extract jar to {jar_out}")
    return jar_out


def sanitize_dsn(
    raw_dsn: Path,
    cleaned_dsn: Path,
    *,
    pcb_name: str = "freerouting.dsn",
    strip_planes: bool = False,
) -> None:
    """Sanitize KiCad-exported DSN for FreeRouting compatibility.

    Mirrors the KiCad plugin behavior:
    - Rewrite the first line as `(pcb <pcb_name>`
    - Strip a few characters that can upset Java parsing
    - Optionally remove `(plane ...)` blocks (copper pours) to speed routing
    """
    cleaned_dsn.parent.mkdir(parents=True, exist_ok=True)
    first = True
    skipping_plane = False
    plane_balance = 0
    with raw_dsn.open("r", encoding="utf-8", errors="replace") as fr, cleaned_dsn.open(
        "w", encoding="utf-8"
    ) as fw:
        for line in fr:
            line = _OFFENDING_DSN_CHARS.sub("", line)
            if first:
                fw.write(f"(pcb {pcb_name}\n")
                first = False
                continue

            if strip_planes:
                if skipping_plane:
                    plane_balance += line.count("(") - line.count(")")
                    if plane_balance <= 0:
                        skipping_plane = False
                        plane_balance = 0
                    continue

                if _DSN_PLANE_START.match(line):
                    skipping_plane = True
                    plane_balance = line.count("(") - line.count(")")
                    if plane_balance <= 0:
                        skipping_plane = False
                        plane_balance = 0
                    continue

            fw.write(line)


def freeroute_kicad_pcb(
    input_pcb: Path,
    output_pcb: Path,
    *,
    config: FreeroutingRunConfig | None = None,
) -> None:
    """Route `input_pcb` with FreeRouting and write `output_pcb`.

    Requires:
    - docker (to run KiCad 9 python and Java 21)
    - `freerouting/` directory present in the repo (for the plugin zip)
    """
    if config is None:
        config = FreeroutingRunConfig()

    _require_docker()
    repo_root = _repo_root()

    input_pcb = input_pcb.resolve()
    output_pcb = output_pcb.resolve()
    if not input_pcb.exists():
        raise FileNotFoundError(input_pcb)

    jar_path = ensure_freerouting_jar(config)
    build_dir = _build_dir()
    raw_dsn = build_dir / "freerouting_raw.dsn"
    dsn = build_dir / "freerouting.dsn"
    ses = build_dir / "freerouting.ses"

    for p in (raw_dsn, dsn, ses):
        p.unlink(missing_ok=True)

    mounts: list[tuple[Path, str]] = [(repo_root, "/work")]

    if input_pcb.is_relative_to(repo_root):
        in_path_in_container = f"/work/{os.path.relpath(input_pcb, repo_root)}"
    else:
        mounts.append((input_pcb.parent, "/ext_in"))
        in_path_in_container = f"/ext_in/{input_pcb.name}"

    if output_pcb.is_relative_to(repo_root):
        out_path_in_container = f"/work/{os.path.relpath(output_pcb, repo_root)}"
    else:
        mounts.append((output_pcb.parent, "/ext_out"))
        out_path_in_container = f"/ext_out/{output_pcb.name}"

    # 1) Export DSN via KiCad 9 pcbnew
    raw_dsn_rel = os.path.relpath(raw_dsn.resolve(), repo_root)
    _docker_run(
        config.kicad_docker_image,
        workdir="/work",
        mounts=mounts,
        env={"IN_PCB": in_path_in_container, "OUT_DSN": f"/work/{raw_dsn_rel}"},
        args=[
            "python3",
            "-c",
            "import os, pcbnew\n"
            "b = pcbnew.LoadBoard(os.environ['IN_PCB'])\n"
            "ok = pcbnew.ExportSpecctraDSN(b, os.environ['OUT_DSN'])\n"
            "raise SystemExit(0 if ok else 1)\n",
        ],
    )

    sanitize_dsn(raw_dsn, dsn, pcb_name="freerouting.dsn", strip_planes=config.strip_planes)

    # 2) Run FreeRouting on DSN -> SES (Java 21)
    jar_rel = os.path.relpath(jar_path.resolve(), repo_root)
    dsn_rel = os.path.relpath(dsn.resolve(), repo_root)
    ses_rel = os.path.relpath(ses.resolve(), repo_root)

    fr_args: list[str] = [
        "java",
        "-jar",
        f"/work/{jar_rel}",
        "-de",
        f"/work/{dsn_rel}",
        "-do",
        f"/work/{ses_rel}",
        "-host",
        "pardal",
    ]

    if config.disable_analytics:
        fr_args.append("-da")
    if config.disable_logging:
        fr_args.append("-dl")
    if config.log_level is not None:
        fr_args.extend(["-ll", str(config.log_level)])

    fr_args.extend(["-mp", str(config.max_passes)])
    if config.threads is not None:
        fr_args.extend(["-mt", str(config.threads)])
    if config.optimizer_improvement_threshold is not None:
        fr_args.extend(["-oit", str(config.optimizer_improvement_threshold)])
    if config.save_intermediate:
        fr_args.append("-im")
    if config.random_seed is not None:
        fr_args.extend(["-random_seed", str(config.random_seed)])
    if config.ignore_net_classes:
        fr_args.extend(["-inc", ",".join(config.ignore_net_classes)])

    # Settings overrides (hierarchical keys accept dots)
    fr_args.append("--gui.enabled=false")
    if config.router_job_timeout is not None:
        fr_args.append(f"--router.job_timeout={config.router_job_timeout}")
    if config.router_max_threads is not None:
        fr_args.append(f"--router.max_threads={config.router_max_threads}")
    if config.trace_pull_tight_accuracy is not None:
        fr_args.append(f"--router.trace_pull_tight_accuracy={config.trace_pull_tight_accuracy}")
    fr_args.append(f"--router.scoring.via_costs={config.via_costs}")
    fr_args.append(f"--router.scoring.start_ripup_costs={config.start_ripup_costs}")
    if config.fanout:
        fr_args.append("--router.fanout.enabled=true")
        fr_args.append(f"--router.fanout.max_passes={config.fanout_max_passes}")
    else:
        fr_args.append("--router.fanout.enabled=false")

    _docker_run(
        config.java_docker_image,
        workdir="/work",
        mounts=[(repo_root, "/work")],
        env=None,
        args=fr_args,
    )

    if not ses.exists():
        raise RuntimeError(f"FreeRouting did not produce SES: {ses}")

    # 3) Import SES into board and save via KiCad 9 pcbnew
    _docker_run(
        config.kicad_docker_image,
        workdir="/work",
        mounts=mounts,
        env={
            "IN_PCB": in_path_in_container,
            "SES": f"/work/{ses_rel}",
            "OUT_PCB": out_path_in_container,
        },
        args=[
            "python3",
            "-c",
            "import os, pcbnew\n"
            "b = pcbnew.LoadBoard(os.environ['IN_PCB'])\n"
            "ok = pcbnew.ImportSpecctraSES(b, os.environ['SES'])\n"
            "b.Save(os.environ['OUT_PCB'])\n"
            "raise SystemExit(0 if ok else 1)\n",
        ],
    )


def run_kicad9_drc(pcb: Path, report_json: Path) -> None:
    """Run KiCad 9 DRC in docker and write JSON report."""
    _require_docker()
    repo_root = _repo_root()
    pcb = pcb.resolve()
    report_json = report_json.resolve()

    mounts: list[tuple[Path, str]] = [(repo_root, "/work")]
    if pcb.is_relative_to(repo_root):
        pcb_in_container = f"/work/{os.path.relpath(pcb, repo_root)}"
    else:
        mounts.append((pcb.parent, "/ext_pcb"))
        pcb_in_container = f"/ext_pcb/{pcb.name}"

    if report_json.is_relative_to(repo_root):
        report_in_container = f"/work/{os.path.relpath(report_json, repo_root)}"
    else:
        mounts.append((report_json.parent, "/ext_report"))
        report_in_container = f"/ext_report/{report_json.name}"

    report_json.parent.mkdir(parents=True, exist_ok=True)
    _docker_run(
        "kicad/kicad:9.0.6-full",
        workdir="/work",
        mounts=mounts,
        env=None,
        args=[
            "kicad-cli",
            "pcb",
            "drc",
            "--format",
            "json",
            "-o",
            report_in_container,
            pcb_in_container,
        ],
    )
