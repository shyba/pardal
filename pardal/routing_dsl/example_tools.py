"""Pure tooling for the checked-in routing DSL example lane."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import backend_adapter as backend_adapter_module
from . import apply_candidate as apply_candidate_module
from . import commit_gate as commit_gate_module
from . import diagnostics as diagnostics_module
from . import route_plan as route_plan_module
from . import source as source_module
from .board_ir_producer import produce_board_ir
from .mojo_bridge import MOJO_BACKEND_ID, MOJO_BACKEND_VERSION
from .mojo_bridge import build_mojo_problem_payload
from .mojo_bridge import convert_mojo_routes_to_route_candidates
from .candidate_schema import load_route_candidates
from .board_ir import load_board_ir
from .capability_gate import load_backend_manifest

EXAMPLE_SCHEMA = "pardal.routing_dsl_example"
EXAMPLE_VERSION = "0.1"
EXAMPLE_BOARD_SOURCE_FILENAME = "board_source.json"
EXAMPLE_ROUTES_SOURCE_FILENAME = "routes.pdl.yaml"
EXAMPLE_BACKEND_MANIFEST_FILENAME = "backend_manifest.json"
EXAMPLE_BOARD_IR_FILENAME = "board.ir.json"
EXAMPLE_ROUTE_PLAN_FILENAME = "route-plan.ir.json"
EXAMPLE_CANDIDATES_FILENAME = "route-candidates.json"
EXAMPLE_APPLY_REPORT_FILENAME = "apply-report.json"
EXAMPLE_DIAGNOSTICS_FILENAME = "route-diagnostics.json"
EXAMPLE_CHECK_REPORT_FILENAME = "check-report.json"


@dataclass(frozen=True)
class ExampleToolingResult:
    example_dir: Path
    board_source_path: Path
    routes_source_path: Path
    board_ir_path: Path
    route_plan_path: Path
    artifact_manifest_path: Path
    artifact_manifest: dict[str, Any]
    backend_manifest_path: Path
    candidates_path: Path
    apply_report_path: Path
    diagnostics_path: Path
    check_report_path: Path


def ensure_example_directory(example_dir: str | Path) -> Path:
    root = Path(example_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "artifacts").mkdir(parents=True, exist_ok=True)
    return root


def write_example_board_source(example_dir: str | Path, payload: Mapping[str, Any]) -> Path:
    root = ensure_example_directory(example_dir)
    path = root / "board_source.json"
    _write_json(path, payload)
    return path


def write_example_routes_source(example_dir: str | Path, payload: str | Mapping[str, Any]) -> Path:
    root = ensure_example_directory(example_dir)
    path = root / "routes.pdl.yaml"
    if isinstance(payload, str):
        path.write_text(payload.rstrip() + "\n", encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    return path


def ensure_example_seed_files(example_dir: str | Path) -> dict[str, Path]:
    root = ensure_example_directory(example_dir)
    board_source_path = root / EXAMPLE_BOARD_SOURCE_FILENAME
    if not board_source_path.exists():
        _write_json(board_source_path, default_example_board_source())
    routes_source_path = root / EXAMPLE_ROUTES_SOURCE_FILENAME
    if not routes_source_path.exists():
        routes_source_path.write_text(default_example_routes_source(), encoding="utf-8")
    backend_manifest_path = root / EXAMPLE_BACKEND_MANIFEST_FILENAME
    if not backend_manifest_path.exists():
        _write_json(backend_manifest_path, default_example_backend_manifest())
    return {
        "board_source": board_source_path,
        "routes_source": routes_source_path,
        "backend_manifest": backend_manifest_path,
    }


def example_command_sequence(board_source_path: str | Path, routes_source_path: str | Path) -> list[dict[str, Any]]:
    board_source_path = Path(board_source_path)
    routes_source_path = Path(routes_source_path)
    return [
        {"name": "board-ir", "command": ["pardal", "route-dsl", "board-ir", str(board_source_path)]},
        {"name": "plan", "command": ["pardal", "route-dsl", "plan", str(routes_source_path)]},
        {"name": "candidates", "command": ["pardal", "route-dsl", "candidates", str(routes_source_path)]},
        {"name": "apply", "command": ["pardal", "route-dsl", "apply", str(routes_source_path)]},
        {"name": "diagnostics", "command": ["pardal", "route-dsl", "diagnostics", str(routes_source_path)]},
        {"name": "check", "command": ["pardal", "route-dsl", "check", "board-ir", str(board_source_path)]},
    ]


def init_example_directory(example_dir: str | Path) -> dict[str, Path]:
    return ensure_example_seed_files(example_dir)


def build_example_artifact_manifest(
    *,
    example_dir: str | Path,
    board_source_path: str | Path,
    routes_source_path: str | Path,
    board_ir_path: str | Path,
    route_plan_path: str | Path,
    commands: Sequence[Mapping[str, Any]] = (),
    interpreter_lane: str = "pure-python",
    counts: Mapping[str, int] | None = None,
    extra_artifacts: Mapping[str, str | Path] | None = None,
) -> dict[str, Any]:
    root = Path(example_dir)
    artifacts = {
        "board_source": _artifact_entry(board_source_path),
        "routes_source": _artifact_entry(routes_source_path),
        "board_ir": _artifact_entry(board_ir_path),
        "route_plan": _artifact_entry(route_plan_path),
    }
    if extra_artifacts:
        for key, value in extra_artifacts.items():
            artifacts[str(key)] = _artifact_entry(value)

    manifest = {
        "schema": EXAMPLE_SCHEMA,
        "version": EXAMPLE_VERSION,
        "example_dir": str(root),
        "interpreter_lane": interpreter_lane,
        "authority": {
            "generated_board_authority": False,
            "routing_authority": False,
            "release_authority": False,
            "jlc_upload_authority": False,
            "orderable_claim": False,
        },
        "counts": dict(counts or {}),
        "commands": [dict(command) for command in commands],
        "artifacts": artifacts,
    }
    manifest["manifest_hash"] = _sha256_manifest(manifest)
    return manifest


def write_example_artifact_manifest(example_dir: str | Path, manifest: Mapping[str, Any]) -> Path:
    root = ensure_example_directory(example_dir)
    path = root / "artifacts" / "manifest.json"
    _write_json(path, manifest)
    return path


def assemble_example_workflow(
    *,
    example_dir: str | Path,
    board_source_payload: Mapping[str, Any],
    routes_source_payload: str | Mapping[str, Any],
    route_plan_payload: Mapping[str, Any],
    board_ir_payload: Mapping[str, Any],
    commands: Sequence[Mapping[str, Any]] = (),
) -> ExampleToolingResult:
    root = ensure_example_directory(example_dir)
    board_source_path = write_example_board_source(root, board_source_payload)
    routes_source_path = write_example_routes_source(root, routes_source_payload)
    backend_manifest_path = root / EXAMPLE_BACKEND_MANIFEST_FILENAME
    if not backend_manifest_path.exists():
        _write_json(backend_manifest_path, default_example_backend_manifest())
    board_ir_path = root / EXAMPLE_BOARD_IR_FILENAME
    _write_json(board_ir_path, _json_payload(board_ir_payload))
    board_ir = load_board_ir(board_ir_path)
    route_plan = route_plan_module.load_route_plan(routes_source_path, board_ir)
    route_plan_path = root / EXAMPLE_ROUTE_PLAN_FILENAME
    _write_json(route_plan_path, route_plan)
    backend_manifest = load_backend_manifest(backend_manifest_path)
    staged = backend_adapter_module.adapt_backend_route_output(route_plan, backend_manifest)
    candidates_path = root / EXAMPLE_CANDIDATES_FILENAME
    _write_json(candidates_path, staged.payload)
    apply_report_path = root / EXAMPLE_APPLY_REPORT_FILENAME
    apply_candidate_module.apply_candidate_report(
        board_ir,
        route_plan,
        candidates_path,
        apply_report_path,
        selected_candidate_id=staged.payload["candidates"][0]["candidate_id"] if staged.payload.get("candidates") else None,
    )
    diagnostics_path = root / EXAMPLE_DIAGNOSTICS_FILENAME
    diagnostics_payload = {
        "run_id": f"{route_plan.get('route_plan_id', '')}:example",
        "route_plan_id": str(route_plan.get("route_plan_id") or ""),
        "route_plan_hash": str(route_plan.get("route_plan_hash") or ""),
        "failures": [],
    }
    diagnostics_module.write_route_diagnostics(diagnostics_path, diagnostics_payload)
    diagnostics_view = diagnostics_module.load_route_diagnostics(diagnostics_path)
    check_report_path = root / EXAMPLE_CHECK_REPORT_FILENAME
    check_report_payload = build_example_check_report_payload(
        diagnostics_payload=diagnostics_view,
        board_ir=board_ir,
        route_plan=route_plan,
        candidate_count=len(staged.payload.get("candidates") or []),
        apply_report=load_json(apply_report_path),
    )
    _write_json(check_report_path, check_report_payload)
    manifest = build_example_artifact_manifest(
        example_dir=root,
        board_source_path=board_source_path,
        routes_source_path=routes_source_path,
        board_ir_path=board_ir_path,
        route_plan_path=route_plan_path,
        commands=commands,
        counts={
            "board_sources": 1,
            "route_groups": len(list(route_plan.get("route_groups") or [])),
            "candidates": len(staged.payload.get("candidates") or []),
            "apply_reports": 1,
            "diagnostics": 1,
            "checks": 1,
            "authority_false_flags": 5,
        },
        extra_artifacts={
            "backend_manifest": backend_manifest_path,
            "route_candidates": candidates_path,
            "apply_report": apply_report_path,
            "diagnostics": diagnostics_path,
            "check_report": check_report_path,
        },
    )
    manifest_path = write_example_artifact_manifest(root, manifest)
    return ExampleToolingResult(
        example_dir=root,
        board_source_path=board_source_path,
        routes_source_path=routes_source_path,
        board_ir_path=board_ir_path,
        route_plan_path=route_plan_path,
        artifact_manifest_path=manifest_path,
        artifact_manifest=manifest,
        backend_manifest_path=backend_manifest_path,
        candidates_path=candidates_path,
        apply_report_path=apply_report_path,
        diagnostics_path=diagnostics_path,
        check_report_path=check_report_path,
    )


def build_example_check_report_payload(
    *,
    diagnostics_payload: Mapping[str, Any],
    board_ir: Mapping[str, Any],
    route_plan: Mapping[str, Any],
    candidate_count: int,
    apply_report: Mapping[str, Any],
) -> dict[str, Any]:
    diagnostics_rows = list(diagnostics_payload.get("rows") or [])
    diagnostics_summary = diagnostics_payload.get("summary") or {}
    board_ir_payload = _as_payload(board_ir)
    authority = {
        "generated_board_authority": False,
        "routing_authority": False,
        "release_authority": False,
        "jlc_upload_authority": False,
        "orderable_claim": False,
    }
    payload = {
        "schema": "pardal.route_dsl_example_check",
        "version": "0.1",
        "route_plan_id": str(route_plan.get("route_plan_id") or ""),
        "route_plan_hash": str(route_plan.get("route_plan_hash") or ""),
        "board_ir_hash": str(board_ir_payload.get("frozen_board_snapshot_id") or ""),
        "diagnostics_hash": str(diagnostics_payload.get("diagnostics_hash") or ""),
        "diagnostics_row_count": len(diagnostics_rows),
        "diagnostics_summary": diagnostics_summary,
        "candidate_count": int(candidate_count),
        "apply_report_schema": str(apply_report.get("schema") or ""),
        "apply_report_hash": _sha256_manifest(apply_report),
        "apply_report_ok": bool(apply_report.get("accepted", True)),
        "board_ir_ok": True,
        "route_plan_ok": True,
        "candidates_ok": candidate_count >= 0,
        "diagnostics_ok": bool(diagnostics_payload.get("schema") == "pardal.route_diagnostics"),
        "authority": authority,
        "counts": {
            "authority_false_flags": 5,
            "diagnostics_rows": len(diagnostics_rows),
            "candidate_count": int(candidate_count),
            "board_ir_components": len(list(board_ir_payload.get("components") or [])),
            "route_groups": len(list(route_plan.get("route_groups") or [])),
        },
    }
    payload["check_hash"] = _sha256_manifest(payload)
    return payload


def _artifact_entry(path: str | Path) -> dict[str, str]:
    p = Path(path)
    return {
        "path": str(p),
        "sha256": _sha256_file(p),
    }


def _sha256_file(path: Path) -> str:
    digest = sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _sha256_manifest(payload: Mapping[str, Any]) -> str:
    digest = sha256()
    digest.update(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8"))
    return digest.hexdigest()


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _as_payload(board_ir: Any) -> Mapping[str, Any]:
    if hasattr(board_ir, "to_json_payload"):
        return board_ir.to_json_payload()
    if isinstance(board_ir, Mapping):
        return board_ir
    raise TypeError("board_ir must be a mapping or FrozenBoardIR")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def _json_payload(value: Any) -> Mapping[str, Any]:
    if hasattr(value, "to_json_payload"):
        return value.to_json_payload()
    if isinstance(value, Mapping):
        return value
    raise TypeError(f"unsupported payload type: {type(value).__name__}")


def default_example_board_source() -> dict[str, Any]:
    return {
        "schema": "pardal.board_ir_source",
        "version": "0.1",
        "board_ir_id": "routing-dsl-example-board-v001",
        "units": {"length": "mm", "angle": "deg"},
        "outline": [{"x": 0.0, "y": 0.0}, {"x": 24.0, "y": 0.0}, {"x": 24.0, "y": 18.0}, {"x": 0.0, "y": 18.0}],
        "bounds": {"min_x": 0.0, "min_y": 0.0, "max_x": 24.0, "max_y": 18.0},
        "stackup": [
            {"id": "layer-fcu", "name": "F.Cu", "kind": "signal", "order": 1},
            {"id": "layer-bcu", "name": "B.Cu", "kind": "signal", "order": 2},
        ],
        "nets": [
            {"id": "net-gnd", "name": "GND"},
            {"id": "net-sig", "name": "SIG_A"},
        ],
        "components": [
            {
                "id": "comp-u1",
                "refdes": "U1",
                "footprint": "Package_QFP:LQFP-32_7x7mm_P0.8mm",
                "layer": "F.Cu",
                "position": {"x": 8.0, "y": 8.0},
                "rotation": 0.0,
            },
            {
                "id": "comp-j1",
                "refdes": "J1",
                "footprint": "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
                "layer": "F.Cu",
                "position": {"x": 18.0, "y": 10.0},
                "rotation": 90.0,
            },
        ],
        "pads": [
            {
                "id": "pad-u1-1",
                "component_id": "comp-u1",
                "net_id": "net-sig",
                "layer": "F.Cu",
                "kind": "smd",
                "position": {"x": 7.0, "y": 7.0},
            },
            {
                "id": "pad-j1-1",
                "component_id": "comp-j1",
                "net_id": "net-sig",
                "layer": "F.Cu",
                "kind": "thru_hole",
                "position": {"x": 17.0, "y": 9.0},
            },
            {
                "id": "pad-j1-2",
                "component_id": "comp-j1",
                "net_id": "net-gnd",
                "layer": "F.Cu",
                "kind": "thru_hole",
                "position": {"x": 19.0, "y": 9.0},
            },
        ],
        "obstacles": [
            {
                "id": "obs-center",
                "kind": "keepout",
                "layer": "F.Cu",
                "shape": {"type": "rect", "x": 10.0, "y": 4.0, "width": 4.0, "height": 3.0},
            }
        ],
        "envelopes": [
            {
                "id": "env-u1",
                "kind": "placement",
                "ref_id": "comp-u1",
                "layer": "F.Cu",
                "shape": {"type": "rect", "x": 6.0, "y": 6.0, "width": 4.0, "height": 4.0},
            }
        ],
        "provenance": {"source": "examples/routing_dsl/board_source.json"},
        "route_plan_anchor_ids": ["comp-u1", "comp-j1", "pad-u1-1", "pad-j1-1"],
    }


def default_example_routes_source() -> str:
    return """schema: pardal.routes
