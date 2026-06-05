"""Pure tooling for staging the fpga_large routing DSL lane."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import backend_adapter as backend_adapter_module
from . import diagnostics as diagnostics_module
from . import route_plan as route_plan_module
from .board_ir_producer import produce_board_ir
from .candidate_schema import route_candidates_to_json_payload
from .mojo_bridge import build_mojo_problem_payload
from .source import load_routes_source
from .board_ir import load_board_ir
from .capability_gate import load_backend_manifest


FPGA_LARGE_SCHEMA = "pardal.routing_dsl_fpga_large"
FPGA_LARGE_VERSION = "0.2"
DEFAULT_BOARD_FIXTURE = Path("examples/fpga_large/fpga_large_rust_strict_fast_0p2.kicad_pcb")
DEFAULT_BACKEND_CFG = Path("examples/fpga_large/mojo_cfg_ncr_fast_keepouts_nooverlap.json")
DEFAULT_FIXTURE_LIST = Path("tests/fixtures/parity_fixtures/fpga_large_only.json")
DEFAULT_ROUTES_SOURCE = Path("tests/fixtures/routing_dsl/route-plan-source.pdl.yaml")


@dataclass(frozen=True)
class FpgaLargeToolingResult:
    work_dir: Path
    manifest_path: Path
    manifest: dict[str, Any]


@dataclass(frozen=True)
class FpgaLargeFinishReadinessResult:
    work_dir: Path
    manifest_path: Path
    manifest: dict[str, Any]
    status: str


def build_fpga_large_tooling_pack(
    *,
    repo_root: str | Path,
    work_dir: str | Path,
    board_fixture: str | Path | None = None,
    backend_cfg: str | Path | None = None,
    commands: Sequence[Mapping[str, Any]] = (),
) -> FpgaLargeToolingResult:
    result = build_fpga_large_finish_readiness_pack(
        repo_root=repo_root,
        work_dir=work_dir,
        board_fixture=board_fixture,
        backend_cfg=backend_cfg,
        commands=commands,
        dry_run=True,
        one_pass=False,
    )
    legacy_manifest = dict(result.manifest)
    legacy_next_worklist = dict(legacy_manifest.get("next_worklist") or {})
    legacy_next_worklist["entries"] = [
        {
            "kind": "derived-route-source",
            "source": str(legacy_manifest.get("inputs", {}).get("board_fixture") or ""),
            "backend_cfg": str(legacy_manifest.get("inputs", {}).get("backend_cfg") or ""),
            "route_group_ids": [],
            "status": "pending",
        }
    ]
    legacy_manifest["next_worklist"] = legacy_next_worklist
    _write_json(result.work_dir / "next-worklist.json", legacy_next_worklist)
    artifacts = dict(legacy_manifest.get("artifacts") or {})
    artifacts["board_fixture"] = _entry(result.work_dir / "board.ir.json")
    artifacts["backend_cfg"] = _entry(result.work_dir / "backend-manifest.json")
    artifacts["next_worklist"] = _entry(result.work_dir / "next-worklist.json")
    artifacts["manifest"] = _entry(result.manifest_path)
    legacy_manifest["artifacts"] = artifacts
    legacy_manifest["manifest_hash"] = _sha256_manifest(legacy_manifest)
    _write_json(result.manifest_path, legacy_manifest)
    result = FpgaLargeFinishReadinessResult(result.work_dir, result.manifest_path, legacy_manifest, result.status)
    return FpgaLargeToolingResult(result.work_dir, result.manifest_path, result.manifest)


def build_fpga_large_finish_readiness_pack(
    *,
    repo_root: str | Path,
    work_dir: str | Path,
    board_fixture: str | Path | None = None,
    backend_cfg: str | Path | None = None,
    routes_source: str | Path | None = None,
    net_list: Sequence[str] = (),
    from_drc: str | Path | Mapping[str, Any] | None = None,
    manifest_path: str | Path | None = None,
    commands: Sequence[Mapping[str, Any]] = (),
    dry_run: bool = True,
    one_pass: bool = False,
    resume: bool = False,
    max_route_groups: int | None = None,
    budget_s: float | None = None,
    candidate_cap: int | None = None,
) -> FpgaLargeFinishReadinessResult:
    root = Path(repo_root)
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    if resume and manifest_path is not None:
        base_manifest = load_json(manifest_path)
        board_fixture_path = Path(base_manifest["inputs"]["board_fixture"])
        backend_cfg_path = Path(base_manifest["inputs"]["backend_cfg"])
        routes_source_path = Path(base_manifest["inputs"]["routes_source"])
        max_route_groups = max_route_groups if max_route_groups is not None else int(base_manifest["config"].get("max_route_groups") or 0) or None
        budget_s = budget_s if budget_s is not None else base_manifest["config"].get("budget_s")
        candidate_cap = candidate_cap if candidate_cap is not None else base_manifest["config"].get("candidate_cap")
    else:
        board_fixture_path = root / (board_fixture or DEFAULT_BOARD_FIXTURE)
        backend_cfg_path = root / (backend_cfg or DEFAULT_BACKEND_CFG)
        routes_source_path = root / (routes_source or DEFAULT_ROUTES_SOURCE)
        base_manifest = None

    board_ir_path = work / "board.ir.json"
    route_plan_path = work / "route-plan.ir.json"
    backend_manifest_path = work / "backend-manifest.json"
    route_candidates_path = work / "route-candidates.json"
    routes_compat_path = work / "routes.json"
    route_diagnostics_path = work / "route-diagnostics.json"
    apply_report_path = work / "apply-report.json"
    drc_path = work / "drc.json"
    next_worklist_path = work / "next-worklist.json"
    summary_path = work / "summary.md"
    report_path = work / "report.json"
    manifest_out_path = work / "manifest.json"
    routes_pdl_path = work / "routes.pdl.yaml"
    problem_path = work / "problem.json"
    route_plan_ir_placeholder_path = work / "route-plan.ir.json"

    _write_board_ir(board_ir_path, board_fixture_path, root=root, dry_run=dry_run)
    _write_routes_source(routes_pdl_path, routes_source_path, root=root)
    _write_backend_manifest(backend_manifest_path, backend_cfg_path)

    board_ir = load_board_ir(board_ir_path)
    routes_source = load_routes_source(routes_pdl_path)
    route_plan = route_plan_module.resolve_route_plan(routes_source, board_ir)
    if candidate_cap is not None:
        route_plan["defaults"]["search"]["max_candidates"] = candidate_cap
    if max_route_groups is not None:
        route_plan["route_groups"] = list(route_plan.get("route_groups") or [])[:max_route_groups]
    _write_json(route_plan_path, route_plan)
    if route_plan_ir_placeholder_path != route_plan_path:
        _write_json(route_plan_ir_placeholder_path, route_plan)

    problem_payload = _problem_payload(board_fixture_path, backend_cfg_path, routes_source_path, route_plan, net_list=net_list, from_drc=from_drc)
    _write_json(problem_path, problem_payload)

    manifest = load_backend_manifest(backend_manifest_path)
    staged_candidates = _stage_candidates(route_plan, manifest, dry_run=dry_run)
    _write_json(route_candidates_path, staged_candidates["payload"])
    _write_json(routes_compat_path, _routes_compat_payload(route_plan, staged_candidates["payload"]))

    route_diagnostics = _route_diagnostics_payload(route_plan, manifest, from_drc=from_drc, net_list=net_list)
    _write_json(route_diagnostics_path, route_diagnostics)
    apply_report = _apply_report_payload(route_plan, staged_candidates["payload"], route_diagnostics, dry_run=dry_run, one_pass=one_pass)
    _write_json(apply_report_path, apply_report)
    drc_payload = _drc_payload(from_drc, staged_candidates["payload"], apply_report)
    _write_json(drc_path, drc_payload)
    next_worklist = _next_worklist_payload(
        route_plan=route_plan,
        route_diagnostics=route_diagnostics,
        drc_payload=drc_payload,
        net_list=net_list,
        from_drc=from_drc,
        max_route_groups=max_route_groups,
        budget_s=budget_s,
        candidate_cap=candidate_cap,
        resume=resume,
        base_manifest=base_manifest,
    )
    _write_json(next_worklist_path, next_worklist)
    summary = _summary_payload(
        route_plan=route_plan,
        apply_report=apply_report,
        route_diagnostics=route_diagnostics,
        drc_payload=drc_payload,
        next_worklist=next_worklist,
        dry_run=dry_run,
        one_pass=one_pass,
    )
    summary_path.write_text(summary["summary_md"], encoding="utf-8")
    _write_json(report_path, summary)

    commands_payload = [dict(command) for command in commands] or _default_command_refs(root, work, board_fixture_path, backend_cfg_path, routes_source_path)
    manifest_payload = {
        "schema": FPGA_LARGE_SCHEMA,
        "version": FPGA_LARGE_VERSION,
        "repo_root": str(root),
        "work_dir": str(work),
        "mode": {
            "dry_run": dry_run,
            "one_pass": one_pass,
            "resume": resume,
            "net_list": list(net_list),
            "from_drc": str(from_drc) if isinstance(from_drc, (str, Path)) else "",
        },
        "inputs": {
            "board_fixture": str(board_fixture_path),
            "backend_cfg": str(backend_cfg_path),
            "routes_source": str(routes_source_path),
        },
        "config": {
            "max_route_groups": max_route_groups,
            "budget_s": budget_s,
            "candidate_cap": candidate_cap,
        },
        "authority": {
            "generated_board_authority": False,
            "routing_authority": False,
            "release_authority": False,
            "jlc_upload_authority": False,
            "orderable_claim": False,
        },
        "commands": commands_payload,
        "next_worklist": next_worklist,
        "artifacts": {
            "manifest": _entry(manifest_out_path),
            "board_ir": _entry(board_ir_path),
            "routes_pdl": _entry(routes_pdl_path),
            "route_plan_ir": _entry(route_plan_path),
            "backend_manifest": _entry(backend_manifest_path),
            "route_candidates": _entry(route_candidates_path),
            "routes": _entry(routes_compat_path),
            "source_route_problem": _entry(problem_path),
            "derived_routes": _entry(routes_compat_path),
            "route_diagnostics": _entry(route_diagnostics_path),
            "apply_report": _entry(apply_report_path),
            "drc": _entry(drc_path),
            "next_worklist": _entry(next_worklist_path),
            "summary": _entry(summary_path),
            "report": _entry(report_path),
            "problem": _entry(problem_path),
        },
        "status": summary["status"],
        "counts": summary["counts"],
    }
    manifest_payload["manifest_hash"] = _sha256_manifest(manifest_payload)
    _write_json(manifest_out_path, manifest_payload)
    return FpgaLargeFinishReadinessResult(work, manifest_out_path, manifest_payload, summary["status"])


def _stage_candidates(route_plan: Mapping[str, Any], manifest: Mapping[str, Any], *, dry_run: bool) -> dict[str, Any]:
    del dry_run
    result = backend_adapter_module.adapt_backend_route_output(route_plan, manifest)
    if result.kind == "route-candidates":
        return {"kind": result.kind, "payload": result.payload}
    return {"kind": result.kind, "payload": result.payload}


def _route_diagnostics_payload(
    route_plan: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    from_drc: str | Path | Mapping[str, Any] | None,
    net_list: Sequence[str],
) -> dict[str, Any]:
    if from_drc is not None:
        drc_payload = load_json(from_drc)
        return _diagnostics_from_drc(route_plan, manifest, drc_payload, net_list=net_list)
    return diagnostics_module.normalize_route_diagnostics(
        {
            "run_id": f"{route_plan.get('route_plan_id', '')}:dry-run",
            "route_plan_id": str(route_plan.get("route_plan_id") or ""),
            "route_plan_hash": str(route_plan.get("route_plan_hash") or ""),
            "failures": [],
        }
    )


def _diagnostics_from_drc(
    route_plan: Mapping[str, Any],
    manifest: Mapping[str, Any],
    drc_payload: Mapping[str, Any],
    *,
    net_list: Sequence[str],
) -> dict[str, Any]:
    failures = []
    for index, item in enumerate(list(drc_payload.get("unconnected_items") or [])):
        nets = _extract_nets_from_drc_item(item)
        route_group_id = _match_route_group_id(route_plan, nets, net_list, index)
        failures.append(
            {
                "run_id": f"{route_plan.get('route_plan_id', '')}:drc",
                "route_plan_id": str(route_plan.get("route_plan_id") or ""),
                "route_plan_hash": str(route_plan.get("route_plan_hash") or ""),
                "route_group_id": route_group_id,
                "source_route_group_name": route_group_id,
                "candidate_id": "",
                "candidate_index": None,
                "assignment": {},
                "strategy": {
                    "kind": "from-drc",
                    "profile_id": str((manifest.get("backend") or {}).get("id") or ""),
                },
                "backend_profile_id": str((manifest.get("backend") or {}).get("id") or ""),
                "failed_stage": "drc",
                "code": "unconnected_items" if item.get("type") == "unconnected_items" else "drc_violation",
                "message": str(item.get("description") or "DRC evidence"),
                "net": nets[0] if nets else "",
                "source_span": {},
                "provenance": {"drc_item": item},
                "generated_board_authority": False,
                "routing_authority": False,
                "release_authority": False,
                "jlc_upload_authority": False,
                "orderable_claim": False,
            }
        )
    return diagnostics_module.normalize_route_diagnostics(
        {
            "run_id": f"{route_plan.get('route_plan_id', '')}:drc",
            "route_plan_id": str(route_plan.get("route_plan_id") or ""),
            "route_plan_hash": str(route_plan.get("route_plan_hash") or ""),
            "failures": failures,
        }
    )


def _next_worklist_payload(
    *,
    route_plan: Mapping[str, Any],
    route_diagnostics: Mapping[str, Any],
    drc_payload: Mapping[str, Any],
    net_list: Sequence[str],
    from_drc: str | Path | Mapping[str, Any] | None,
    max_route_groups: int | None,
    budget_s: float | None,
    candidate_cap: int | None,
    resume: bool,
    base_manifest: Mapping[str, Any] | None,
) -> dict[str, Any]:
    route_groups = list(route_plan.get("route_groups") or [])
    items = []
    if net_list:
        for index, net in enumerate(net_list[: max_route_groups or len(net_list)]):
            items.append(_worklist_item("explicit-net", str(net), index, route_plan))
    elif from_drc is not None:
        for row_index, row in enumerate(route_diagnostics.get("rows") or []):
            items.append(_worklist_item("drc-linked", str(row.get("net") or row.get("route_group_id") or f"drc-{row_index}"), row_index, route_plan))
    else:
        for index, group in enumerate(route_groups[: max_route_groups or len(route_groups)]):
            items.append(_worklist_item("route-group", str(group.get("route_group_id") or ""), index, route_plan))
    status = "continue"
    if not items and _success_from_drc(drc_payload):
        status = "success"
    if resume and base_manifest is not None:
        status = str(base_manifest.get("status") or status)
    return {
        "schema": "pardal.routing_dsl_fpga_large_next_worklist",
        "version": "0.1",
        "status": status,
        "budget_s": budget_s,
        "candidate_cap": candidate_cap,
        "entries": items,
        "counts": {"entry_count": len(items), "route_group_count": len(route_groups)},
    }


def _worklist_item(kind: str, label: str, index: int, route_plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "kind": kind,
        "route_group_id": str(label or f"rg-{index}"),
        "source_route_group_name": str(label or ""),
        "net": label,
        "status": "pending",
    }


def _summary_payload(
    *,
    route_plan: Mapping[str, Any],
    apply_report: Mapping[str, Any],
    route_diagnostics: Mapping[str, Any],
    drc_payload: Mapping[str, Any],
    next_worklist: Mapping[str, Any],
    dry_run: bool,
    one_pass: bool,
) -> dict[str, Any]:
    success = _success_from_drc(drc_payload) and not route_diagnostics.get("rows") and not dry_run
    status = "success" if success else "continue"
    if any(row.get("code") == "unsupported_geometry" for row in route_diagnostics.get("rows") or []):
        status = "blocked"
    lines = [
        f"# fpga_large finish readiness",
        f"- status: {status}",
        f"- dry_run: {dry_run}",
        f"- one_pass: {one_pass}",
        f"- route_plan_id: {route_plan.get('route_plan_id', '')}",
        f"- route_plan_hash: {route_plan.get('route_plan_hash', '')}",
        f"- unconnected: {len(drc_payload.get('unconnected_items') or [])}",
        f"- next_worklist_entries: {len(next_worklist.get('entries') or [])}",
    ]
    return {
        "status": status,
        "summary_md": "\n".join(lines) + "\n",
        "counts": {
            "route_groups": len(list(route_plan.get("route_groups") or [])),
            "unconnected": len(drc_payload.get("unconnected_items") or []),
            "next_worklist": len(next_worklist.get("entries") or []),
            "authority_false_flags": 5,
        },
        "apply_report": dict(apply_report),
    }


def _apply_report_payload(
    route_plan: Mapping[str, Any],
    candidates: Mapping[str, Any],
    route_diagnostics: Mapping[str, Any],
    *,
    dry_run: bool,
    one_pass: bool,
) -> dict[str, Any]:
    return {
        "schema": "pardal.route_apply_report",
        "version": "0.1",
        "route_plan_id": str(route_plan.get("route_plan_id") or ""),
        "route_plan_hash": str(route_plan.get("route_plan_hash") or ""),
        "dry_run": dry_run,
        "one_pass": one_pass,
        "accepted": False if route_diagnostics.get("rows") else True,
        "candidate_id": str((candidates.get("candidates") or [{}])[0].get("candidate_id") or ""),
        "authority": {
            "generated_board_authority": False,
            "routing_authority": False,
            "release_authority": False,
            "jlc_upload_authority": False,
            "orderable_claim": False,
        },
    }


def _drc_payload(
    from_drc: str | Path | Mapping[str, Any] | None,
    candidates: Mapping[str, Any],
    apply_report: Mapping[str, Any],
) -> dict[str, Any]:
    if from_drc is None:
        return {
            "$schema": "https://schemas.kicad.org/drc.v1.json",
            "coordinate_units": "mm",
            "source": "dry-run",
            "unconnected_items": [],
            "violations": [],
            "routes_candidate_count": len(candidates.get("candidates") or []),
            "accepted": apply_report.get("accepted", False),
        }
    return load_json(from_drc)


def _problem_payload(
    board_fixture_path: Path,
    backend_cfg_path: Path,
    routes_source_path: Path,
    route_plan: Mapping[str, Any],
    *,
    net_list: Sequence[str],
    from_drc: str | Path | Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema": "pardal.routing_dsl_fpga_large_problem",
        "version": "0.1",
        "source": str(board_fixture_path),
        "backend_cfg": str(backend_cfg_path),
        "routes_source": str(routes_source_path),
        "route_plan_id": str(route_plan.get("route_plan_id") or ""),
        "net_list": list(net_list),
        "from_drc": str(from_drc) if isinstance(from_drc, (str, Path)) else bool(from_drc),
        "status": "dry-run",
    }


def _routes_compat_payload(route_plan: Mapping[str, Any], candidates: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": "pardal.routing_dsl_fpga_large_routes",
        "version": "0.1",
        "route_plan_id": str(route_plan.get("route_plan_id") or ""),
        "route_plan_hash": str(route_plan.get("route_plan_hash") or ""),
        "routes": list(candidates.get("candidates") or []),
    }


def _match_route_group_id(route_plan: Mapping[str, Any], nets: Sequence[str], net_list: Sequence[str], index: int) -> str:
    route_groups = list(route_plan.get("route_groups") or [])
    if net_list:
        return f"net:{net_list[min(index, len(net_list) - 1)]}"
    if nets:
        return f"net:{nets[0]}"
    if route_groups:
        return str(route_groups[min(index, len(route_groups) - 1)].get("route_group_id") or "")
    return f"rg-{index}"


def _extract_nets_from_drc_item(item: Mapping[str, Any]) -> list[str]:
    nets = []
    for sub_item in list(item.get("items") or []):
        description = str(sub_item.get("description") or "")
        if "[" in description and "]" in description:
            nets.append(description.split("[", 1)[1].split("]", 1)[0])
    return nets


def _success_from_drc(drc_payload: Mapping[str, Any]) -> bool:
    return not list(drc_payload.get("unconnected_items") or []) and not list(drc_payload.get("violations") or [])


def _write_board_ir(board_ir_path: Path, board_fixture_path: Path, *, root: Path, dry_run: bool) -> None:
    if board_fixture_path.suffix == ".json" and board_fixture_path.exists():
        payload = load_json(board_fixture_path)
        if isinstance(payload, Mapping) and payload.get("schema") == "pardal.board_ir":
            _write_json(board_ir_path, payload)
            return
    if dry_run:
        fallback = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "routing_dsl" / "board.ir.json"
        if not fallback.exists():
            fallback = root / "tests" / "fixtures" / "routing_dsl" / "board.ir.json"
        if fallback.exists():
            _write_json(board_ir_path, load_json(fallback))
            return
        placeholder = {
            "schema": "pardal.board_ir",
            "version": "0.1",
            "board_ir_id": "fpga_large-placeholder",
            "frozen_board_snapshot_id": "fpga_large-placeholder-snapshot",
            "units": {"length": "mm", "angle": "deg"},
            "outline": [],
            "bounds": {"min_x": 0.0, "min_y": 0.0, "max_x": 0.0, "max_y": 0.0},
            "stackup": [],
            "nets": [],
            "components": [],
            "pads": [],
            "obstacles": [],
            "envelopes": [],
            "provenance": {"mode": "dry-run"},
            "route_plan_anchor_ids": [],
        }
        _write_json(board_ir_path, placeholder)
        return
    _write_json(board_ir_path, produce_board_ir(board_fixture_path).payload)


def _write_routes_source(routes_pdl_path: Path, routes_source_path: Path, *, root: Path) -> None:
    if routes_source_path.exists():
        routes_pdl_path.write_text(routes_source_path.read_text(encoding="utf-8"), encoding="utf-8")
        return
    fallback = Path(__file__).resolve().parents[2] / DEFAULT_ROUTES_SOURCE
    if not fallback.exists():
        fallback = root / DEFAULT_ROUTES_SOURCE
    routes_pdl_path.write_text(fallback.read_text(encoding="utf-8"), encoding="utf-8")


def _write_backend_manifest(backend_manifest_path: Path, backend_cfg_path: Path) -> None:
    payload = {
        "schema": "pardal.backend_manifest",
        "version": "0.1",
        "backend": {"id": "mojo", "version": "0.1"},
        "config_path": str(backend_cfg_path),
    }
    _write_json(backend_manifest_path, payload)


def _default_command_refs(
    repo_root: Path,
    work: Path,
    board_fixture: Path,
    backend_cfg: Path,
    routes_source: Path,
) -> list[dict[str, Any]]:
    return [
        {"name": "prepare", "command": ["python3", "pardal/tools/routing_dsl_fpga_large.py", "prepare"], "cwd": str(repo_root)},
        {"name": "pass", "command": ["pardal", "route-dsl", "fpga-large", "pass"], "cwd": str(work)},
        {"name": "next-worklist", "command": ["pardal", "route-dsl", "fpga-large", "next-worklist"], "cwd": str(work)},
        {"name": "report", "command": ["pardal", "route-dsl", "fpga-large", "report"], "cwd": str(work)},
        {"name": "resume", "command": ["pardal", "route-dsl", "fpga-large", "resume"], "cwd": str(work)},
        {"name": "extract", "command": ["python3", "pardal/tools/extract_routing_problem_pcbnew.py", "--pcb", str(board_fixture)]},
        {"name": "route", "command": ["python3", "pardal/tools/iterative_backend_route_fpga_large.py", "--config", str(backend_cfg)]},
        {"name": "apply", "command": ["python3", "pardal/tools/apply_routes_pcbnew.py"]},
        {"name": "drc", "command": ["kicad-cli", "pcb", "drc", "<output-board>"]},
        {"name": "diagnostics", "command": ["pardal", "route-dsl", "diagnostics", "<input>"]},
        {"name": "routes-source", "command": ["cat", str(routes_source)]},
    ]


def _entry(path: str | Path) -> dict[str, str]:
    p = Path(path)
    return {"path": str(p), "sha256": _sha256_file(p) if p.exists() else ""}


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _sha256_manifest(payload: Mapping[str, Any]) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def load_json(source: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(source, Mapping):
        return dict(source)
    return json.loads(Path(source).read_text(encoding="utf-8"))
