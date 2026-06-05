"""Pure bridge helpers between routing DSL IR and the Mojo lane payloads."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence

from .candidate_schema import CANDIDATE_SCHEMA, CANDIDATE_VERSION, route_candidates_to_json_payload, validate_route_candidates


MOJO_BACKEND_ID = "mojo"
MOJO_BACKEND_VERSION = "1.0"
MOJO_PROBLEM_SCHEMA = "mojo.problem"
MOJO_PROBLEM_VERSION = "1.0"
MOJO_ROUTES_SCHEMA = "mojo.routes"
MOJO_ROUTES_VERSION = "1.0"


class MojoBridgeError(ValueError):
    pass


def load_mojo_problem_payload(path_or_payload: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(path_or_payload, Mapping):
        return validate_mojo_problem_payload(path_or_payload)
    return validate_mojo_problem_payload(json.loads(Path(path_or_payload).read_text(encoding="utf-8")))


def load_mojo_routes_payload(path_or_payload: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(path_or_payload, Mapping):
        return validate_mojo_routes_payload(path_or_payload)
    return validate_mojo_routes_payload(json.loads(Path(path_or_payload).read_text(encoding="utf-8")))


def build_mojo_problem_payload(
    board_ir: Mapping[str, Any],
    route_plan: Mapping[str, Any],
    backend_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    _ensure_supported_backend(backend_manifest)
    board_ir = _board_payload(board_ir)
    route_plan = dict(route_plan)
    route_groups = []
    for group in list(route_plan.get("route_groups") or []):
        if not isinstance(group, Mapping):
            continue
        route_groups.append(_route_group_problem_payload(group))
    payload = {
        "schema": MOJO_PROBLEM_SCHEMA,
        "version": MOJO_PROBLEM_VERSION,
        "backend": _backend_identity(backend_manifest),
        "board": {
            "board_ir_id": str(board_ir.get("board_ir_id") or ""),
            "frozen_board_snapshot_id": str(board_ir.get("frozen_board_snapshot_id") or ""),
            "stackup": _jsonish(board_ir.get("stackup") or []),
            "nets": _jsonish(board_ir.get("nets") or []),
            "components": _jsonish(board_ir.get("components") or []),
            "pads": _jsonish(board_ir.get("pads") or []),
            "obstacles": _jsonish(board_ir.get("obstacles") or []),
        },
        "route_plan": {
            "route_plan_id": str(route_plan.get("route_plan_id") or ""),
            "route_plan_hash": str(route_plan.get("route_plan_hash") or ""),
            "frozen_board_snapshot_id": str(route_plan.get("frozen_board_snapshot_id") or ""),
            "route_groups": route_groups,
        },
        "unsupported_features": _unsupported_features(route_plan, backend_manifest),
    }
    payload["problem_hash"] = _hash_payload(payload)
    return payload


def convert_mojo_routes_to_route_candidates(
    routes_payload: Mapping[str, Any],
    route_plan: Mapping[str, Any],
    backend_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    routes_payload = validate_mojo_routes_payload(routes_payload)
    backend = _backend_identity(backend_manifest)
    route_groups = {
        str(group.get("route_group_id") or group.get("id") or ""): group for group in list(route_plan.get("route_groups") or []) if isinstance(group, Mapping)
    }
    candidates: list[dict[str, Any]] = []
    for item in routes_payload.get("routes") or []:
        group_id = str(item.get("route_group_id") or "")
        group = route_groups.get(group_id, {})
        candidate = {
            "candidate_id": str(item.get("candidate_id") or f"cand_{group_id}_{item.get('candidate_index', 0):04d}"),
            "candidate_index": int(item.get("candidate_index") or 0),
            "route_group_id": group_id,
            "assignment_hash": str(item.get("assignment_hash") or group.get("assignment_hash") or ""),
            "assignment": item.get("assignment") or {},
            "patch": _routes_patch_to_candidate_patch(item.get("patch") or {}),
            "diagnostics": item.get("diagnostics") or [],
            "backend_debug": _backend_debug(item, backend),
        }
        backend_native = item.get("backend_native") or {}
        if isinstance(backend_native, Mapping) and backend_native:
            candidate["backend_debug"]["native"] = _jsonish(backend_native)
        candidates.append(candidate)
    payload = {
        "schema": CANDIDATE_SCHEMA,
        "version": CANDIDATE_VERSION,
        "route_plan_id": str(routes_payload.get("route_plan_id") or route_plan.get("route_plan_id") or ""),
        "route_plan_hash": str(routes_payload.get("route_plan_hash") or route_plan.get("route_plan_hash") or ""),
        "frozen_board_snapshot_id": str(
            routes_payload.get("frozen_board_snapshot_id") or route_plan.get("frozen_board_snapshot_id") or ""
        ),
        "backend": backend,
        "candidates": candidates,
    }
    return validate_route_candidates(payload)


def validate_mojo_problem_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise MojoBridgeError("mojo problem payload must be a mapping")
    schema = str(payload.get("schema") or "")
    version = str(payload.get("version") or "")
    if schema != MOJO_PROBLEM_SCHEMA:
        raise MojoBridgeError(f"unexpected mojo problem schema {schema!r}")
    if version != MOJO_PROBLEM_VERSION:
        raise MojoBridgeError(f"unexpected mojo problem version {version!r}")
    backend = _backend_identity(payload.get("backend") or {})
    board = payload.get("board") or {}
    route_plan = payload.get("route_plan") or {}
    route_groups = [group for group in list(route_plan.get("route_groups") or []) if isinstance(group, Mapping)]
    normalized = {
        "schema": schema,
        "version": version,
        "backend": backend,
        "board": {
            "board_ir_id": str(board.get("board_ir_id") or ""),
            "frozen_board_snapshot_id": str(board.get("frozen_board_snapshot_id") or ""),
            "stackup": _jsonish(board.get("stackup") or []),
            "nets": _jsonish(board.get("nets") or []),
            "components": _jsonish(board.get("components") or []),
            "pads": _jsonish(board.get("pads") or []),
            "obstacles": _jsonish(board.get("obstacles") or []),
        },
        "route_plan": {
            "route_plan_id": str(route_plan.get("route_plan_id") or ""),
            "route_plan_hash": str(route_plan.get("route_plan_hash") or ""),
            "frozen_board_snapshot_id": str(route_plan.get("frozen_board_snapshot_id") or ""),
            "route_groups": [_route_group_problem_payload(group) for group in route_groups],
        },
        "unsupported_features": tuple(str(item) for item in _unsupported_features(route_plan, {"capabilities": {}})),
        "problem_hash": str(payload.get("problem_hash") or ""),
    }
    return normalized


def validate_mojo_routes_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise MojoBridgeError("mojo routes payload must be a mapping")
    schema = str(payload.get("schema") or "")
    version = str(payload.get("version") or "")
    if schema != MOJO_ROUTES_SCHEMA:
        raise MojoBridgeError(f"unexpected mojo routes schema {schema!r}")
    if version != MOJO_ROUTES_VERSION:
        raise MojoBridgeError(f"unexpected mojo routes version {version!r}")
    routes = payload.get("routes")
    if routes is None:
        routes = []
    if not isinstance(routes, list):
        raise MojoBridgeError("routes must be a list")
    normalized_routes = []
    for item in routes:
        if not isinstance(item, Mapping):
            raise MojoBridgeError("route entries must be mappings")
        normalized_routes.append(
            {
                "route_group_id": str(item.get("route_group_id") or ""),
                "candidate_id": str(item.get("candidate_id") or ""),
                "candidate_index": int(item.get("candidate_index") or 0),
                "assignment_hash": str(item.get("assignment_hash") or ""),
                "assignment": _jsonish(item.get("assignment") or {}),
                "patch": _jsonish(item.get("patch") or {}),
                "diagnostics": _normalize_diagnostics(item.get("diagnostics") or []),
                "backend_native": _jsonish(item.get("backend_native") or {}),
            }
        )
    normalized = {
        "schema": schema,
        "version": version,
        "route_plan_id": str(payload.get("route_plan_id") or ""),
        "route_plan_hash": str(payload.get("route_plan_hash") or ""),
        "frozen_board_snapshot_id": str(payload.get("frozen_board_snapshot_id") or ""),
        "routes": normalized_routes,
    }
    return normalized


def _ensure_supported_backend(backend_manifest: Mapping[str, Any]) -> None:
    backend = _backend_identity(backend_manifest)
    if backend["id"] != MOJO_BACKEND_ID:
        raise MojoBridgeError("mojo bridge only supports mojo backend manifests")


def _backend_identity(backend_manifest: Mapping[str, Any]) -> dict[str, Any]:
    backend = backend_manifest.get("backend") or {}
    return {"id": str(backend.get("id") or ""), "version": str(backend.get("version") or "")}


def _board_payload(board_ir: Any) -> dict[str, Any]:
    if hasattr(board_ir, "to_json_payload"):
        board = board_ir.to_json_payload()
        return {
            "board_ir_id": str(board.get("board_ir_id") or ""),
            "frozen_board_snapshot_id": str(board.get("frozen_board_snapshot_id") or ""),
            "stackup": _jsonish(board.get("stackup") or []),
            "nets": _jsonish(board.get("nets") or []),
            "components": _jsonish(board.get("components") or []),
            "pads": _jsonish(board.get("pads") or []),
            "obstacles": _jsonish(board.get("obstacles") or []),
        }
    if isinstance(board_ir, Mapping):
        board = board_ir
    else:
        board = getattr(board_ir, "__dict__", {})
    return {
        "board_ir_id": str(board.get("board_ir_id") or ""),
        "frozen_board_snapshot_id": str(board.get("frozen_board_snapshot_id") or ""),
        "stackup": _jsonish(board.get("stackup") or []),
        "nets": _jsonish(board.get("nets") or []),
        "components": _jsonish(board.get("components") or []),
        "pads": _jsonish(board.get("pads") or []),
        "obstacles": _jsonish(board.get("obstacles") or []),
    }


def _route_group_problem_payload(group: Mapping[str, Any]) -> dict[str, Any]:
    scope = group.get("scope") or {}
    select = group.get("select") or {}
    return {
        "route_group_id": str(group.get("route_group_id") or group.get("id") or ""),
        "source_route_group_name": str(group.get("source_route_group_name") or group.get("name") or ""),
        "route_group_output_id": str(group.get("route_group_output_id") or ""),
        "assignment_hash": str(group.get("assignment_hash") or ""),
        "candidate_count": int(group.get("candidate_count") or 0),
        "scope": _jsonish(scope),
        "select": _jsonish(select),
        "replacement": _jsonish(group.get("replacement") or {}),
        "placement_moves": _jsonish(group.get("placement_moves") or []),
        "variables": _jsonish(group.get("variables") or []),
    }


def _unsupported_features(route_plan: Mapping[str, Any], backend_manifest: Mapping[str, Any]) -> list[str]:
    manifest_features = list((backend_manifest.get("capabilities") or {}).get("unsupported_features") or [])
    requested = []
    for group in list(route_plan.get("route_groups") or []):
        if not isinstance(group, Mapping):
            continue
        requested.extend(str(token) for token in list(group.get("unsupported_features") or []) if token)
    return sorted(set(requested) & set(str(item) for item in manifest_features))


def _routes_patch_to_candidate_patch(patch: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"remove_objects", "move_components", "add_tracks", "add_vias", "add_arcs", "add_zones", "set_net_ties"}
    return {key: _jsonish(patch.get(key) or ([] if key != "set_net_ties" else [])) for key in allowed if key in patch or key != "set_net_ties"}


def _backend_debug(route_item: Mapping[str, Any], backend: Mapping[str, Any]) -> dict[str, Any]:
    debug = {
        "backend_id": backend.get("id", ""),
        "backend_version": backend.get("version", ""),
    }
    for field in ("problem_id", "solver_status", "timing", "native_id", "lane_id"):
        if field in route_item:
            debug[field] = _jsonish(route_item.get(field))
    return debug


def _normalize_diagnostics(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise MojoBridgeError("diagnostics must be a sequence")
    result = []
    for item in value:
        if isinstance(item, Mapping):
            result.append(str(item.get("id") or ""))
        else:
            result.append(str(item))
    return tuple(result)


def _jsonish(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonish(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_jsonish(item) for item in value]
    if isinstance(value, list):
        return [_jsonish(item) for item in value]
    return value


def _hash_payload(payload: Mapping[str, Any]) -> str:
    return "sha256:" + sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()