version: 0.1
board:
  board_ir_id: routing-dsl-example-board-v001
  frozen_board_snapshot_id: routing-dsl-example-board-v001-snapshot-sha256:b8f4c9753c02710f991acd2713fde8d6be1b2e411f4852c59de5f5d7d01d9293
defaults:
  units:
    length: mm
  search:
    candidate_order: lexical
    max_candidates: 4
  diagnostics:
    emit_best_failed_candidate: true
route_groups:
  - id: rg_u1_to_j1
    name: route_u1_to_j1
    select:
      nets: [SIG_A]
      endpoints:
        - ref: U1
          pads: ["1"]
        - ref: J1
          pads: ["1"]
    scope:
      allowed_layers: [F.Cu, B.Cu]
      forbidden_layers: []
      corridors: []
      keepouts: []
    replacement:
      mode: scoped
      nets: [SIG_A]
      existing_route_groups: [rg_u1_to_j1]
      allow_power: false
      allow_planes: false
      max_removed_segments: 2
      max_removed_vias: 1
    variables:
      lane:
        values: [left, right]
"""


def default_example_backend_manifest() -> dict[str, Any]:
    return {
        "backend": {"id": MOJO_BACKEND_ID, "version": MOJO_BACKEND_VERSION},
        "capabilities": {
            "supported_layers": ["F.Cu", "B.Cu"],
            "vias": {"types": ["through"], "max_count": 2},
            "differential_pairs": False,
            "zones": False,
            "keepouts": True,
            "width_mm": {"min": 0.1, "max": 0.5},
            "clearance_mm": {"min": 0.1, "max": 0.25},
            "unsupported_features": [],
        },
    }
