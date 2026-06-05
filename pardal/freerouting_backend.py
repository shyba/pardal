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
import json
import re
import shutil
import shlex
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
    enable_logging: bool | None = None  # if set, overrides disable_logging
    log_level: str | int | None = None  # maps to `-ll` (requires disable_logging=False)
    router_job_timeout: str | None = None  # maps to `--router.job_timeout=HH:MM:SS`
    router_max_threads: int | None = None  # maps to `--router.max_threads=<n>`
    trace_pull_tight_accuracy: int | None = None  # maps to `--router.trace_pull_tight_accuracy=<n>`

    # Optional JVM/runtime controls for instrumentation.
    java_tmpdir_relpath: str | None = None  # mounted under /work in docker
    capture_stdout_path: Path | None = None
    capture_stderr_path: Path | None = None
    jar_override: Path | None = None  # use local FR jar instead of plugin zip jar
    jvm_props: tuple[str, ...] = ()

    # Execution control:
    #
    # FreeRouting's `--router.job_timeout` does not always terminate the JVM in
    # practice. We used to wrap the Java invocation with a container-level
    # `timeout` to guarantee termination. That wrapper can prematurely kill runs
    # and makes oracle triage confusing (you lose the distinction between
    # "router chose to stop" vs "wrapper killed it"). For parity work we keep the
    # wrapper opt-in and rely on the Python subprocess timeout by default.
    enforce_container_timeout: bool = False
    container_timeout_slack_s: int = 15

    # Post-processing
    cleanup_dangling_tracks: bool = True
    cleanup_max_iterations: int = 5


def _repo_root() -> Path:
    # pardal/ is pardal-pcb/pardal/, so parents[1] is repo root.
    return Path(__file__).resolve().parents[1]


def _build_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "build" / "freerouting"


def _require_docker() -> None:
    if shutil.which("docker") is None:
        raise RuntimeError("docker not found in PATH; required for KiCad 9/Java containers")


def _run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    timeout_s: float | None = None,
    stdout=None,
    stderr=None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=check,
        timeout=None if timeout_s is None else float(timeout_s),
        stdout=stdout,
        stderr=stderr,
    )


