"""Candidate commit gate for routing DSL staged outputs.

This module validates a selected candidate against frozen board IR and route
plan linkage. It does not mutate KiCad state or claim committed-board authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
import json

from .board_ir import FrozenBoardIR, load_board_ir
from .candidate_schema import RouteCandidateSchemaError, load_route_candidates, validate_route_candidates
from .diagnostics import normalize_route_diagnostics
from .route_plan import load_route_plan, normalize_route_plan_payload


APPLY_REPORT_SCHEMA = "pardal.route_apply_report"
APPLY_REPORT_VERSION = "0.1"

_FORBIDDEN_AUTHORITY_FIELDS = (
    "generated_board_authority",
    "routing_authority",
    "release_authority",
    "jlc_upload_authority",
    "orderable_claim",
)


class CommitGateError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CommitGateResult:
    accepted: bool
    payload: dict[str, Any]


def validate_candidate_commit(
    board_ir: str | Path | FrozenBoardIR | Mapping[str, Any],
    route_plan: str | Path | Mapping[str, Any],
    candidate_payload: str | Path | Mapping[str, Any],
    *,
    selected_candidate_id: str | None = None,
) -> CommitGateResult:
    board = _load_board(board_ir)
    plan = _load_route_plan(route_plan)
    candidates = _load_candidates(candidate_payload)
    candidate = _select_candidate(candidates, selected_candidate_id)
    violations = list(_validate_candidate(board, plan, candidates, candidate))
    accepted = not violations
    payload = {
        "schema": APPLY_REPORT_SCHEMA,
        "version": APPLY_REPORT_VERSION,
        "accepted": accepted,
        "generated_board_authority": False,
        "routing_authority": False,
        "release_authority": False,
        "jlc_upload_authority": False,
        "orderable_claim": False,
        "board_ir_id": board.board_ir_id,
        "frozen_board_snapshot_id": board.frozen_board_snapshot_id,
        "route_plan_id": str(plan.get("route_plan_id") or ""),
        "route_plan_hash": str(plan.get("route_plan_hash") or ""),
        "candidate_id": str(candidate.get("candidate_id") or ""),
        "candidate_index": candidate.get("candidate_index"),
        "route_group_id": str(candidate.get("route_group_id") or ""),
        "violations": violations,
        "candidate": _candidate_report(candidate),
        "route_plan": _route_plan_report(plan),
        "board_ir": _board_report(board),
    }
    payload["summary"] = {
        "violation_count": len(violations),
        "selected_candidate_id": str(candidate.get("candidate_id") or ""),
    }
    return CommitGateResult(accepted=accepted, payload=payload)


def apply_candidate_to_copy(
    board_ir: str | Path | FrozenBoardIR | Mapping[str, Any],
    route_plan: str | Path | Mapping[str, Any],
    candidate_payload: str | Path | Mapping[str, Any],
    output_report_path: str | Path,
    *,
    selected_candidate_id: str | None = None,
) -> dict[str, Any]:
    result = validate_candidate_commit(
        board_ir,
        route_plan,
        candidate_payload,
        selected_candidate_id=selected_candidate_id,
    )
    output_path = Path(output_report_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result.payload, sort_keys=True, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return result.payload


def _validate_candidate(
    board: FrozenBoardIR,
    plan: Mapping[str, Any],
    candidates: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    if str(candidates.get("route_plan_id") or "") != str(plan.get("route_plan_id") or ""):
        violations.append(_violation("route_plan_id_mismatch", "candidate batch route_plan_id does not match route plan"))
    if str(candidates.get("route_plan_hash") or "") != str(plan.get("route_plan_hash") or ""):
        violations.append(_violation("route_plan_hash_mismatch", "candidate batch route_plan_hash does not match route plan"))
    if str(candidates.get("frozen_board_snapshot_id") or "") != board.frozen_board_snapshot_id:
        violations.append(_violation("snapshot_mismatch", "candidate batch snapshot does not match board snapshot"))
    if str(candidates.get("route_plan_id") or "") and str(candidates.get("route_plan_id") or "") != str(plan.get("route_plan_id") or ""):
        violations.append(_violation("route_plan_linkage", "candidate batch is not linked to the selected route plan"))

    route_group = _match_route_group(plan, str(candidate.get("route_group_id") or ""))
    if not route_group:
        violations.append(_violation("unknown_route_group", "candidate route_group_id is not present in route plan"))
    else:
        violations.extend(_validate_scope(board, route_group, candidate))

    violations.extend(_reject_authority_claims(candidate))
    violations.extend(_validate_patch_refs(board, candidate, route_group))
    violations.extend(_validate_movement_envelopes(board, route_group, candidate))
    return violations


def _validate_scope(board: FrozenBoardIR, route_group: Mapping[str, Any], candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    scope = route_group.get("scope") or {}
    allowed_layers = {str(item.get("name") or item) for item in list(scope.get("allowed_layers") or []) if item is not None}
    forbidden_layers = {str(item.get("name") or item) for item in list(route_group.get("scope", {}).get("forbidden_layers") or []) if item is not None}
    patch = candidate.get("patch") or {}
    for track in list(patch.get("add_tracks") or []):
        layer = str(track.get("layer") or "")
        if allowed_layers and layer not in allowed_layers:
            violations.append(_violation("layer_not_allowed", f"track layer {layer!r} is outside the route scope"))
        if layer in forbidden_layers:
            violations.append(_violation("forbidden_layer", f"track layer {layer!r} is forbidden by the route plan"))
        net = str(track.get("net") or "")
        if net and not _net_name_exists(board, net):
            violations.append(_violation("unknown_net", f"track net {net!r} is unknown to the board", source_field="patch.add_tracks.net"))
    for via in list(patch.get("add_vias") or []):
        for field in ("net", "from_layer", "to_layer"):
            value = str(via.get(field) or "")
            if field == "net" and value and not _net_name_exists(board, value):
                violations.append(_violation("unknown_net", f"via net {value!r} is unknown to the board", source_field="patch.add_vias.net"))
            if field in {"from_layer", "to_layer"} and value and not _layer_exists(board, value):
                violations.append(_violation("unknown_layer", f"via {field} {value!r} is unknown to the board", source_field=f"patch.add_vias.{field}"))
    return violations


def _validate_patch_refs(board: FrozenBoardIR, candidate: Mapping[str, Any], route_group: Mapping[str, Any]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    patch = candidate.get("patch") or {}
    for move in list(patch.get("move_components") or []):
        component_id = str(move.get("component_id") or "")
        if component_id and component_id not in {component.id for component in board.components}:
            violations.append(_violation("unknown_component", f"component {component_id!r} is unknown to the board", source_field="patch.move_components.component_id"))
    replacement = route_group.get("replacement") or {}
    if replacement.get("mode") == "scoped":
        allowed_nets = {str(net) for net in list(replacement.get("nets") or [])}
        for track in list(patch.get("add_tracks") or []):
            net = str(track.get("net") or "")
            if allowed_nets and net not in allowed_nets:
                violations.append(_violation("replacement_scope_net", f"net {net!r} is outside the replacement scope"))
    return violations


def _validate_movement_envelopes(board: FrozenBoardIR, route_group: Mapping[str, Any], candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    movement = {move.get("ref"): move for move in list(route_group.get("placement_moves") or []) if isinstance(move, Mapping)}
    for move in list(candidate.get("patch", {}).get("move_components") or []):
        ref = str(move.get("ref") or "")
        allowed = movement.get(ref)
        if allowed is None:
            violations.append(_violation("movement_not_allowed", f"movement for {ref!r} is not authorized by route plan"))
            continue
        pos = move.get("position") or {}
        envelope = allowed.get("envelope") or {}
        if isinstance(pos, Mapping):
            x = float(pos.get("x"))
            y = float(pos.get("y"))
            dx = envelope.get("dx") or [0.0, 0.0]
            dy = envelope.get("dy") or [0.0, 0.0]
            base = _component_position(board, str(move.get("component_id") or ""))
            if base is not None:
                if not (base[0] + float(dx[0]) <= x <= base[0] + float(dx[1])):
                    violations.append(_violation("movement_envelope_x", f"{ref!r} x movement is outside the envelope"))
                if not (base[1] + float(dy[0]) <= y <= base[1] + float(dy[1])):
                    violations.append(_violation("movement_envelope_y", f"{ref!r} y movement is outside the envelope"))
    return violations


def _reject_authority_claims(candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    for field in _FORBIDDEN_AUTHORITY_FIELDS:
        if candidate.get(field) is True:
            violations.append(_violation("authority_claim", f"candidate may not claim {field}"))
        if field in candidate:
            violations.append(_violation("authority_field_present", f"candidate may not include {field}"))
    patch = candidate.get("patch") or {}
    for field in _FORBIDDEN_AUTHORITY_FIELDS:
        if field in patch:
            violations.append(_violation("authority_field_present", f"candidate patch may not include {field}"))
    for disallowed in ("board_path", "input_board_path", "source_board_path", "output_board_path"):
        if disallowed in candidate or disallowed in patch:
            violations.append(_violation("input_path_mutation", f"candidate may not mutate {disallowed}"))
    return violations


def _match_route_group(plan: Mapping[str, Any], route_group_id: str) -> Mapping[str, Any]:
    for route_group in list(plan.get("route_groups") or []):
        if str(route_group.get("route_group_id") or route_group.get("id") or "") == route_group_id:
            return route_group
    return {}


def _net_name_exists(board: FrozenBoardIR, net_name: str) -> bool:
    return any(net.name == net_name for net in board.nets)


def _layer_exists(board: FrozenBoardIR, layer_name: str) -> bool:
    return any(layer.name == layer_name for layer in board.stackup)


def _component_position(board: FrozenBoardIR, component_id: str) -> tuple[float, float] | None:
    for component in board.components:
        if component.id == component_id:
            return component.position
    return None


def _candidate_report(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": str(candidate.get("candidate_id") or ""),
        "candidate_index": candidate.get("candidate_index"),
        "route_group_id": str(candidate.get("route_group_id") or ""),
        "assignment_hash": str(candidate.get("assignment_hash") or ""),
        "backend_debug": dict(candidate.get("backend_debug") or {}),
    }


def _route_plan_report(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "route_plan_id": str(plan.get("route_plan_id") or ""),
        "route_plan_hash": str(plan.get("route_plan_hash") or ""),
        "board_ir_id": str(plan.get("board_ir_id") or ""),
        "frozen_board_snapshot_id": str(plan.get("frozen_board_snapshot_id") or ""),
    }


def _board_report(board: FrozenBoardIR) -> dict[str, Any]:
    return {
        "board_ir_id": board.board_ir_id,
        "frozen_board_snapshot_id": board.frozen_board_snapshot_id,
        "route_plan_anchor_ids": list(board.route_plan_anchor_ids),
    }


def _violation(code: str, message: str, *, source_field: str = "") -> dict[str, Any]:
    return {"code": code, "message": message, "source_field": source_field}


def _load_board(board_ir: str | Path | FrozenBoardIR | Mapping[str, Any]) -> FrozenBoardIR:
    if isinstance(board_ir, FrozenBoardIR):
        return board_ir
    return load_board_ir(board_ir)


def _load_candidates(candidate_payload: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(candidate_payload, Mapping):
        return validate_route_candidates(candidate_payload)
    return load_route_candidates(candidate_payload)


def _load_route_plan(route_plan: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(route_plan, Mapping):
        return normalize_route_plan_payload(route_plan)
    return normalize_route_plan_payload(route_plan)


def _select_candidate(candidates: Mapping[str, Any], selected_candidate_id: str | None) -> Mapping[str, Any]:
    items = list(candidates.get("candidates") or [])
    if not items:
        raise CommitGateError("candidate batch contains no candidates")
    if selected_candidate_id is None:
        return items[0]
    for item in items:
        if str(item.get("candidate_id") or "") == selected_candidate_id:
            return item
    raise CommitGateError(f"selected candidate {selected_candidate_id!r} not found")
