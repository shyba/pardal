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
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pcb_tool.freerouting_backend import FreeroutingRunConfig, freeroute_kicad_pcb, sanitize_dsn
from pcb_tool.kicad_docker import DEFAULT_IMAGE, run_kicad_cli_in_docker


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
    delta_drc_violations: int
    delta_drc_unconnected: int
    mojo_failed_nets: int
    mojo_tracks: int
    mojo_vias: int
    routes_json: str
    problem_json: str
    freerouting_ok: bool
    freerouting_error: str
    freerouting_raw_dsn: str
    freerouting_dsn: str
    freerouting_ses: str
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
    mojo_violation_types: dict[str, int]
    freerouting_violation_types: dict[str, int]


def _require_docker() -> None:
    if shutil.which("docker") is None:
        raise RuntimeError("docker not found in PATH")


def _run(cmd: list[str], *, cwd: Path) -> None:
    subprocess.run(cmd, cwd=str(cwd), check=True)


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


def _backend_route(
    *,
    project_root: Path,
    in_pcb: Path,
    out_pcb: Path,
    cfg_json: Path | None,
    resolution_mm: float,
    docker_image: str,
) -> None:
    cmd = [
        str(project_root / "venv" / "bin" / "python"),
        "-m",
        "pcb_tool.cli",
        "backend-route",
        str(in_pcb),
        "-o",
        str(out_pcb),
        "--docker-image",
        docker_image,
        "--resolution",
        str(float(resolution_mm)),
    ]
    if cfg_json is not None:
        cmd += ["--cfg", str(cfg_json)]
    _run(cmd, cwd=project_root)


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
    run_freerouting: bool,
    run_mojo: bool,
    cache: bool,
    drc_timeout_s: float,
    mojo_dump_dsn: bool,
    mojo_dump_ir: bool,
) -> FixtureSummary:
    _require_docker()
    out_dir.mkdir(parents=True, exist_ok=True)
    repo_root = project_root
    timing = TimingStats(0.0, 0.0, 0.0, 0.0, 0.0)

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
    if mojo_dump_dsn:
        try:
            _mojo_dsn_dump(repo_root=repo_root, in_dsn=kicad_dsn, out_json=kicad_dsn_dump, cache=cache)
            dsn_dump_ok = True
        except Exception as e:  # noqa: BLE001
            dsn_dump_ok = False
            dsn_dump_err = f"{type(e).__name__}: {e}"
    if mojo_dump_ir:
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
    if run_mojo and (not (cache and mojo_out.exists() and mojo_out.stat().st_size > 0)):
        # Ensure artifacts are refreshed together.
        routes_json.unlink(missing_ok=True)
        problem_json.unlink(missing_ok=True)
        t0 = time.perf_counter()
        _backend_route(
            project_root=project_root,
            in_pcb=input_pcb,
            out_pcb=mojo_out,
            cfg_json=mojo_cfg_json,
            resolution_mm=mojo_resolution_mm,
            docker_image=kicad_image,
        )
        t_mojo = time.perf_counter() - t0
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

    delta_viol = -1
    delta_unconn = -1
    if run_freerouting and run_mojo and freerouting_ok and fr_stats.violations >= 0 and fr_stats.unconnected >= 0:
        delta_viol = mojo_stats.violations - fr_stats.violations
        delta_unconn = mojo_stats.unconnected - fr_stats.unconnected

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
        except Exception:
            pass

    timing = TimingStats(
        kicad_export_dsn_s=t_export,
        freerouting_route_s=t_fr,
        mojo_backend_route_s=t_mojo,
        kicad_drc_freerouting_s=t_fr_drc,
        kicad_drc_mojo_s=t_mojo_drc,
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
        delta_drc_violations=delta_viol,
        delta_drc_unconnected=delta_unconn,
        mojo_failed_nets=mojo_failed,
        mojo_tracks=mojo_tracks,
        mojo_vias=mojo_vias,
        routes_json=str(routes_json) if run_mojo else "",
        problem_json=str(problem_json) if run_mojo else "",
        freerouting_ok=freerouting_ok if run_freerouting else False,
        freerouting_error=freerouting_error,
        freerouting_raw_dsn=str(raw_dsn_out),
        freerouting_dsn=str(dsn_out),
        freerouting_ses=str(ses_out),
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

    # FreeRouting knobs (subset; extend as needed)
    ap.add_argument("--freerouting-max-passes", type=int, default=50)
    ap.add_argument("--freerouting-no-fanout", action="store_true")
    ap.add_argument("--freerouting-strip-planes", action="store_true")
    ap.add_argument("--freerouting-seed", type=int, default=None)
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
    args = ap.parse_args(argv)

    project_root = Path(__file__).resolve().parents[2]
    workspace_root = Path(__file__).resolve().parents[3]

    fr_cfg = FreeroutingRunConfig(
        kicad_docker_image=str(args.kicad_image),
        max_passes=int(args.freerouting_max_passes),
        fanout=not bool(args.freerouting_no_fanout),
        strip_planes=bool(args.freerouting_strip_planes),
        random_seed=None if args.freerouting_seed is None else int(args.freerouting_seed),
        router_job_timeout=None if args.freerouting_job_timeout is None else str(args.freerouting_job_timeout),
    )

    summary = run_fixture(
        workspace_root=workspace_root,
        project_root=project_root,
        fixture_name=str(args.fixture_name),
        input_pcb=args.input_pcb,
        out_dir=args.out_dir,
        kicad_image=str(args.kicad_image),
        freerouting_cfg=fr_cfg,
        mojo_cfg_json=args.mojo_cfg,
        mojo_resolution_mm=float(args.mojo_resolution),
        run_freerouting=not bool(args.skip_freerouting),
        run_mojo=not bool(args.skip_mojo),
        cache=not bool(args.no_cache),
        drc_timeout_s=float(args.kicad_drc_timeout_s),
        mojo_dump_dsn=bool(args.mojo_dsn_dump),
        mojo_dump_ir=bool(args.mojo_dsn_ir),
    )
    out_path = args.out_dir / f"{args.fixture_name}.summary.json"
    out_path.write_text(json.dumps(asdict(summary), indent=2, sort_keys=True), encoding="utf-8")
    print(out_path)
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
