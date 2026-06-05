"""Pure file-oriented workflow helpers for routing DSL artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from . import board_ir as board_ir_module
from . import capability_gate as capability_gate_module
from . import diagnostics as diagnostics_module
from . import route_plan as route_plan_module
from . import source as source_module


ROUTE_PLAN_FILENAME = "route-plan.ir.json"
CAPABILITY_REPORT_FILENAME = "capability-report.json"
ROUTE_DIAGNOSTICS_FILENAME = "route-diagnostics.json"


@dataclass(frozen=True)
class RouteWorkflowResult:
    route_plan_path: Path
    artifact_path: Path
    artifact_kind: str
    route_plan: dict[str, Any]
    artifact_payload: dict[str, Any]


class RouteWorkflowError(ValueError):
    pass


class StaleRoutePlanError(RouteWorkflowError):
    pass


def run_route_workflow(
    routes_source_path: str | Path,
    board_ir_path: str | Path,
    backend_manifest_path: str | Path,
    output_dir: str | Path,
) -> RouteWorkflowResult:
    source = source_module.load_routes_source(routes_source_path)
    board = board_ir_module.load_board_ir(board_ir_path)
    manifest = capability_gate_module.load_backend_manifest(backend_manifest_path)

    route_plan = route_plan_module.normalize_route_plan_payload(route_plan_module.resolve_route_plan(source, board))
    _ensure_route_plan_is_fresh(route_plan, source, board)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    route_plan_path = output_path / ROUTE_PLAN_FILENAME
    _write_json(route_plan_path, route_plan)

    capability_view = capability_gate_module.evaluate_backend_capabilities(_capability_gate_view(route_plan), manifest)
    if capability_view["supported"]:
        artifact_path = output_path / CAPABILITY_REPORT_FILENAME
        _write_json(artifact_path, capability_view)
        return RouteWorkflowResult(
            route_plan_path=route_plan_path,
            artifact_path=artifact_path,
            artifact_kind="capability-report",
            route_plan=route_plan,
            artifact_payload=capability_view,
        )

    diagnostics_payload = _route_diagnostics_from_capability_failures(route_plan, manifest, capability_view)
    artifact_path = output_path / ROUTE_DIAGNOSTICS_FILENAME
    diagnostics_module.write_route_diagnostics(artifact_path, diagnostics_payload)
    return RouteWorkflowResult(
        route_plan_path=route_plan_path,
        artifact_path=artifact_path,
        artifact_kind="route-diagnostics",
        route_plan=route_plan,
        artifact_payload=diagnostics_module.load_route_diagnostics(artifact_path),
    )


def load_route_workflow_inputs(
    routes_source_path: str | Path,
    board_ir_path: str | Path,
    backend_manifest_path: str | Path,
) -> dict[str, Any]:
    return {
        "routes_source": source_module.load_routes_source(routes_source_path),
        "board_ir": board_ir_module.load_board_ir(board_ir_path),
        "backend_manifest": capability_gate_module.load_backend_manifest(backend_manifest_path),
    }


def load_route_plan_artifact(path: str | Path) -> dict[str, Any]:
    return route_plan_module.normalize_route_plan_payload(Path(path))


def _ensure_route_plan_is_fresh(
    route_plan: Mapping[str, Any],
    source: source_module.RoutingSource,
    board: board_ir_module.FrozenBoardIR,
) -> None:
    if str(route_plan.get("board_ir_id") or "") != source.board_ir_id:
        raise StaleRoutePlanError(
            f"route-plan board_ir_id {route_plan.get('board_ir_id')!r} does not match source board_ir_id {source.board_ir_id!r}"
        )
    if str(route_plan.get("board_ir_id") or "") != board.board_ir_id:
        raise StaleRoutePlanError(
            f"route-plan board_ir_id {route_plan.get('board_ir_id')!r} does not match board_ir {board.board_ir_id!r}"
        )
    if str(route_plan.get("frozen_board_snapshot_id") or "") != source.frozen_board_snapshot_id:
        raise StaleRoutePlanError(
            "route-plan frozen_board_snapshot_id does not match source frozen_board_snapshot_id"
        )
    if str(route_plan.get("frozen_board_snapshot_id") or "") != board.frozen_board_snapshot_id:
        raise StaleRoutePlanError(
            "route-plan frozen_board_snapshot_id does not match board_ir snapshot"
        )


def _route_diagnostics_from_capability_failures(
    route_plan: Mapping[str, Any],
    manifest: Mapping[str, Any],
    capability_view: Mapping[str, Any],
) -> dict[str, Any]:
    failures = []
    route_groups = list(route_plan.get("route_groups") or [])
    backend_id = str((manifest.get("backend") or {}).get("id") or "")
    for failure in capability_view.get("failures") or []:
        route_group = _match_route_group(route_groups, str(failure.get("route_group_id") or ""))
        failures.append(
            {
                "run_id": f"{route_plan.get('route_plan_id', '')}:{backend_id}",
                "route_plan_id": str(route_plan.get("route_plan_id") or ""),
                "route_plan_hash": str(route_plan.get("route_plan_hash") or ""),
                "route_group_id": str(failure.get("route_group_id") or ""),
                "source_route_group_name": str(route_group.get("source_route_group_name") or route_group.get("name") or ""),
                "candidate_id": "",
                "candidate_index": None,
                "assignment": {},
                "strategy": {
                    "kind": str(((route_plan.get("defaults") or {}).get("search") or {}).get("candidate_order") or ""),
                    "profile_id": backend_id,
                },
                "backend_profile_id": backend_id,
                "failed_stage": "capability",
                "code": str(failure.get("code") or ""),
                "message": str(failure.get("message") or ""),
                "source_span": {},
                "provenance": {
                    "source_field": str(failure.get("source_field") or ""),
                    "expected": failure.get("expected"),
                    "actual": failure.get("actual"),
                },
                "generated_board_authority": False,
                "routing_authority": False,
                "release_authority": False,
                "jlc_upload_authority": False,
                "orderable_claim": False,
            }
        )
    return {
        "run_id": f"{route_plan.get('route_plan_id', '')}:{backend_id}",
        "route_plan_id": str(route_plan.get("route_plan_id") or ""),
        "route_plan_hash": str(route_plan.get("route_plan_hash") or ""),
        "failures": failures,
    }


def _capability_gate_view(route_plan: Mapping[str, Any]) -> dict[str, Any]:
    groups = []
    for group in list(route_plan.get("route_groups") or []):
        if not isinstance(group, Mapping):
            continue
        scope = group.get("scope") or {}
        allowed_layers = []
        if isinstance(scope, Mapping):
            for layer in list(scope.get("allowed_layers") or []):
                if isinstance(layer, Mapping):
                    allowed_layers.append(str(layer.get("name") or ""))
                else:
                    allowed_layers.append(str(layer))
        groups.append(
            {
                "id": str(group.get("route_group_id") or group.get("id") or ""),
                "scope": {
                    "allowed_layers": allowed_layers,
                    "zones": bool((scope or {}).get("zones")),
                    "keepouts": bool((scope or {}).get("keepouts")),
                    "differential_pairs": bool((scope or {}).get("differential_pairs")),
                },
                "constraints": dict(group.get("constraints") or {}),
                "via": dict(group.get("via") or {}),
                "features": list(group.get("features") or []),
            }
        )
    return {
        "route_plan_id": route_plan.get("route_plan_id", ""),
        "route_plan_hash": route_plan.get("route_plan_hash", ""),
        "backend": dict(route_plan.get("backend") or {}),
        "route_groups": groups,
    }


def _match_route_group(route_groups: list[Mapping[str, Any]], route_group_id: str) -> Mapping[str, Any]:
    for route_group in route_groups:
        if str(route_group.get("route_group_id") or route_group.get("id") or "") == route_group_id:
            return route_group
    return {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, sort_keys=True, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
