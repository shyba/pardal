#!/usr/bin/env python3
"""Run a parity fixture through FreeRouting oracle and Mojo backend-route.

This is the execution harness for the FreeRouting parity plan:

- Export DSN from the input KiCad PCB (docker KiCad 9).
- Run FreeRouting on DSN and import SES back into KiCad (docker KiCad 9).
- Run Mojo router via `backend-route` (extract problem.json via pcbnew docker,
  route on host, apply back via pcbnew docker).
- Run KiCad DRC JSON on both outputs (docker KiCad 9).
- Emit a single JSON summary for diff-friendly tracking.

This does *not* require any local KiCad installation, only Docker.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import textwrap
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pcb_tool.freerouting_backend import FreeroutingRunConfig, freeroute_kicad_pcb, sanitize_dsn
from pcb_tool.kicad_docker import DEFAULT_IMAGE, run_kicad_cli_in_docker


def _argv_has_flag(argv: list[str], flag: str) -> bool:
    return any(a == flag or a.startswith(f"{flag}=") for a in argv)


def _cfg_resolution_mm(cfg: Path | None) -> float | None:
    if cfg is None or not cfg.exists():
        return None
    try:
        payload = json.loads(cfg.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    for key in ("mojo_resolution_mm", "resolution_mm"):
        if key in payload:
            try:
                return float(payload[key])
            except (TypeError, ValueError):
                return None
    return None

def _with_max_time_ms(cfg: Path | None, *, out_path: Path, max_time_ms: int) -> Path:
    """Write a cfg JSON with max_time_ms overridden; return the written path."""
    payload: dict[str, Any] = {}
    if cfg is not None:
        payload = json.loads(cfg.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(payload, dict):
            payload = {}
    payload["max_time_ms"] = int(max_time_ms)
    # Keep single nets from consuming the entire budget when we want bounded runs.
    # This is a "budget harness" setting, not a recommended production default.
    if "per_net_time_ms" not in payload:
        # Previous cap of 1s per-net made large boards effectively impossible to
        # route even with larger overall budgets. Scale with the total budget,
        # but keep a sane upper bound so one net can't monopolize the whole run.
        payload["per_net_time_ms"] = int(max(50, min(30_000, max_time_ms // 20)))
    # Note: we intentionally do not force `ncr_iters` down here. Some fixtures
    # (e.g. fpga_large) rely on multiple passes to make progress.
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return out_path


def _with_json_overrides(cfg: Path | None, *, out_path: Path, overrides: dict[str, Any]) -> Path:
    payload: dict[str, Any] = {}
    if cfg is not None and cfg.exists():
        raw = json.loads(cfg.read_text(encoding="utf-8", errors="replace"))
        if isinstance(raw, dict):
            payload = raw
    for key, value in overrides.items():
        if value is not None:
            payload[str(key)] = value
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return out_path


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = max(0, min(len(ordered) - 1, int(math.ceil(float(q) * len(ordered)) - 1)))
    return ordered[rank]


@dataclass(frozen=True)
class DrcStats:
    violations: int
    unconnected: int


@dataclass(frozen=True)
class TimingStats:
    kicad_export_dsn_s: float
    freerouting_route_s: float
    mojo_backend_route_s: float
    kicad_drc_freerouting_s: float
    kicad_drc_mojo_s: float
    mojo_route_runs_s: list[float]
    mojo_route_p50_s: float
    mojo_route_p90_s: float
    mojo_route_min_s: float
    mojo_route_max_s: float
    mojo_route_warmup_s: float


@dataclass(frozen=True)
class IrStats:
    bbox_w_mm: float
    bbox_h_mm: float
    pins: int
    wires: int
    vias: int


@dataclass(frozen=True)
class FixtureSummary:
    fixture: str
    input_pcb: str
    kicad_raw_dsn: str
    kicad_dsn: str
    kicad_dsn_dump_json: str
    kicad_dsn_dump_ok: bool
    kicad_dsn_dump_error: str
    kicad_dsn_ir_json: str
    kicad_dsn_ir_ok: bool
    kicad_dsn_ir_error: str
    freerouting_out_pcb: str
    mojo_out_pcb: str
    freerouting_drc: DrcStats
    mojo_drc: DrcStats
    freerouting_drc_routing_only: DrcStats
    mojo_drc_routing_only: DrcStats
    delta_drc_violations: int
    delta_drc_unconnected: int
    delta_drc_violations_routing_only: int
    delta_drc_unconnected_routing_only: int
    mojo_failed_nets: int
    mojo_tracks: int
    mojo_vias: int
    routes_json: str
    problem_json: str
    freerouting_ok: bool
    freerouting_error: str
    mojo_ok: bool
    mojo_error: str
    freerouting_raw_dsn: str
    freerouting_dsn: str
    freerouting_ses: str
    freerouting_log_file: str
    freerouting_stdout_log: str
    freerouting_stderr_log: str
    freerouting_trace_jsonl: str
    freerouting_trace_ok: bool
    freerouting_trace_error: str
    freerouting_dsn_dump_json: str
    freerouting_dsn_dump_ok: bool
    freerouting_dsn_dump_error: str
    freerouting_dsn_ir_json: str
    freerouting_dsn_ir_ok: bool
    freerouting_dsn_ir_error: str
    kicad_ir_stats: IrStats
    freerouting_ir_stats: IrStats
    delta_ir_wires: int
    delta_ir_vias: int
    delta_ir_pins: int
    timing_s: TimingStats
    mojo_perf_json: str
    mojo_phase_times: dict[str, float]
    mojo_operation_counts: dict[str, int]
    mojo_perf_mode: str
    mojo_violation_types: dict[str, int]
    freerouting_violation_types: dict[str, int]


def _top_violation_types(types: dict[str, int], *, limit: int = 3) -> str:
    rows: list[tuple[str, int]] = []
    for key, value in (types or {}).items():
        try:
            v = int(value)
        except Exception:
            continue
        if v > 0:
            rows.append((str(key), v))
    rows.sort(key=lambda kv: (-kv[1], kv[0]))
    if not rows:
        return "none"
    return ", ".join(f"{k}={v}" for k, v in rows[: max(1, int(limit))])


def append_parity_diary_entry(
    *,
    diary_path: Path,
    summaries: list[FixtureSummary],
    source: str,
    label: str | None = None,
    suite_out_dir: Path | None = None,
) -> None:
    """Append a compact parity batch entry to the markdown diary."""
    if not summaries:
        return
    diary_path = diary_path.resolve()
    diary_path.parent.mkdir(parents=True, exist_ok=True)
    if not diary_path.exists():
        diary_path.write_text("# FreeRouting Parity Diary\n\n", encoding="utf-8")

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    title = f"## {stamp} ({source}"
    if label:
        title += f": {label}"
    title += ")"

    mojo_clean = 0
    fr_clean = 0
    lines = [title, ""]
    for s in summaries:
        if s.mojo_drc_routing_only.violations == 0 and s.mojo_drc_routing_only.unconnected == 0:
            mojo_clean += 1
        if s.freerouting_drc_routing_only.violations == 0 and s.freerouting_drc_routing_only.unconnected == 0:
            fr_clean += 1

        mojo_failed = (
            f", failed_nets={int(s.mojo_failed_nets)}" if int(s.mojo_failed_nets) >= 0 else ""
        )
        fr_text = "FR skipped"
        if int(s.freerouting_drc.violations) >= 0 and int(s.freerouting_drc.unconnected) >= 0:
            fr_text = (
                f"FR {int(s.freerouting_drc.violations)}/{int(s.freerouting_drc.unconnected)} "
                f"(routing-only {int(s.freerouting_drc_routing_only.violations)}/"
                f"{int(s.freerouting_drc_routing_only.unconnected)})"
            )
        lines.append(
            f"- `{s.fixture}`: Mojo {int(s.mojo_drc.violations)}/{int(s.mojo_drc.unconnected)} "
            f"(routing-only {int(s.mojo_drc_routing_only.violations)}/{int(s.mojo_drc_routing_only.unconnected)}"
            f"{mojo_failed}); {fr_text}; mojo_types={_top_violation_types(s.mojo_violation_types)}"
        )

    lines.append(f"- routing-only clean fixtures: Mojo {mojo_clean}/{len(summaries)}, FR {fr_clean}/{len(summaries)}")
    if suite_out_dir is not None:
        lines.append(f"- suite artifacts: `{suite_out_dir.resolve()}`")
    lines.append("")

    with diary_path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _require_docker() -> None:
    if shutil.which("docker") is None:
        raise RuntimeError("docker not found in PATH")


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    subprocess.run(cmd, cwd=str(cwd), check=True, env=env)


def _drc_json(pcb: Path, *, image: str, timeout_s: float) -> dict[str, Any]:
    out = pcb.with_suffix(pcb.suffix + ".drc.json")
    out.unlink(missing_ok=True)
    result = run_kicad_cli_in_docker(
        image=image,
        workdir_host=pcb.parent,
        args=[
            "pcb",
            "drc",
            "--format",
            "json",
            "-o",
            out.name,
            pcb.name,
        ],
        timeout_s=timeout_s,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or "kicad-cli pcb drc failed")
    return json.loads(out.read_text(encoding="utf-8", errors="replace"))


def _drc_stats(drc: dict[str, Any]) -> DrcStats:
    # KiCad 9 JSON schema: top-level has `violations` (list) and `unconnected_items` (list).
    v = drc.get("violations", []) or []
    u = drc.get("unconnected_items", []) or []
    return DrcStats(violations=len(v), unconnected=len(u))


def _violation_type_histogram(drc: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in drc.get("violations", []) or []:
        t = v.get("type") or "unknown"
        out[t] = out.get(t, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


def _routing_only_drc(stats: DrcStats, violation_types: dict[str, int]) -> DrcStats:
    """Return DRC counts excluding known non-routing footprint/library warnings."""
    if stats.violations < 0 or stats.unconnected < 0:
        return DrcStats(violations=-1, unconnected=-1)
    non_routing = int(violation_types.get("lib_footprint_issues", 0)) + int(
        violation_types.get("lib_footprint_mismatch", 0)
    )
    # Defensive clamp because downstream tools sometimes emit partial type maps.
    routing_violations = max(0, int(stats.violations) - non_routing)
    return DrcStats(violations=routing_violations, unconnected=int(stats.unconnected))


def _ir_stats_from_file(path: Path) -> IrStats:
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return IrStats(bbox_w_mm=-1.0, bbox_h_mm=-1.0, pins=-1, wires=-1, vias=-1)

    bb = payload.get("boundary_bbox_mm") or {}
    try:
        min_x = float(bb.get("min_x"))
        min_y = float(bb.get("min_y"))
        max_x = float(bb.get("max_x"))
        max_y = float(bb.get("max_y"))
        bbox_w = max_x - min_x
        bbox_h = max_y - min_y
    except Exception:
        bbox_w = -1.0
        bbox_h = -1.0

    pins = payload.get("pin_positions_mm") or {}
    wiring = payload.get("wiring_mm") or {}
    wires = wiring.get("wires") or []
    vias = wiring.get("vias") or []
    return IrStats(
        bbox_w_mm=bbox_w,
        bbox_h_mm=bbox_h,
        pins=len(pins) if isinstance(pins, dict) else -1,
        wires=len(wires) if isinstance(wires, list) else -1,
        vias=len(vias) if isinstance(vias, list) else -1,
    )


def _export_kicad_dsn(
    *,
    workspace_root: Path,
    input_pcb: Path,
    out_raw_dsn: Path,
    out_dsn: Path,
    image: str,
    cache: bool,
) -> None:
    out_raw_dsn.parent.mkdir(parents=True, exist_ok=True)
    out_dsn.parent.mkdir(parents=True, exist_ok=True)
    if cache and out_raw_dsn.exists() and out_raw_dsn.stat().st_size > 0 and out_dsn.exists() and out_dsn.stat().st_size > 0:
        return

    input_pcb = input_pcb.resolve()
    workspace_root = workspace_root.resolve()
    if input_pcb.is_relative_to(workspace_root):
        in_path_in_container = f"/work/{input_pcb.relative_to(workspace_root).as_posix()}"
    else:
        raise ValueError(f"Input PCB must be within workspace root: {workspace_root}")

    out_raw_dsn = out_raw_dsn.resolve()
    out_mounts: list[str] = []
    if out_raw_dsn.is_relative_to(workspace_root):
        out_path_in_container = f"/work/{out_raw_dsn.relative_to(workspace_root).as_posix()}"
    else:
        # Allow writing DSN into an external temp dir (e.g. pytest tmp_path).
        out_mounts = ["-v", f"{out_raw_dsn.parent}:/out"]
        out_path_in_container = f"/out/{out_raw_dsn.name}"
    try:
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{workspace_root}:/work",
                *out_mounts,
                "-w",
                "/work",
                "-e",
                f"IN_PCB={in_path_in_container}",
                "-e",
                f"OUT_DSN={out_path_in_container}",
                image,
                "python3",
                "-c",
                "import os, pcbnew\n"
                "b = pcbnew.LoadBoard(os.environ['IN_PCB'])\n"
                "ok = pcbnew.ExportSpecctraDSN(b, os.environ['OUT_DSN'])\n"
                "raise SystemExit(0 if ok else 1)\n",
            ],
            cwd=str(workspace_root),
            check=True,
        )
    except subprocess.CalledProcessError as e:
        # Some KiCad builds crash while exporting Specctra DSN for certain boards,
        # even though `LoadBoard()` succeeds. Many FreeRouting fixtures already
        # ship a `.dsn` alongside the `.kicad_pcb`, so fall back to that.
        sib_dir = input_pcb.parent
        dsn_candidates = sorted(sib_dir.glob("*.dsn")) + sorted(sib_dir.glob("*.DSN"))
        if not dsn_candidates:
            raise RuntimeError(
                f"KiCad DSN export failed for {input_pcb} (docker exit={e.returncode}) and no sibling .dsn found."
            ) from e
        preferred = [p for p in dsn_candidates if p.stem == input_pcb.stem]
        src = preferred[0] if preferred else dsn_candidates[0]
        out_raw_dsn.write_text(src.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")

    sanitize_dsn(out_raw_dsn, out_dsn, pcb_name=out_dsn.name, strip_planes=False)


def _ir_payload(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}


def _ir_counts(payload: dict[str, Any]) -> dict[str, int]:
    pins = payload.get("pin_positions_mm") or {}
    wiring = payload.get("wiring_mm") or {}
    wires = wiring.get("wires") or []
    vias = wiring.get("vias") or []
    return {
        "pins": len(pins) if isinstance(pins, dict) else -1,
        "wires": len(wires) if isinstance(wires, list) else -1,
        "vias": len(vias) if isinstance(vias, list) else -1,
    }


def _write_ir_diff(*, out_json: Path, a_name: str, a_ir: Path, b_name: str, b_ir: Path) -> None:
    a = _ir_payload(a_ir)
    b = _ir_payload(b_ir)
    out = {
        "a": {"name": a_name, "path": str(a_ir), "counts": _ir_counts(a)},
        "b": {"name": b_name, "path": str(b_ir), "counts": _ir_counts(b)},
    }
    out_json.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")

def _freerouting_build_dir(repo_root: Path) -> Path:
    # Matches `pcb_tool.freerouting_backend._build_dir()` (pardal-pcb/build/freerouting).
    return repo_root / "pardal-pcb" / "build" / "freerouting"


def _copy_if_exists(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


def _copy_freerouting_artifacts(repo_root: Path, out_dir: Path, fixture_name: str) -> tuple[Path, Path, Path]:
    """Copy FreeRouting intermediate artifacts into the fixture out-dir (best effort)."""
    build_dir = _freerouting_build_dir(repo_root)
    raw_dsn = build_dir / "freerouting_raw.dsn"
    dsn = build_dir / "freerouting.dsn"
    ses = build_dir / "freerouting.ses"

    raw_out = out_dir / f"{fixture_name}.freerouting_raw.dsn"
    dsn_out = out_dir / f"{fixture_name}.freerouting.dsn"
    ses_out = out_dir / f"{fixture_name}.freerouting.ses"

    _copy_if_exists(raw_dsn, raw_out)
    _copy_if_exists(dsn, dsn_out)
    _copy_if_exists(ses, ses_out)
    return raw_out, dsn_out, ses_out


def _resolve_freerouting_runtime_log(
    *,
    workspace_root: Path,
    config: FreeroutingRunConfig,
) -> Path | None:
    rel = str(config.java_tmpdir_relpath or "").strip().replace("\\", "/").lstrip("/")
    if not rel:
        return None
    return (workspace_root / rel).resolve() / "freerouting" / "freerouting.log"


def _trace_jsonl_from_jvm_props(
    *,
    workspace_root: Path,
    config: FreeroutingRunConfig,
) -> Path | None:
    prefix = "-Dfreerouting.trace.path="
    for prop in config.jvm_props:
        text = str(prop)
        if not text.startswith(prefix):
            continue
        raw = text[len(prefix) :].strip()
        if not raw:
            return None
        if raw.startswith("/work/"):
            return (workspace_root / raw[len("/work/") :]).resolve()
        p = Path(raw)
        return p.resolve() if p.is_absolute() else (workspace_root / p).resolve()
    return None


def _materialize_footprint_libraries(
    *,
    workspace_root: Path,
    input_pcb: Path,
    out_dir: Path,
    image: str,
    cache: bool,
) -> None:
    """Build a local fp-lib-table + .pretty libs from footprints embedded in the PCB.

    This normalizes DRC runs by making all referenced footprint libraries available
    in the parity output dir. It is useful for fixtures where routing is valid but
    KiCad emits `lib_footprint_*` warnings due to missing project library tables.
    """
    norm_lib_root = out_dir / "_norm_fp_libs"
    fp_lib_table = out_dir / "fp-lib-table"
    if cache and fp_lib_table.exists() and norm_lib_root.exists():
        return

    if norm_lib_root.exists():
        shutil.rmtree(norm_lib_root)
    norm_lib_root.mkdir(parents=True, exist_ok=True)

    workspace_root = workspace_root.resolve()
    input_pcb = input_pcb.resolve()
    out_dir = out_dir.resolve()
    if not input_pcb.is_relative_to(workspace_root):
        raise ValueError(f"Input PCB must be within workspace root: {workspace_root}")
    if not out_dir.is_relative_to(workspace_root):
        raise ValueError(f"Output dir must be within workspace root: {workspace_root}")

    in_pcb_container = f"/work/{input_pcb.relative_to(workspace_root).as_posix()}"
    out_dir_container = f"/work/{out_dir.relative_to(workspace_root).as_posix()}"

    host_script = textwrap.dedent(
        r"""
        import os
        import re
        from pathlib import Path
        import pcbnew

        in_pcb = Path(os.environ["IN_PCB"])
        out_dir = Path(os.environ["OUT_DIR"])
        lib_root = out_dir / "_norm_fp_libs"
        lib_root.mkdir(parents=True, exist_ok=True)

        board = pcbnew.LoadBoard(str(in_pcb))
        io = None
        try:
            if hasattr(pcbnew, "PCB_IO_MGR"):
                io = pcbnew.PCB_IO_MGR.PluginFind(pcbnew.PCB_IO_MGR.KICAD_SEXP)
        except Exception:
            io = None
        by_lib = {}
        used_slugs = set()
        for fp in board.GetFootprints():
            fpid = fp.GetFPID()
            lib = str(fpid.GetLibNickname() or "").strip()
            item = str(fpid.GetLibItemName() or "").strip()
            if not lib or not item:
                continue
            if lib not in by_lib:
                slug = re.sub(r"[^A-Za-z0-9_.+-]+", "_", lib).strip("._")
                if not slug:
                    slug = "lib"
                base_slug = slug
                n = 1
                while slug in used_slugs:
                    n += 1
                    slug = f"{base_slug}_{n}"
                used_slugs.add(slug)
                lib_dir = lib_root / f"{slug}.pretty"
                lib_dir.mkdir(parents=True, exist_ok=True)
                by_lib[lib] = {"slug": slug, "items": set(), "dir": lib_dir}
            if item in by_lib[lib]["items"]:
                continue
            # Save a normalized library instance (origin/orientation reset).
            # FootprintSave on board instances can embed placement-dependent
            # geometry (notably zone polygons), which triggers
            # lib_footprint_mismatch for identical items used at different XY.
            fp_norm = fp.Duplicate()
            try:
                fp_norm.SetOrientationDegrees(0)
            except Exception:
                pass
            try:
                fp_norm.SetPosition(pcbnew.VECTOR2I(0, 0))
            except Exception:
                pass
            try:
                fp_norm.SetReference("REF**")
            except Exception:
                pass
            try:
                fp_norm.SetValue(item)
            except Exception:
                pass
            if io is not None:
                io.FootprintSave(str(by_lib[lib]["dir"]), fp_norm)
            else:
                pcbnew.FootprintSave(str(by_lib[lib]["dir"]), fp_norm)
            mod_path = by_lib[lib]["dir"] / f"{item}.kicad_mod"
            if mod_path.exists():
                mod_text = mod_path.read_text(encoding="utf-8", errors="replace")
                # Normalize volatile instance-level fields to reduce false mismatch noise.
                mod_text = re.sub(r'\s+\(tstamp [^)]+\)', "", mod_text)
                mod_text = re.sub(r'^\s*\(property\s+"Sheetfile".*\)\n?', "", mod_text, flags=re.MULTILINE)
                mod_text = re.sub(r'^\s*\(property\s+"Sheetname".*\)\n?', "", mod_text, flags=re.MULTILINE)
                mod_text = re.sub(r'^\s*\(path\s+".*"\)\n?', "", mod_text, flags=re.MULTILINE)
                mod_path.write_text(mod_text, encoding="utf-8")
            by_lib[lib]["items"].add(item)

        lines = ["(fp_lib_table"]
        for lib in sorted(by_lib):
            slug = by_lib[lib].get("slug")
            if not slug:
                continue
            uri = f"${{KIPRJMOD}}/_norm_fp_libs/{slug}.pretty"
            safe_lib = lib.replace('"', '\\"')
            safe_uri = uri.replace('"', '\\"')
            lines.append(
                f'  (lib (name "{safe_lib}")(type "KiCad")(uri "{safe_uri}")(options "")(descr "autogenerated parity fixture"))'
            )
        lines.append(")")
        (out_dir / "fp-lib-table").write_text("\n".join(lines) + "\n", encoding="utf-8")
        """
    ).strip()

    host_env = dict(os.environ)
    host_env["IN_PCB"] = str(input_pcb)
    host_env["OUT_DIR"] = str(out_dir)
    try:
        subprocess.run(
            ["python3", "-c", host_script],
            cwd=str(workspace_root),
            env=host_env,
            check=True,
        )
        return
    except Exception:
        # Local pcbnew may be missing or too old for KiCad 9 board files.
        pass

    try:
        # First docker fallback: run the same pcbnew-based normalizer in the
        # KiCad container so we can preserve canonical library geometry.
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{workspace_root}:/work",
                "-w",
                "/work",
                "-e",
                f"IN_PCB={in_pcb_container}",
                "-e",
                f"OUT_DIR={out_dir_container}",
                image,
                "python3",
                "-c",
                host_script,
            ],
            cwd=str(workspace_root),
            check=True,
        )
        return
    except Exception:
        # Last resort: parser-only extraction path (less accurate for some
        # footprint geometry, but keeps parity runs unblocked).
        pass

    script = textwrap.dedent(
        r"""
        import os
        import re
        from pathlib import Path

        in_pcb = Path(os.environ["IN_PCB"])
        out_dir = Path(os.environ["OUT_DIR"])
        lib_root = out_dir / "_norm_fp_libs"
        lib_root.mkdir(parents=True, exist_ok=True)

        text = in_pcb.read_text(encoding="utf-8", errors="replace")

        def _extract_footprints(src: str):
            needle = '(footprint "'
            i = 0
            n = len(src)
            while i < n:
                j = src.find(needle, i)
                if j < 0:
                    return
                # Parse the first string literal (footprint id).
                p = j + len('(footprint "')
                q = p
                escaped = False
                while q < n:
                    ch = src[q]
                    if escaped:
                        escaped = False
                    elif ch == "\\":
                        escaped = True
                    elif ch == '"':
                        break
                    q += 1
                if q >= n:
                    return
                fpid = src[p:q]
                # Parse balanced S-expression from j.
                depth = 0
                k = j
                in_str = False
                esc = False
                while k < n:
                    ch = src[k]
                    if in_str:
                        if esc:
                            esc = False
                        elif ch == "\\":
                            esc = True
                        elif ch == '"':
                            in_str = False
                    else:
                        if ch == '"':
                            in_str = True
                        elif ch == "(":
                            depth += 1
                        elif ch == ")":
                            depth -= 1
                            if depth == 0:
                                k += 1
                                break
                    k += 1
                block = src[j:k]
                yield fpid, block
                i = k

        by_lib = {}
        used_slugs = set()
        for fpid, block in _extract_footprints(text):
            if ":" not in fpid:
                continue
            lib, item = fpid.split(":", 1)
            lib = lib.strip()
            item = item.strip()
            if not lib or not item:
                continue
            if lib not in by_lib:
                slug = re.sub(r"[^A-Za-z0-9_.+-]+", "_", lib).strip("._")
                if not slug:
                    slug = "lib"
                base_slug = slug
                n = 1
                while slug in used_slugs:
                    n += 1
                    slug = f"{base_slug}_{n}"
                used_slugs.add(slug)
                lib_dir = lib_root / f"{slug}.pretty"
                lib_dir.mkdir(parents=True, exist_ok=True)
                by_lib[lib] = {"slug": slug, "items": set(), "dir": lib_dir}
            if item in by_lib[lib]["items"]:
                continue
            item_safe = re.sub(r"[/\\\\]+", "_", item)
            # In .kicad_mod the footprint name should be the item name only.
            patched = re.sub(
                r'^\(footprint\s+"[^"]+"',
                f'(footprint "{item}"',
                block,
                count=1,
                flags=re.MULTILINE,
            )
            (by_lib[lib]["dir"] / f"{item_safe}.kicad_mod").write_text(
                patched + "\n", encoding="utf-8"
            )
            by_lib[lib]["items"].add(item)

        lines = ["(fp_lib_table"]
        for lib in sorted(by_lib):
            slug = by_lib[lib].get("slug")
            if not slug:
                continue
            uri = f"${{KIPRJMOD}}/_norm_fp_libs/{slug}.pretty"
            safe_lib = lib.replace('"', '\\"')
            safe_uri = uri.replace('"', '\\"')
            lines.append(
                f'  (lib (name "{safe_lib}")(type "KiCad")(uri "{safe_uri}")(options "")(descr "autogenerated parity fixture"))'
            )
        lines.append(")")
        (out_dir / "fp-lib-table").write_text("\n".join(lines) + "\n", encoding="utf-8")
        """
    ).strip()

    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{workspace_root}:/work",
            "-w",
            "/work",
            "-e",
            f"IN_PCB={in_pcb_container}",
            "-e",
            f"OUT_DIR={out_dir_container}",
            image,
            "python3",
            "-c",
            script,
        ],
        cwd=str(workspace_root),
        check=True,
    )


def _backend_route(
    *,
    project_root: Path,
    in_pcb: Path,
    out_pcb: Path,
    cfg_json: Path | None,
    resolution_mm: float,
    inflate_mm: float | None,
    docker_image: str,
    extract_timeout_s: float | None,
    route_timeout_s: float | None,
    apply_timeout_s: float | None,
    perf_json: Path | None,
    perf_mode: str,
) -> None:
    cmd = [
        str(project_root / "venv" / "bin" / "python"),
        "-m",
        "pcb_tool.cli",
        "backend-route",
        str(in_pcb.resolve()),
        "-o",
        str(out_pcb.resolve()),
        "--docker-image",
        docker_image,
        "--resolution",
        str(float(resolution_mm)),
    ]
    if inflate_mm is not None:
        cmd += ["--inflate", str(float(inflate_mm))]
    if cfg_json is not None:
        cmd += ["--cfg", str(cfg_json)]
    if extract_timeout_s is not None:
        cmd += ["--extract-timeout-s", str(float(extract_timeout_s))]
    if route_timeout_s is not None:
        cmd += ["--route-timeout-s", str(float(route_timeout_s))]
    if apply_timeout_s is not None:
        cmd += ["--apply-timeout-s", str(float(apply_timeout_s))]
    run_env = os.environ.copy()
    if perf_json is not None:
        run_env["PARDAL_PERF_JSON"] = str(perf_json.resolve())
    else:
        run_env.pop("PARDAL_PERF_JSON", None)
    if perf_mode:
        run_env["PARDAL_PERF_MODE"] = str(perf_mode)
    else:
        run_env.pop("PARDAL_PERF_MODE", None)
    _run(cmd, cwd=project_root, env=run_env)


def _mojo_dsn_dump(
    *,
    repo_root: Path,
    in_dsn: Path,
    out_json: Path,
    cache: bool,
) -> None:
    if cache and out_json.exists() and out_json.stat().st_size > 0:
        return
    out_json.unlink(missing_ok=True)
    router_bin = repo_root / "pardal_router_mojo" / "build" / "pardal-router-mojo"
    if not router_bin.exists():
        build_script = repo_root / "pardal_router_mojo" / "build.sh"
        if build_script.exists():
            subprocess.run([str(build_script)], cwd=str(build_script.parent), check=True)
    if not router_bin.exists():
        raise FileNotFoundError(router_bin)
    subprocess.run([str(router_bin), "dsn-dump", str(in_dsn), str(out_json)], cwd=str(repo_root), check=True)

def _mojo_dsn_ir(
    *,
    repo_root: Path,
    in_dsn: Path,
    out_json: Path,
    cache: bool,
) -> None:
    if cache and out_json.exists() and out_json.stat().st_size > 0:
        return
    out_json.unlink(missing_ok=True)
    router_bin = repo_root / "pardal_router_mojo" / "build" / "pardal-router-mojo"
    if not router_bin.exists():
        build_script = repo_root / "pardal_router_mojo" / "build.sh"
        if build_script.exists():
            subprocess.run([str(build_script)], cwd=str(build_script.parent), check=True)
    if not router_bin.exists():
        raise FileNotFoundError(router_bin)
    subprocess.run([str(router_bin), "dsn-ir", str(in_dsn), str(out_json)], cwd=str(repo_root), check=True)


def run_fixture(
    *,
    workspace_root: Path,
    project_root: Path,
    fixture_name: str,
    input_pcb: Path,
    out_dir: Path,
    kicad_image: str,
    freerouting_cfg: FreeroutingRunConfig,
    mojo_cfg_json: Path | None,
    mojo_resolution_mm: float,
    mojo_inflate_mm: float | None,
    run_freerouting: bool,
    run_mojo: bool,
    cache: bool,
    drc_timeout_s: float,
    mojo_dump_dsn: bool,
    mojo_dump_ir: bool,
    normalize_footprint_libs: bool,
    mojo_extract_timeout_s: float | None,
    mojo_route_timeout_s: float | None,
    mojo_apply_timeout_s: float | None,
    mojo_warm_runs: int,
    mojo_perf_json: Path | None,
    mojo_perf_mode: str,
) -> FixtureSummary:
    _require_docker()
    input_pcb = input_pcb.resolve()
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    repo_root = project_root
    timing = TimingStats(0.0, 0.0, 0.0, 0.0, 0.0, [], 0.0, 0.0, 0.0, 0.0, 0.0)
    mojo_phase_times: dict[str, float] = {}
    mojo_operation_counts: dict[str, int] = {}
    mojo_perf_json_written = ""
    mojo_mode = str(mojo_perf_mode or "safe").strip().lower()
    if mojo_mode not in {"safe", "fast"}:
        mojo_mode = "safe"
    warm_runs = max(1, int(mojo_warm_runs))
    if warm_runs > 1:
        cache = False

    if normalize_footprint_libs:
        _materialize_footprint_libraries(
            workspace_root=workspace_root,
            input_pcb=input_pcb,
            out_dir=out_dir,
            image=kicad_image,
            cache=cache,
        )

    # 0) Always export the KiCad DSN (even in Mojo-only runs) so we have a stable,
    # inspectable interchange artifact.
    kicad_raw_dsn = out_dir / f"{fixture_name}.kicad_raw.dsn"
    kicad_dsn = out_dir / f"{fixture_name}.kicad.dsn"
    kicad_dsn_dump = out_dir / f"{fixture_name}.kicad.dsn.dump.json"
    kicad_dsn_ir = out_dir / f"{fixture_name}.kicad.dsn.ir.json"
    t0 = time.perf_counter()
    _export_kicad_dsn(
        workspace_root=workspace_root,
        input_pcb=input_pcb,
        out_raw_dsn=kicad_raw_dsn,
        out_dsn=kicad_dsn,
        image=kicad_image,
        cache=cache,
    )
    t_export = time.perf_counter() - t0
    dsn_dump_ok = False
    dsn_dump_err = ""
    ir_ok = False
    ir_err = ""
    if mojo_dump_dsn and kicad_dsn.exists() and kicad_dsn.stat().st_size > 0:
        try:
            _mojo_dsn_dump(repo_root=repo_root, in_dsn=kicad_dsn, out_json=kicad_dsn_dump, cache=cache)
            dsn_dump_ok = True
        except Exception as e:  # noqa: BLE001
            dsn_dump_ok = False
            dsn_dump_err = f"{type(e).__name__}: {e}"
    if mojo_dump_ir and kicad_dsn.exists() and kicad_dsn.stat().st_size > 0:
        try:
            _mojo_dsn_ir(repo_root=repo_root, in_dsn=kicad_dsn, out_json=kicad_dsn_ir, cache=cache)
            ir_ok = True
        except Exception as e:  # noqa: BLE001
            ir_ok = False
            ir_err = f"{type(e).__name__}: {e}"

    # 1) FreeRouting oracle: routes and writes a KiCad PCB.
    freerouting_out = out_dir / f"{fixture_name}.freerouting.kicad_pcb"
    freerouting_ok = True
    freerouting_error = ""
    t_fr = 0.0
    raw_dsn_out = out_dir / f"{fixture_name}.freerouting_raw.dsn"
    dsn_out = out_dir / f"{fixture_name}.freerouting.dsn"
    ses_out = out_dir / f"{fixture_name}.freerouting.ses"
    fr_runtime_log_src = _resolve_freerouting_runtime_log(workspace_root=workspace_root, config=freerouting_cfg)
    fr_runtime_log_out = out_dir / f"{fixture_name}.freerouting.log"
    fr_stdout_log_path = (
        Path(freerouting_cfg.capture_stdout_path).resolve()
        if freerouting_cfg.capture_stdout_path is not None
        else None
    )
    fr_stderr_log_path = (
        Path(freerouting_cfg.capture_stderr_path).resolve()
        if freerouting_cfg.capture_stderr_path is not None
        else None
    )
    fr_trace_jsonl_path = _trace_jsonl_from_jvm_props(workspace_root=workspace_root, config=freerouting_cfg)
    fr_trace_ok = False
    fr_trace_err = ""
    fr_dsn_dump = out_dir / f"{fixture_name}.freerouting.dsn.dump.json"
    fr_dsn_dump_ok = False
    fr_dsn_dump_err = ""
    fr_dsn_ir = out_dir / f"{fixture_name}.freerouting.dsn.ir.json"
    fr_dsn_ir_ok = False
    fr_dsn_ir_err = ""
    fr_kicad_raw_dsn = out_dir / f"{fixture_name}.freerouting.kicad_raw.dsn"
    fr_kicad_dsn = out_dir / f"{fixture_name}.freerouting.kicad.dsn"
    fr_kicad_dsn_dump = out_dir / f"{fixture_name}.freerouting.kicad.dsn.dump.json"
    fr_kicad_dsn_ir = out_dir / f"{fixture_name}.freerouting.kicad.dsn.ir.json"
    fr_kicad_dump_ok = False
    fr_kicad_ir_ok = False
    if run_freerouting:
        if not cache:
            if fr_runtime_log_src is not None:
                fr_runtime_log_src.unlink(missing_ok=True)
            fr_runtime_log_out.unlink(missing_ok=True)
            if fr_stdout_log_path is not None:
                fr_stdout_log_path.unlink(missing_ok=True)
            if fr_stderr_log_path is not None:
                fr_stderr_log_path.unlink(missing_ok=True)
            if fr_trace_jsonl_path is not None:
                fr_trace_jsonl_path.unlink(missing_ok=True)
        if cache and freerouting_out.exists() and freerouting_out.stat().st_size > 0:
            t_fr = 0.0
        else:
            try:
                t0 = time.perf_counter()
                freeroute_kicad_pcb(input_pcb, freerouting_out, config=freerouting_cfg)
                t_fr = time.perf_counter() - t0
            except Exception as e:  # noqa: BLE001
                freerouting_ok = False
                freerouting_error = f"{type(e).__name__}: {e}"
                t_fr = 0.0
        # Always try to copy intermediates for inspection (even if routing failed).
        raw_dsn_out, dsn_out, ses_out = _copy_freerouting_artifacts(workspace_root, out_dir, fixture_name)
        if fr_runtime_log_src is not None:
            _copy_if_exists(fr_runtime_log_src, fr_runtime_log_out)
        if fr_trace_jsonl_path is not None:
            if fr_trace_jsonl_path.exists() and fr_trace_jsonl_path.stat().st_size > 0:
                fr_trace_ok = True
                fr_trace_err = ""
            else:
                fr_trace_ok = False
                fr_trace_err = "trace file not produced"
        if mojo_dump_dsn and dsn_out.exists() and dsn_out.stat().st_size > 0:
            try:
                _mojo_dsn_dump(repo_root=repo_root, in_dsn=dsn_out, out_json=fr_dsn_dump, cache=cache)
                fr_dsn_dump_ok = True
            except Exception as e:  # noqa: BLE001
                fr_dsn_dump_ok = False
                fr_dsn_dump_err = f"{type(e).__name__}: {e}"
        if mojo_dump_ir and dsn_out.exists() and dsn_out.stat().st_size > 0:
            try:
                _mojo_dsn_ir(repo_root=repo_root, in_dsn=dsn_out, out_json=fr_dsn_ir, cache=cache)
                fr_dsn_ir_ok = True
            except Exception as e:  # noqa: BLE001
                fr_dsn_ir_ok = False
                fr_dsn_ir_err = f"{type(e).__name__}: {e}"

        # Export a fresh DSN from the FreeRouting-output PCB (captures wiring) for IR/dump comparisons.
        if freerouting_ok and freerouting_out.exists() and freerouting_out.stat().st_size > 0:
            try:
                _export_kicad_dsn(
                    workspace_root=workspace_root,
                    input_pcb=freerouting_out,
                    out_raw_dsn=fr_kicad_raw_dsn,
                    out_dsn=fr_kicad_dsn,
                    image=kicad_image,
                    cache=cache,
                )
                if mojo_dump_dsn:
                    _mojo_dsn_dump(repo_root=repo_root, in_dsn=fr_kicad_dsn, out_json=fr_kicad_dsn_dump, cache=cache)
                    fr_kicad_dump_ok = True
                if mojo_dump_ir:
                    _mojo_dsn_ir(repo_root=repo_root, in_dsn=fr_kicad_dsn, out_json=fr_kicad_dsn_ir, cache=cache)
                    fr_kicad_ir_ok = True
            except Exception:
                pass
    else:
        t_fr = 0.0

    # 2) Mojo backend route (problem.json pipeline).
    mojo_out = out_dir / f"{fixture_name}.mojo.kicad_pcb"
    routes_json = mojo_out.with_suffix(".routes.json")
    problem_json = mojo_out.with_suffix(".problem.json")
    mojo_ok = True
    mojo_error = ""
    mojo_route_runs_s: list[float] = []
    mojo_route_warmup_s = 0.0
    def _extract_perf_metrics(doc: object) -> tuple[dict[str, float], dict[str, int]]:
        phase_times: dict[str, float] = {}
        operation_counts: dict[str, int] = {}
        perf_payload = doc.get("perf", doc) if isinstance(doc, dict) else {}
        if isinstance(perf_payload, dict):
            raw_phase_times = perf_payload.get("phase_times")
            if isinstance(raw_phase_times, dict):
                phase_times = {
                    str(k): float(v) for k, v in raw_phase_times.items() if isinstance(v, (int, float))
                }
            raw_operation_counts = perf_payload.get("operation_counts")
            if isinstance(raw_operation_counts, dict):
                operation_counts = {
                    str(k): int(v) for k, v in raw_operation_counts.items() if isinstance(v, (int, float))
                }
        return phase_times, operation_counts
    if run_mojo and (not (cache and mojo_out.exists() and mojo_out.stat().st_size > 0)):
        # Ensure artifacts are refreshed together.
        routes_json.unlink(missing_ok=True)
        problem_json.unlink(missing_ok=True)
        if mojo_perf_json is not None:
            base_suffix = mojo_perf_json.suffix if mojo_perf_json.suffix else ".json"
            for stale in mojo_perf_json.parent.glob(f"{mojo_perf_json.stem}.*{base_suffix}"):
                stale.unlink(missing_ok=True)
        total_runs = warm_runs
        warmup_runs = 1 if warm_runs > 1 else 0
        run_i = 0
        measured_i = 0
        while run_i < (total_runs + warmup_runs):
            is_warmup = run_i < warmup_runs
            run_perf_json: Path | None = None
            if mojo_perf_json is not None:
                suffix = mojo_perf_json.suffix if mojo_perf_json.suffix else ".json"
                if total_runs + warmup_runs == 1:
                    run_perf_json = mojo_perf_json
                elif is_warmup:
                    run_perf_json = mojo_perf_json.with_name(f"{mojo_perf_json.stem}.warmup{suffix}")
                else:
                    run_perf_json = mojo_perf_json.with_name(f"{mojo_perf_json.stem}.run{measured_i + 1}{suffix}")
                run_perf_json.parent.mkdir(parents=True, exist_ok=True)
                run_perf_json.unlink(missing_ok=True)
            t0 = time.perf_counter()
            try:
                _backend_route(
                    project_root=project_root,
                    in_pcb=input_pcb,
                    out_pcb=mojo_out,
                    cfg_json=mojo_cfg_json,
                    resolution_mm=mojo_resolution_mm,
                    inflate_mm=mojo_inflate_mm,
                    docker_image=kicad_image,
                    extract_timeout_s=mojo_extract_timeout_s,
                    route_timeout_s=mojo_route_timeout_s,
                    apply_timeout_s=mojo_apply_timeout_s,
                    perf_json=run_perf_json,
                    perf_mode=mojo_mode,
                )
            except Exception as e:  # noqa: BLE001
                mojo_ok = False
                mojo_error = f"{type(e).__name__}: {e}"
                break
            dt = time.perf_counter() - t0
            if is_warmup:
                mojo_route_warmup_s = dt
            else:
                mojo_route_runs_s.append(dt)
                measured_i += 1
                if run_perf_json is not None and run_perf_json.exists():
                    mojo_perf_json_written = str(run_perf_json)
                elif run_perf_json is not None:
                    mojo_perf_json_written = ""
            run_i += 1
        if mojo_ok and mojo_route_runs_s:
            t_mojo = _percentile(mojo_route_runs_s, 0.5)
        else:
            t_mojo = 0.0
    else:
        t_mojo = 0.0

    # 2b) Export DSN from the Mojo-output PCB for IR/dump comparisons.
    mojo_kicad_raw_dsn = out_dir / f"{fixture_name}.mojo.kicad_raw.dsn"
    mojo_kicad_dsn = out_dir / f"{fixture_name}.mojo.kicad.dsn"
    mojo_kicad_dsn_dump = out_dir / f"{fixture_name}.mojo.kicad.dsn.dump.json"
    mojo_kicad_dsn_ir = out_dir / f"{fixture_name}.mojo.kicad.dsn.ir.json"
    mojo_kicad_dump_ok = False
    mojo_kicad_ir_ok = False
    if run_mojo and mojo_out.exists() and mojo_out.stat().st_size > 0:
        try:
            _export_kicad_dsn(
                workspace_root=workspace_root,
                input_pcb=mojo_out,
                out_raw_dsn=mojo_kicad_raw_dsn,
                out_dsn=mojo_kicad_dsn,
                image=kicad_image,
                cache=cache,
            )
            if mojo_dump_dsn:
                _mojo_dsn_dump(repo_root=repo_root, in_dsn=mojo_kicad_dsn, out_json=mojo_kicad_dsn_dump, cache=cache)
                mojo_kicad_dump_ok = True
            if mojo_dump_ir:
                _mojo_dsn_ir(repo_root=repo_root, in_dsn=mojo_kicad_dsn, out_json=mojo_kicad_dsn_ir, cache=cache)
                mojo_kicad_ir_ok = True
        except Exception:
            pass

    # If we have IRs, write small diff snapshots for later classification work.
    if mojo_dump_ir and kicad_dsn_ir.exists() and fr_kicad_dsn_ir.exists() and fr_kicad_ir_ok:
        _write_ir_diff(
            out_json=out_dir / f"{fixture_name}.ir_diff.kicad_vs_freerouting_output.json",
            a_name="kicad",
            a_ir=kicad_dsn_ir,
            b_name="freerouting_output",
            b_ir=fr_kicad_dsn_ir,
        )
    if mojo_dump_ir and kicad_dsn_ir.exists() and mojo_kicad_dsn_ir.exists() and mojo_kicad_ir_ok:
        _write_ir_diff(
            out_json=out_dir / f"{fixture_name}.ir_diff.kicad_vs_mojo.json",
            a_name="kicad",
            a_ir=kicad_dsn_ir,
            b_name="mojo_output",
            b_ir=mojo_kicad_dsn_ir,
        )
    if mojo_dump_ir and fr_kicad_dsn_ir.exists() and fr_kicad_ir_ok and mojo_kicad_dsn_ir.exists() and mojo_kicad_ir_ok:
        _write_ir_diff(
            out_json=out_dir / f"{fixture_name}.ir_diff.freerouting_output_vs_mojo.json",
            a_name="freerouting_output",
            a_ir=fr_kicad_dsn_ir,
            b_name="mojo_output",
            b_ir=mojo_kicad_dsn_ir,
        )

    # 3) DRC for both.
    fr_types: dict[str, int] = {}
    if run_freerouting:
        fr_drc_path = freerouting_out.with_suffix(freerouting_out.suffix + ".drc.json")
        if freerouting_ok and cache and fr_drc_path.exists() and fr_drc_path.stat().st_size > 0:
            fr_drc = json.loads(fr_drc_path.read_text(encoding="utf-8", errors="replace"))
            fr_stats = _drc_stats(fr_drc)
            fr_types = _violation_type_histogram(fr_drc)
            t_fr_drc = 0.0
        elif freerouting_ok:
            t0 = time.perf_counter()
            fr_drc = _drc_json(freerouting_out, image=kicad_image, timeout_s=drc_timeout_s)
            t_fr_drc = time.perf_counter() - t0
            fr_drc_path.write_text(json.dumps(fr_drc, indent=2, sort_keys=True), encoding="utf-8")
            fr_stats = _drc_stats(fr_drc)
            fr_types = _violation_type_histogram(fr_drc)
        else:
            fr_stats = DrcStats(violations=-1, unconnected=-1)
            t_fr_drc = 0.0
    else:
        fr_stats = DrcStats(violations=-1, unconnected=-1)
        t_fr_drc = 0.0
        fr_types = {}

    if run_mojo:
        if mojo_ok and mojo_out.exists() and mojo_out.stat().st_size > 0:
            t0 = time.perf_counter()
            mojo_drc = _drc_json(mojo_out, image=kicad_image, timeout_s=drc_timeout_s)
            t_mojo_drc = time.perf_counter() - t0
            mojo_drc_path = mojo_out.with_suffix(mojo_out.suffix + ".drc.json")
            mojo_drc_path.write_text(json.dumps(mojo_drc, indent=2, sort_keys=True), encoding="utf-8")
            mojo_types = _violation_type_histogram(mojo_drc)
            mojo_stats = _drc_stats(mojo_drc)
        else:
            mojo_drc = {}
            t_mojo_drc = 0.0
            mojo_types = {}
            mojo_stats = DrcStats(violations=-1, unconnected=-1)
    else:
        mojo_drc = {}
        t_mojo_drc = 0.0
        mojo_types = {}
        mojo_stats = DrcStats(violations=-1, unconnected=-1)

    delta_viol = -1
    delta_unconn = -1
    fr_routing_only_stats = _routing_only_drc(fr_stats, fr_types)
    mojo_routing_only_stats = _routing_only_drc(mojo_stats, mojo_types)
    delta_viol_routing_only = -1
    delta_unconn_routing_only = -1
    if run_freerouting and run_mojo and freerouting_ok and fr_stats.violations >= 0 and fr_stats.unconnected >= 0:
        delta_viol = mojo_stats.violations - fr_stats.violations
        delta_unconn = mojo_stats.unconnected - fr_stats.unconnected
    if (
        run_freerouting
        and run_mojo
        and freerouting_ok
        and fr_routing_only_stats.violations >= 0
        and fr_routing_only_stats.unconnected >= 0
    ):
        delta_viol_routing_only = mojo_routing_only_stats.violations - fr_routing_only_stats.violations
        delta_unconn_routing_only = mojo_routing_only_stats.unconnected - fr_routing_only_stats.unconnected

    # 4) Completion stats from routes.json (if present).
    mojo_failed = -1
    mojo_tracks = -1
    mojo_vias = -1
    if run_mojo and routes_json.exists():
        try:
            payload = json.loads(routes_json.read_text(encoding="utf-8", errors="replace"))
            mojo_failed = len(payload.get("failed_nets", []) or [])
            mojo_tracks = len(payload.get("tracks", []) or [])
            mojo_vias = len(payload.get("vias", []) or [])
            phase_times, operation_counts = _extract_perf_metrics(payload)
            if phase_times:
                mojo_phase_times = phase_times
            if operation_counts:
                mojo_operation_counts = operation_counts
        except Exception:
            pass

    if mojo_perf_json_written:
        perf_path = Path(mojo_perf_json_written)
        if perf_path.exists():
            try:
                perf_doc = json.loads(perf_path.read_text(encoding="utf-8", errors="replace"))
                phase_times, operation_counts = _extract_perf_metrics(perf_doc)
                if phase_times:
                    mojo_phase_times = phase_times
                if operation_counts:
                    mojo_operation_counts = operation_counts
            except Exception:
                pass
        else:
            mojo_perf_json_written = ""

    if run_mojo and (mojo_perf_json is not None) and mojo_ok and routes_json.exists():
        if not mojo_perf_json_written:
            raise RuntimeError(
                f"{fixture_name}: --perf-json requested but no perf sidecar was written ({mojo_perf_json})"
            )
        if not mojo_phase_times:
            raise RuntimeError(
                f"{fixture_name}: --perf-json requested but no perf payload was found in {mojo_perf_json_written} or {routes_json}"
            )

    mojo_route_p50_s = _percentile(mojo_route_runs_s, 0.5)
    mojo_route_p90_s = _percentile(mojo_route_runs_s, 0.9)
    mojo_route_min_s = min(mojo_route_runs_s) if mojo_route_runs_s else 0.0
    mojo_route_max_s = max(mojo_route_runs_s) if mojo_route_runs_s else 0.0
    timing = TimingStats(
        kicad_export_dsn_s=t_export,
        freerouting_route_s=t_fr,
        mojo_backend_route_s=t_mojo,
        kicad_drc_freerouting_s=t_fr_drc,
        kicad_drc_mojo_s=t_mojo_drc,
        mojo_route_runs_s=mojo_route_runs_s,
        mojo_route_p50_s=mojo_route_p50_s,
        mojo_route_p90_s=mojo_route_p90_s,
        mojo_route_min_s=mojo_route_min_s,
        mojo_route_max_s=mojo_route_max_s,
        mojo_route_warmup_s=mojo_route_warmup_s,
    )

    kicad_ir_stats = _ir_stats_from_file(kicad_dsn_ir) if kicad_dsn_ir.exists() else IrStats(-1.0, -1.0, -1, -1, -1)
    freerouting_ir_stats = _ir_stats_from_file(fr_dsn_ir) if fr_dsn_ir.exists() else IrStats(-1.0, -1.0, -1, -1, -1)
    delta_ir_wires = -1
    delta_ir_vias = -1
    delta_ir_pins = -1
    if kicad_ir_stats.wires >= 0 and freerouting_ir_stats.wires >= 0:
        delta_ir_wires = kicad_ir_stats.wires - freerouting_ir_stats.wires
    if kicad_ir_stats.vias >= 0 and freerouting_ir_stats.vias >= 0:
        delta_ir_vias = kicad_ir_stats.vias - freerouting_ir_stats.vias
    if kicad_ir_stats.pins >= 0 and freerouting_ir_stats.pins >= 0:
        delta_ir_pins = kicad_ir_stats.pins - freerouting_ir_stats.pins

    return FixtureSummary(
        fixture=fixture_name,
        input_pcb=str(input_pcb),
        kicad_raw_dsn=str(kicad_raw_dsn),
        kicad_dsn=str(kicad_dsn),
        kicad_dsn_dump_json=str(kicad_dsn_dump),
        kicad_dsn_dump_ok=dsn_dump_ok,
        kicad_dsn_dump_error=dsn_dump_err,
        kicad_dsn_ir_json=str(kicad_dsn_ir),
        kicad_dsn_ir_ok=ir_ok,
        kicad_dsn_ir_error=ir_err,
        freerouting_out_pcb=str(freerouting_out),
        mojo_out_pcb=str(mojo_out) if run_mojo else "",
        freerouting_drc=fr_stats,
        mojo_drc=mojo_stats,
        freerouting_drc_routing_only=fr_routing_only_stats,
        mojo_drc_routing_only=mojo_routing_only_stats,
        delta_drc_violations=delta_viol,
        delta_drc_unconnected=delta_unconn,
        delta_drc_violations_routing_only=delta_viol_routing_only,
        delta_drc_unconnected_routing_only=delta_unconn_routing_only,
        mojo_failed_nets=mojo_failed,
        mojo_tracks=mojo_tracks,
        mojo_vias=mojo_vias,
        routes_json=str(routes_json) if run_mojo else "",
        problem_json=str(problem_json) if run_mojo else "",
        freerouting_ok=freerouting_ok if run_freerouting else False,
        freerouting_error=freerouting_error,
        mojo_ok=mojo_ok if run_mojo else False,
        mojo_error=mojo_error,
        freerouting_raw_dsn=str(raw_dsn_out),
        freerouting_dsn=str(dsn_out),
        freerouting_ses=str(ses_out),
        freerouting_log_file=str(fr_runtime_log_out) if fr_runtime_log_out.exists() else "",
        freerouting_stdout_log=str(fr_stdout_log_path) if fr_stdout_log_path is not None else "",
        freerouting_stderr_log=str(fr_stderr_log_path) if fr_stderr_log_path is not None else "",
        freerouting_trace_jsonl=str(fr_trace_jsonl_path) if fr_trace_jsonl_path is not None else "",
        freerouting_trace_ok=bool(fr_trace_ok),
        freerouting_trace_error=str(fr_trace_err),
        freerouting_dsn_dump_json=str(fr_dsn_dump),
        freerouting_dsn_dump_ok=fr_dsn_dump_ok,
        freerouting_dsn_dump_error=fr_dsn_dump_err,
        freerouting_dsn_ir_json=str(fr_dsn_ir),
        freerouting_dsn_ir_ok=fr_dsn_ir_ok,
        freerouting_dsn_ir_error=fr_dsn_ir_err,
        kicad_ir_stats=kicad_ir_stats,
        freerouting_ir_stats=freerouting_ir_stats,
        delta_ir_wires=delta_ir_wires,
        delta_ir_vias=delta_ir_vias,
        delta_ir_pins=delta_ir_pins,
        timing_s=timing,
        mojo_perf_json=mojo_perf_json_written,
        mojo_phase_times=mojo_phase_times,
        mojo_operation_counts=mojo_operation_counts,
        mojo_perf_mode=mojo_mode,
        mojo_violation_types=mojo_types,
        freerouting_violation_types=fr_types,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fixture-name", required=True)
    ap.add_argument("--in", dest="input_pcb", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--kicad-image", default=DEFAULT_IMAGE)
    ap.add_argument("--mojo-cfg", type=Path, default=None, help="Mojo router config JSON (backend-route)")
    ap.add_argument("--mojo-resolution", type=float, default=0.2)
    ap.add_argument(
        "--mojo-inflate",
        type=float,
        default=None,
        help="Override extractor obstacle inflation (mm) for Mojo backend-route (passed to --inflate).",
    )
    ap.add_argument(
        "--mojo-budget-s",
        type=float,
        default=None,
        help="If set, writes an override cfg with max_time_ms derived from this budget and uses it for Mojo routing.",
    )
    ap.add_argument("--mojo-extract-timeout-s", type=float, default=None)
    ap.add_argument("--mojo-route-timeout-s", type=float, default=None)
    ap.add_argument("--mojo-apply-timeout-s", type=float, default=None)
    ap.add_argument(
        "--warm-runs",
        type=int,
        default=1,
        help="Run Mojo backend-route N warm runs (N>1 performs 1 warmup + N measured runs).",
    )
    ap.add_argument(
        "--perf-mode",
        choices=["safe", "fast"],
        default="safe",
        help="Mojo perf mode override written into cfg and exported in summary.",
    )
    ap.add_argument(
        "--perf-json",
        type=Path,
        default=None,
        help="Optional perf JSON path for Mojo route (warm runs produce .warmup/.runN sidecars).",
    )

    # FreeRouting knobs (subset; extend as needed)
    ap.add_argument("--freerouting-max-passes", type=int, default=50)
    ap.add_argument("--freerouting-no-fanout", action="store_true")
    ap.add_argument("--freerouting-strip-planes", action="store_true")
    ap.add_argument("--freerouting-seed", type=int, default=None)
    ap.add_argument(
        "--freerouting-java-image",
        type=str,
        default="eclipse-temurin:21-jre",
        help="Docker image for FreeRouting Java execution.",
    )
    ap.add_argument(
        "--freerouting-enable-logging",
        action="store_true",
        help="Enable FreeRouting logging for this fixture run.",
    )
    ap.add_argument(
        "--freerouting-log-level",
        type=str,
        default=None,
        help="Set FreeRouting log level (OFF/FATAL/ERROR/WARN/INFO/DEBUG/TRACE/ALL or 0-7).",
    )
    ap.add_argument(
        "--freerouting-capture-stdout",
        action="store_true",
        help="Capture FreeRouting docker stdout to <out-dir>/<fixture>.freerouting.stdout.log.",
    )
    ap.add_argument(
        "--freerouting-capture-stderr",
        action="store_true",
        help="Capture FreeRouting docker stderr to <out-dir>/<fixture>.freerouting.stderr.log.",
    )
    ap.add_argument(
        "--freerouting-use-local-jar",
        type=Path,
        default=None,
        help="Use a local FreeRouting jar instead of the plugin zip jar (absolute or workspace-relative).",
    )
    ap.add_argument(
        "--freerouting-trace-jsonl",
        type=str,
        default=None,
        help="Emit FreeRouting decision trace NDJSON. Use 'auto' for <out-dir>/<fixture>.freerouting.trace.jsonl.",
    )
    ap.add_argument(
        "--freerouting-trace-nets",
        type=str,
        default=None,
        help="Optional net filter for decision trace (csv names/#ids or 're:<regex>').",
    )
    ap.add_argument(
        "--freerouting-trace-max-events",
        type=int,
        default=None,
        help="Optional cap on emitted decision trace events.",
    )
    ap.add_argument(
        "--freerouting-job-timeout",
        type=str,
        default=None,
        help="Pass through to FreeRouting `--router.job_timeout=HH:MM:SS` (requires docker Java).",
    )
    ap.add_argument("--skip-freerouting", action="store_true", help="Skip running the FreeRouting oracle (Mojo only).")
    ap.add_argument("--skip-mojo", action="store_true", help="Skip running Mojo backend-route (FreeRouting only).")
    ap.add_argument("--no-cache", action="store_true", help="Disable reuse of existing outputs in out-dir.")
    ap.add_argument("--kicad-drc-timeout-s", type=float, default=300.0)
    ap.add_argument(
        "--mojo-dsn-dump",
        action="store_true",
        help="Also run `pardal-router-mojo dsn-dump` on the exported DSN and write a JSON snapshot.",
    )
    ap.add_argument(
        "--mojo-dsn-ir",
        action="store_true",
        help="Also run `pardal-router-mojo dsn-ir` on the exported DSN and write a minimal IR JSON.",
    )
    ap.add_argument(
        "--normalize-footprint-libs",
        action="store_true",
        help=(
            "Pre-step: materialize referenced footprint libraries into out-dir and "
            "write a local fp-lib-table to reduce lib_footprint_* DRC noise."
        ),
    )
    ap.add_argument(
        "--update-diary",
        action="store_true",
        help="Append a compact entry to PARITY_DIARY.md after this run.",
    )
    ap.add_argument(
        "--diary-path",
        type=Path,
        default=None,
        help="Override diary path (default: <project_root>/PARITY_DIARY.md).",
    )
    ap.add_argument(
        "--diary-label",
        type=str,
        default=None,
        help="Optional short label for the diary entry (e.g. cfg/experiment name).",
    )
    args = ap.parse_args(argv)

    project_root = Path(__file__).resolve().parents[2]
    workspace_root = Path(__file__).resolve().parents[3]
    args.input_pcb = args.input_pcb.resolve()
    args.out_dir = args.out_dir.resolve()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    fr_enable_logging = bool(args.freerouting_enable_logging or args.freerouting_log_level is not None)
    fr_tmpdir_relpath: str | None = None
    if fr_enable_logging:
        fr_tmpdir_host = (args.out_dir / "_freerouting_tmp").resolve()
        try:
            fr_tmpdir_relpath = str(fr_tmpdir_host.relative_to(workspace_root))
        except ValueError:
            fr_tmpdir_relpath = None

    fr_stdout_path = (
        args.out_dir / f"{args.fixture_name}.freerouting.stdout.log"
        if bool(args.freerouting_capture_stdout)
        else None
    )
    fr_stderr_path = (
        args.out_dir / f"{args.fixture_name}.freerouting.stderr.log"
        if bool(args.freerouting_capture_stderr)
        else None
    )

    fr_trace_host_path: Path | None = None
    if args.freerouting_trace_jsonl is not None:
        raw_trace = str(args.freerouting_trace_jsonl).strip()
        if raw_trace and raw_trace.lower() != "off":
            if raw_trace.lower() == "auto":
                fr_trace_host_path = (args.out_dir / f"{args.fixture_name}.freerouting.trace.jsonl").resolve()
            else:
                trace_candidate = Path(raw_trace)
                if not trace_candidate.is_absolute():
                    trace_candidate = (args.out_dir / trace_candidate).resolve()
                fr_trace_host_path = trace_candidate.resolve()

    fr_jvm_props: list[str] = []
    if fr_trace_host_path is not None:
        try:
            fr_trace_rel = str(fr_trace_host_path.relative_to(workspace_root)).replace("\\", "/")
        except ValueError as e:
            raise SystemExit(
                f"--freerouting-trace-jsonl path must be under workspace root ({workspace_root}): {fr_trace_host_path}"
            ) from e
        fr_jvm_props.append(f"-Dfreerouting.trace.path=/work/{fr_trace_rel}")
        if args.freerouting_trace_nets:
            fr_jvm_props.append(f"-Dfreerouting.trace.net_filter={args.freerouting_trace_nets}")
        if args.freerouting_trace_max_events is not None:
            fr_jvm_props.append(f"-Dfreerouting.trace.max_events={int(args.freerouting_trace_max_events)}")

    fr_cfg = FreeroutingRunConfig(
        kicad_docker_image=str(args.kicad_image),
        java_docker_image=str(args.freerouting_java_image),
        max_passes=int(args.freerouting_max_passes),
        fanout=not bool(args.freerouting_no_fanout),
        strip_planes=bool(args.freerouting_strip_planes),
        random_seed=None if args.freerouting_seed is None else int(args.freerouting_seed),
        router_job_timeout=None if args.freerouting_job_timeout is None else str(args.freerouting_job_timeout),
        disable_logging=not bool(fr_enable_logging),
        enable_logging=bool(fr_enable_logging),
        log_level=None if args.freerouting_log_level is None else str(args.freerouting_log_level),
        java_tmpdir_relpath=fr_tmpdir_relpath,
        capture_stdout_path=fr_stdout_path,
        capture_stderr_path=fr_stderr_path,
        jar_override=args.freerouting_use_local_jar,
        jvm_props=tuple(fr_jvm_props),
    )

    mojo_cfg = args.mojo_cfg
    if args.mojo_budget_s is not None and (not bool(args.skip_mojo)):
        # Ensure the router exits cleanly within the requested budget:
        # - keep a small buffer for JSON IO and process startup
        max_time_ms = max(1, int(float(args.mojo_budget_s) * 1000.0) - 500)
        out_cfg = args.out_dir / f"{args.fixture_name}.mojo_budget_cfg.json"
        mojo_cfg = _with_max_time_ms(mojo_cfg, out_path=out_cfg, max_time_ms=max_time_ms)
        # If the user didn't provide an explicit subprocess timeout, set one slightly above budget.
        if args.mojo_route_timeout_s is None:
            args.mojo_route_timeout_s = float(args.mojo_budget_s) + 2.0

    if (not bool(args.skip_mojo)) and str(args.perf_mode).lower() != "safe":
        out_cfg = args.out_dir / f"{args.fixture_name}.mojo_perf_cfg.json"
        mojo_cfg = _with_json_overrides(
            mojo_cfg,
            out_path=out_cfg,
            overrides={
                "perf_mode": str(args.perf_mode).lower(),
                "adaptive_time_budget": True,
            },
        )

    mojo_perf_json = None
    if args.perf_json is not None:
        mojo_perf_json = args.perf_json
        if not mojo_perf_json.is_absolute():
            mojo_perf_json = (args.out_dir / mojo_perf_json).resolve()

    argv_in = list(sys.argv[1:] if argv is None else argv)
    mojo_resolution_mm = float(args.mojo_resolution)
    if not _argv_has_flag(argv_in, "--mojo-resolution"):
        cfg_res = _cfg_resolution_mm(mojo_cfg)
        if cfg_res is not None:
            mojo_resolution_mm = cfg_res

    summary = run_fixture(
        workspace_root=workspace_root,
        project_root=project_root,
        fixture_name=str(args.fixture_name),
        input_pcb=args.input_pcb,
        out_dir=args.out_dir,
        kicad_image=str(args.kicad_image),
        freerouting_cfg=fr_cfg,
        mojo_cfg_json=mojo_cfg,
        mojo_resolution_mm=mojo_resolution_mm,
        mojo_inflate_mm=None if args.mojo_inflate is None else float(args.mojo_inflate),
        run_freerouting=not bool(args.skip_freerouting),
        run_mojo=not bool(args.skip_mojo),
        # Caching can serve stale mojo outputs when cfgs are tuned between runs.
        # For parity verification, disable cache whenever an explicit mojo cfg is used.
        cache=(not bool(args.no_cache))
        and (mojo_cfg is None)
        and int(args.warm_runs) <= 1
        and (mojo_perf_json is None),
        drc_timeout_s=float(args.kicad_drc_timeout_s),
        mojo_dump_dsn=bool(args.mojo_dsn_dump),
        mojo_dump_ir=bool(args.mojo_dsn_ir),
        normalize_footprint_libs=bool(args.normalize_footprint_libs),
        mojo_extract_timeout_s=args.mojo_extract_timeout_s,
        mojo_route_timeout_s=args.mojo_route_timeout_s,
        mojo_apply_timeout_s=args.mojo_apply_timeout_s,
        mojo_warm_runs=max(1, int(args.warm_runs)),
        mojo_perf_json=mojo_perf_json,
        mojo_perf_mode=str(args.perf_mode).lower(),
    )
    out_path = args.out_dir / f"{args.fixture_name}.summary.json"
    out_path.write_text(json.dumps(asdict(summary), indent=2, sort_keys=True), encoding="utf-8")
    if args.update_diary:
        diary_path = args.diary_path.resolve() if args.diary_path else (project_root / "PARITY_DIARY.md")
        try:
            append_parity_diary_entry(
                diary_path=diary_path,
                summaries=[summary],
                source="run_parity_fixture",
                label=args.diary_label or str(args.fixture_name),
                suite_out_dir=args.out_dir,
            )
        except Exception as e:  # noqa: BLE001
            print(f"warning: failed to append diary entry: {type(e).__name__}: {e}", file=sys.stderr)
    print(out_path)
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