def _docker_run(
    image: str,
    *,
    workdir: str,
    mounts: Iterable[tuple[Path, str]],
    env: dict[str, str] | None,
    args: list[str],
    check: bool = True,
    timeout_s: float | None = None,
    stdout_path: Path | None = None,
    stderr_path: Path | None = None,
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
    stdout_handle = None
    stderr_handle = None
    try:
        if stdout_path is not None:
            stdout_path.parent.mkdir(parents=True, exist_ok=True)
            stdout_handle = stdout_path.open("ab")
        if stderr_path is not None:
            stderr_path.parent.mkdir(parents=True, exist_ok=True)
            stderr_handle = stderr_path.open("ab")
        _run(
            cmd,
            check=check,
            timeout_s=timeout_s,
            stdout=stdout_handle,
            stderr=stderr_handle,
        )
    finally:
        if stdout_handle is not None:
            stdout_handle.close()
        if stderr_handle is not None:
            stderr_handle.close()


def _parse_hms_to_seconds(hms: str) -> int:
    parts = hms.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Expected HH:MM:SS, got {hms!r}")
    h, m, s = (int(p) for p in parts)
    if h < 0 or m < 0 or s < 0 or m >= 60 or s >= 60:
        raise ValueError(f"Invalid HH:MM:SS: {hms!r}")
    return h * 3600 + m * 60 + s


def _resolve_optional_repo_path(repo_root: Path, maybe_path: Path | None) -> Path | None:
    if maybe_path is None:
        return None
    p = Path(maybe_path)
    if p.is_absolute():
        return p.resolve()
    return (repo_root / p).resolve()


def _logging_enabled(config: FreeroutingRunConfig) -> bool:
    if config.enable_logging is not None:
        return bool(config.enable_logging)
    if config.log_level is not None:
        return True
    return not bool(config.disable_logging)


def _java_invocation_prefix(config: FreeroutingRunConfig, repo_root: Path) -> list[str]:
    java_prefix: list[str] = ["java"]
    for prop in config.jvm_props:
        prop_text = str(prop).strip()
        if prop_text:
            java_prefix.append(prop_text)
    if config.java_tmpdir_relpath:
        rel = str(config.java_tmpdir_relpath).strip().replace("\\", "/").lstrip("/")
        if rel:
            tmp_host_dir = (repo_root / rel).resolve()
            tmp_host_dir.mkdir(parents=True, exist_ok=True)
            java_prefix.append(f"-Djava.io.tmpdir=/work/{rel}")
    return java_prefix


def ensure_freerouting_jar(config: FreeroutingRunConfig) -> Path:
    """Extract FreeRouting jar from the vendored KiCad plugin zip into build/."""
    repo_root = _repo_root()
    jar_override = _resolve_optional_repo_path(repo_root, config.jar_override)
    if jar_override is not None:
        if not jar_override.exists():
            raise FileNotFoundError(jar_override)
        if jar_override.stat().st_size <= 0:
            raise RuntimeError(f"Jar override is empty: {jar_override}")
        return jar_override

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

    # KiCad may create sibling project files next to the output board when running
    # headlessly (e.g. `.kicad_pro`, `.kicad_prl`). Track whether those existed
    # before routing so we can clean up only files introduced by this call.
    extra_artifacts = [
        output_pcb.with_suffix(".kicad_pro"),
        output_pcb.with_suffix(".kicad_prl"),
    ]
    artifact_preexisting = {p: p.exists() for p in extra_artifacts}

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

    java_prefix = _java_invocation_prefix(config, repo_root)
    fr_args: list[str] = [
        *java_prefix,
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
    if not _logging_enabled(config):
        fr_args.append("-dl")
    elif config.log_level is not None:
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

    java_args: list[str] = fr_args
    docker_timeout_s: float | None = None
    if config.router_job_timeout is not None:
        # Always apply a python-level timeout so "job_timeout" cannot hang the harness.
        try:
            job_timeout_s = _parse_hms_to_seconds(config.router_job_timeout)
        except ValueError:
            job_timeout_s = None
        if job_timeout_s is not None:
            docker_timeout_s = float(job_timeout_s) + float(
                max(0, int(config.container_timeout_slack_s))
            )
            if config.enforce_container_timeout:
                java_args = [
                    "bash",
                    "-lc",
                    f"timeout {int(job_timeout_s)}s {shlex.join(fr_args)}",
                ]

    _docker_run(
        config.java_docker_image,
        workdir="/work",
        mounts=[(repo_root, "/work")],
        env=None,
        args=java_args,
        timeout_s=docker_timeout_s,
        stdout_path=_resolve_optional_repo_path(repo_root, config.capture_stdout_path),
        stderr_path=_resolve_optional_repo_path(repo_root, config.capture_stderr_path),
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

    for artifact in extra_artifacts:
        if artifact.exists() and not artifact_preexisting.get(artifact, False):
            artifact.unlink(missing_ok=True)

    # Preserve project settings for KiCad CLI DRC: KiCad associates rules with the
    # `.kicad_pro` matching the PCB filename stem. FreeRouting/pcbnew may generate
    # new project files with default rules; overwrite them with the input project
    # so DRC uses the fixture's intended constraints.
    if output_pcb != input_pcb:
        for ext in (".kicad_pro", ".kicad_prl"):
            src = input_pcb.with_suffix(ext)
            dst = output_pcb.with_suffix(ext)
            try:
                if src.exists():
                    dst.write_text(
                        src.read_text(encoding="utf-8", errors="replace"), encoding="utf-8"
                    )
            except Exception:
                pass

    # FreeRouting can occasionally emit tiny "dangling" track stubs (usually at
    # inferred layer transitions). KiCad DRC flags these as warnings. For a
    # high-confidence output we optionally remove only the specific items KiCad
    # reports as dangling and re-check, up to a small iteration budget.
    if config.cleanup_dangling_tracks:
        report_json = _build_dir() / "freerouting_kicad_drc.json"

        def run_drc() -> dict:
            report_json.parent.mkdir(parents=True, exist_ok=True)
            report_rel = os.path.relpath(report_json.resolve(), repo_root)
            _docker_run(
                config.kicad_docker_image,
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
                    f"/work/{report_rel}",
                    out_path_in_container,
                ],
                check=False,
            )
            return json.loads(report_json.read_text(encoding="utf-8"))

        def dangling_uuids(report: dict) -> set[str]:
            uuids: set[str] = set()
            for v in report.get("violations", []):
                if v.get("type") not in {"track_dangling", "via_dangling"}:
                    continue
                if v.get("severity") != "warning":
                    continue
                for item in v.get("items", []):
                    uid = item.get("uuid")
                    if uid and uid != "00000000-0000-0000-0000-000000000000":
                        uuids.add(uid)
            return uuids

        for _ in range(max(0, int(config.cleanup_max_iterations))):
            report = run_drc()
            to_remove = dangling_uuids(report)
            if not to_remove:
                break

            _docker_run(
                config.kicad_docker_image,
                workdir="/work",
                mounts=mounts,
                env={
                    "OUT_PCB": out_path_in_container,
                    "REMOVE_UUIDS": ",".join(sorted(to_remove)),
                },
                args=[
                    "python3",
                    "-c",
                    "import os, pcbnew\n"
                    "b = pcbnew.LoadBoard(os.environ['OUT_PCB'])\n"
                    "remove = set(filter(None, os.environ.get('REMOVE_UUIDS', '').split(',')))\n"
                    "removed = 0\n"
                    "for it in list(b.GetTracks()):\n"
                    "    if it.m_Uuid.AsString() in remove:\n"
                    "        b.RemoveNative(it)\n"
                    "        removed += 1\n"
                    "b.Save(os.environ['OUT_PCB'])\n"
                    "print('removed', removed)\n",
                ],
            )


def run_kicad9_drc(pcb: Path, report_json: Path, *, timeout_s: float | None = None) -> None:
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
        # KiCad returns a non-zero exit code when violations exist; we still want the JSON.
        check=False,
        timeout_s=timeout_s,
    )
    if not report_json.exists() or report_json.stat().st_size == 0:
        raise RuntimeError(f"KiCad DRC report not produced: {report_json}")


def freeroute_dsn(
    input_dsn: Path,
    *,
    output_dsn: Path,
    drc_json: Path | None = None,
    config: FreeroutingRunConfig | None = None,
) -> None:
    """Route a Specctra DSN directly (no KiCad IO).

    This is primarily used for oracle baseline generation over FreeRouting's DSN
    fixture corpus.
    """
    if config is None:
        config = FreeroutingRunConfig()

    _require_docker()
    repo_root = _repo_root()

    input_dsn = input_dsn.resolve()
    output_dsn = output_dsn.resolve()
    if not input_dsn.exists():
        raise FileNotFoundError(input_dsn)

    output_dsn.parent.mkdir(parents=True, exist_ok=True)
    if drc_json is not None:
        drc_json = drc_json.resolve()
        drc_json.parent.mkdir(parents=True, exist_ok=True)

    jar_path = ensure_freerouting_jar(config)

    build_dir = _build_dir()
    raw = build_dir / "freerouting_input_raw.dsn"
    cleaned = build_dir / "freerouting_input_cleaned.dsn"
    raw.unlink(missing_ok=True)
    cleaned.unlink(missing_ok=True)

    # Copy into build dir to keep container mounts simple and allow sanitization.
    raw.write_text(input_dsn.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    sanitize_dsn(raw, cleaned, pcb_name=input_dsn.name, strip_planes=config.strip_planes)

    jar_rel = os.path.relpath(jar_path.resolve(), repo_root)
    cleaned_rel = os.path.relpath(cleaned.resolve(), repo_root)

    # We want routed DSN (stable for hashing) rather than SES; FreeRouting can
    # only emit one `-do` output per run.
    output_rel = os.path.relpath(output_dsn.resolve(), repo_root) if output_dsn.is_relative_to(repo_root) else None
    if output_rel is None:
        raise ValueError(
            f"output_dsn must live under the repo root for docker mounts: {output_dsn}"
        )

    java_prefix = _java_invocation_prefix(config, repo_root)
    fr_args: list[str] = [
        *java_prefix,
        "-jar",
        f"/work/{jar_rel}",
        "-de",
        f"/work/{cleaned_rel}",
        "-do",
        f"/work/{output_rel}",
        "-host",
        "pardal",
    ]

    if config.disable_analytics:
        fr_args.append("-da")
    if not _logging_enabled(config):
        fr_args.append("-dl")
    elif config.log_level is not None:
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
        stdout_path=_resolve_optional_repo_path(repo_root, config.capture_stdout_path),
        stderr_path=_resolve_optional_repo_path(repo_root, config.capture_stderr_path),
    )

    if not output_dsn.exists():
        raise RuntimeError(f"FreeRouting did not produce output DSN: {output_dsn}")

    if drc_json is not None:
        drc_rel = os.path.relpath(drc_json.resolve(), repo_root)
        drc_args: list[str] = [
            *java_prefix,
            "-jar",
            f"/work/{jar_rel}",
            "-de",
            f"/work/{output_rel}",
            "-drc",
            f"/work/{drc_rel}",
            "-host",
            "pardal",
            "--gui.enabled=false",
        ]
        if config.disable_analytics:
            drc_args.append("-da")
        if not _logging_enabled(config):
            drc_args.append("-dl")
        elif config.log_level is not None:
            drc_args.extend(["-ll", str(config.log_level)])
        _docker_run(
            config.java_docker_image,
            workdir="/work",
            mounts=[(repo_root, "/work")],
            env=None,
            args=drc_args,
            stdout_path=_resolve_optional_repo_path(repo_root, config.capture_stdout_path),
            stderr_path=_resolve_optional_repo_path(repo_root, config.capture_stderr_path),
        )
