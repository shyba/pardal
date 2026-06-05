"""Validation and normalization for staged route candidate batches."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import math
from typing import Any, Mapping


CANDIDATE_SCHEMA = "pardal.route_candidates"
CANDIDATE_VERSION = "0.1"
ALLOWED_PATCH_KEYS = {
    "remove_objects",
    "move_components",
    "add_tracks",
    "add_vias",
    "add_arcs",
    "add_zones",
    "set_net_ties",
}


class RouteCandidateSchemaError(ValueError):
    def __init__(self, message: str, path: Path | None = None):
        self.message = message
        self.path = path
        super().__init__(message)

    def __str__(self) -> str:  # pragma: no cover - formatting only
        if self.path is None:
            return self.message
        return f"{self.path}: {self.message}"


def load_route_candidates(path: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(path, Mapping):
        return validate_route_candidates(path)
    candidate_path = Path(path)
    return validate_route_candidates(json.loads(candidate_path.read_text(encoding="utf-8")))


def normalize_route_candidates(payload: Mapping[str, Any]) -> dict[str, Any]:
    return validate_route_candidates(payload)


def route_candidates_to_json_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = validate_route_candidates(payload)
    return _to_json_compatible(normalized)


def write_route_candidates(path: str | Path, payload: Mapping[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(route_candidates_to_json_payload(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n", encoding="utf-8")


def validate_route_candidates(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise RouteCandidateSchemaError("route-candidates root must be a mapping")

    schema = _require_string(payload, "schema", "schema")
    if schema != CANDIDATE_SCHEMA:
        raise RouteCandidateSchemaError(
            f"unexpected schema {schema!r}; expected {CANDIDATE_SCHEMA!r}"
        )

    version = _require_string(payload, "version", "version")
    if version != CANDIDATE_VERSION:
        raise RouteCandidateSchemaError(
            f"unexpected version {version!r}; expected {CANDIDATE_VERSION!r}"
        )

    route_plan_id = _require_string(payload, "route_plan_id", "route_plan_id")
    route_plan_hash = _require_string(payload, "route_plan_hash", "route_plan_hash")
    frozen_board_snapshot_id = _require_string(
        payload, "frozen_board_snapshot_id", "frozen_board_snapshot_id"
    )
    _validate_route_plan_link(route_plan_id, route_plan_hash)
    backend = _require_mapping(payload, "backend", "backend")
    backend_id = _require_string(backend, "id", "backend.id")
    backend_version = _require_string(backend, "version", "backend.version")

    candidates_raw = payload.get("candidates", [])
    if candidates_raw is None:
        candidates_raw = []
    if not isinstance(candidates_raw, list):
        raise RouteCandidateSchemaError("candidates must be a list")

    normalized_candidates = []
    seen_candidate_ids: set[str] = set()
    seen_route_group_ids: set[str] = set()
    for item in candidates_raw:
        if not isinstance(item, Mapping):
            raise RouteCandidateSchemaError("candidate entries must be mappings")
        normalized = _normalize_candidate(item)
        candidate_id = normalized["candidate_id"]
        if candidate_id in seen_candidate_ids:
            raise RouteCandidateSchemaError(f"duplicate candidate_id {candidate_id!r}")
        seen_candidate_ids.add(candidate_id)
        route_group_id = normalized["route_group_id"]
        if route_group_id in seen_route_group_ids:
            # multiple candidates for a route group are allowed; this set is only used
            # to ensure the batch is stable and indexed correctly below.
            pass
        normalized_candidates.append(normalized)

    normalized_candidates.sort(key=_candidate_sort_key)
    _validate_batch_indices(normalized_candidates)

    result = {
        "schema": schema,
        "version": version,
        "route_plan_id": route_plan_id,
        "route_plan_hash": route_plan_hash,
        "frozen_board_snapshot_id": frozen_board_snapshot_id,
        "backend": {"id": backend_id, "version": backend_version},
        "candidates": normalized_candidates,
    }
    result["batch_hash"] = _hash_payload(result)
    return result


def _normalize_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    candidate_id = _require_string(candidate, "candidate_id", "candidate_id")
    candidate_index = _require_int(candidate, "candidate_index", "candidate_index")
    route_group_id = _require_string(candidate, "route_group_id", "route_group_id")
    assignment_hash = _require_string(candidate, "assignment_hash", "assignment_hash")
    assignment = candidate.get("assignment", {})
    if assignment is None:
        assignment = {}
    if not isinstance(assignment, Mapping):
        raise RouteCandidateSchemaError("assignment must be a mapping")
    patch = _normalize_patch(candidate.get("patch", {}))
    diagnostics = candidate.get("diagnostics", [])
    if diagnostics is None:
        diagnostics = []
    if not isinstance(diagnostics, (list, tuple)):
        raise RouteCandidateSchemaError("diagnostics must be a list")
    diagnostics_ids = []
    for diag in diagnostics:
        if isinstance(diag, Mapping):
            diagnostics_ids.append(_require_string(diag, "id", "diagnostics.id"))
        elif isinstance(diag, str):
            diagnostics_ids.append(diag.strip())
        else:
            raise RouteCandidateSchemaError("diagnostics entries must be mappings")

    if "committed_copper" in candidate:
        raise RouteCandidateSchemaError("committed_copper authority claims are not allowed")
    if "authority" in candidate:
        raise RouteCandidateSchemaError("authority claims are not allowed")

    for key in candidate.keys():
        if key in {
            "candidate_id",
            "candidate_index",
            "route_group_id",
            "assignment_hash",
            "assignment",
            "patch",
            "diagnostics",
        }:
            continue
        if key.startswith("backend_") or key == "backend_debug":
            continue
        raise RouteCandidateSchemaError(f"unknown candidate field {key!r}")

    return {
        "candidate_id": candidate_id,
        "candidate_index": candidate_index,
        "route_group_id": route_group_id,
        "assignment_hash": assignment_hash,
        "assignment": _sorted_jsonish(assignment),
        "patch": patch,
        "diagnostics": tuple(diagnostics_ids),
        "backend_debug": _sorted_jsonish(candidate.get("backend_debug", {})),
    }


def _normalize_patch(patch: Any) -> dict[str, Any]:
    if patch is None:
        patch = {}
    if not isinstance(patch, Mapping):
        raise RouteCandidateSchemaError("patch must be a mapping")
    unknown = set(patch.keys()) - ALLOWED_PATCH_KEYS
    if unknown:
        raise RouteCandidateSchemaError(f"unknown patch field {sorted(unknown)[0]!r}")

    normalized: dict[str, Any] = {}
    normalized["remove_objects"] = _normalize_object_ids(patch.get("remove_objects", []), "remove_objects")
    normalized["move_components"] = _normalize_move_components(patch.get("move_components", []))
    normalized["add_tracks"] = _normalize_tracks(patch.get("add_tracks", []))
    normalized["add_vias"] = _normalize_vias(patch.get("add_vias", []))
    normalized["add_arcs"] = _normalize_arcs(patch.get("add_arcs", []))
    normalized["add_zones"] = _normalize_zones(patch.get("add_zones", []))
    normalized["set_net_ties"] = _sorted_jsonish(patch.get("set_net_ties", []))
    return normalized


def _normalize_object_ids(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        value = []
    if not isinstance(value, (list, tuple)):
        raise RouteCandidateSchemaError(f"{field} must be a list")
    ids = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise RouteCandidateSchemaError(f"{field} entries must be non-empty strings")
        ids.append(item.strip())
    return tuple(sorted(ids))


def _normalize_move_components(value: Any) -> tuple[dict[str, Any], ...]:
    if value is None:
        value = []
    if not isinstance(value, (list, tuple)):
        raise RouteCandidateSchemaError("move_components must be a list")
    moves = []
    for item in value:
        if not isinstance(item, Mapping):
            raise RouteCandidateSchemaError("move_components entries must be mappings")
        component_id = _require_string(item, "component_id", "move_components.component_id")
        ref = _require_string(item, "ref", "move_components.ref")
        position = _require_point(item.get("position"), "move_components.position")
        layer = item.get("layer")
        if layer is not None and not isinstance(layer, str):
            raise RouteCandidateSchemaError("move_components.layer must be a string")
        rotation = item.get("rotation")
        if rotation is not None:
            rotation = _require_finite_number(rotation, "move_components.rotation")
        for key in item.keys():
            if key not in {"component_id", "ref", "position", "layer", "rotation"}:
                raise RouteCandidateSchemaError(f"unknown move_components field {key!r}")
        moves.append(
            {
                "component_id": component_id,
                "ref": ref,
                "position": position,
                "layer": layer,
                "rotation": rotation,
            }
        )
    return tuple(sorted(moves, key=lambda item: (item["component_id"], item["ref"], item["position"])))


def _normalize_tracks(value: Any) -> tuple[dict[str, Any], ...]:
    if value is None:
        value = []
    if not isinstance(value, (list, tuple)):
        raise RouteCandidateSchemaError("add_tracks must be a list")
    tracks = []
    for item in value:
        if not isinstance(item, Mapping):
            raise RouteCandidateSchemaError("add_tracks entries must be mappings")
        tracks.append(
            {
                "net": _require_string(item, "net", "add_tracks.net"),
                "layer": _require_string(item, "layer", "add_tracks.layer"),
                "width": _require_finite_number(item.get("width"), "add_tracks.width"),
                "points": _normalize_points(item.get("points"), "add_tracks.points"),
            }
        )
        _reject_unknown_keys(item, {"net", "layer", "width", "points"}, "add_tracks")
    return tuple(sorted(tracks, key=lambda item: (item["net"], item["layer"], item["points"])))


def _normalize_vias(value: Any) -> tuple[dict[str, Any], ...]:
    if value is None:
        value = []
    if not isinstance(value, (list, tuple)):
        raise RouteCandidateSchemaError("add_vias must be a list")
    vias = []
    for item in value:
        if not isinstance(item, Mapping):
            raise RouteCandidateSchemaError("add_vias entries must be mappings")
        vias.append(
            {
                "net": _require_string(item, "net", "add_vias.net"),
                "position": _normalize_point(item.get("position"), "add_vias.position"),
                "from_layer": _require_string(item, "from_layer", "add_vias.from_layer"),
                "to_layer": _require_string(item, "to_layer", "add_vias.to_layer"),
                "type": _require_string(item, "type", "add_vias.type"),
                "drill": _require_finite_number(item.get("drill"), "add_vias.drill"),
            }
        )
        _reject_unknown_keys(item, {"net", "position", "from_layer", "to_layer", "type", "drill"}, "add_vias")
    return tuple(sorted(vias, key=lambda item: (item["net"], item["position"], item["from_layer"], item["to_layer"])))


def _normalize_arcs(value: Any) -> tuple[dict[str, Any], ...]:
    if value is None:
        value = []
    if not isinstance(value, (list, tuple)):
        raise RouteCandidateSchemaError("add_arcs must be a list")
    arcs = []
    for item in value:
        if not isinstance(item, Mapping):
            raise RouteCandidateSchemaError("add_arcs entries must be mappings")
        arcs.append(
            {
                "net": _require_string(item, "net", "add_arcs.net"),
                "layer": _require_string(item, "layer", "add_arcs.layer"),
                "width": _require_finite_number(item.get("width"), "add_arcs.width"),
                "center": _normalize_point(item.get("center"), "add_arcs.center"),
                "radius": _require_finite_number(item.get("radius"), "add_arcs.radius"),
                "start_angle": _require_finite_number(item.get("start_angle"), "add_arcs.start_angle"),
                "end_angle": _require_finite_number(item.get("end_angle"), "add_arcs.end_angle"),
            }
        )
        _reject_unknown_keys(
            item,
            {"net", "layer", "width", "center", "radius", "start_angle", "end_angle"},
            "add_arcs",
        )
    return tuple(sorted(arcs, key=lambda item: (item["net"], item["layer"], item["center"], item["radius"])))


def _normalize_zones(value: Any) -> tuple[dict[str, Any], ...]:
    if value is None:
        value = []
    if not isinstance(value, (list, tuple)):
        raise RouteCandidateSchemaError("add_zones must be a list")
    zones = []
    for item in value:
        if not isinstance(item, Mapping):
            raise RouteCandidateSchemaError("add_zones entries must be mappings")
        zones.append(
            {
                "net": _require_string(item, "net", "add_zones.net"),
                "layer": _require_string(item, "layer", "add_zones.layer"),
                "outline": _normalize_points(item.get("outline"), "add_zones.outline"),
            }
        )
        _reject_unknown_keys(item, {"net", "layer", "outline"}, "add_zones")
    return tuple(sorted(zones, key=lambda item: (item["net"], item["layer"], item["outline"])))


def _normalize_point(value: Any, field: str) -> tuple[float, float]:
    if isinstance(value, Mapping):
        x = _require_finite_number(value.get("x"), f"{field}.x")
        y = _require_finite_number(value.get("y"), f"{field}.y")
        _reject_unknown_keys(value, {"x", "y"}, field)
        return (x, y)
    if isinstance(value, (list, tuple)) and len(value) == 2:
        x = _require_finite_number(value[0], f"{field}.x")
        y = _require_finite_number(value[1], f"{field}.y")
        return (x, y)
    raise RouteCandidateSchemaError(f"{field} must be a mapping")


def _require_point(value: Any, field: str) -> tuple[float, float]:
    if value is None:
        raise RouteCandidateSchemaError(f"{field} is required")
    return _normalize_point(value, field)


def _normalize_points(value: Any, field: str) -> tuple[tuple[float, float], ...]:
    if not isinstance(value, (list, tuple)):
        raise RouteCandidateSchemaError(f"{field} must be a list")
    return tuple(_normalize_point(point, field) for point in value)


def _require_finite_number(value: Any, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        raise RouteCandidateSchemaError(f"{field} must be finite")
    return float(value)


def _require_string(mapping: Mapping[str, Any], key: str, field: str) -> str:
    if key not in mapping:
        raise RouteCandidateSchemaError(f"{field} is required")
    value = mapping[key]
    if not isinstance(value, str) or not value.strip():
        raise RouteCandidateSchemaError(f"{field} must be a non-empty string")
    return value.strip()


def _require_int(mapping: Mapping[str, Any], key: str, field: str) -> int:
    if key not in mapping:
        raise RouteCandidateSchemaError(f"{field} is required")
    value = mapping[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise RouteCandidateSchemaError(f"{field} must be an integer")
    return value


def _require_mapping(mapping: Mapping[str, Any], key: str, field: str) -> Mapping[str, Any]:
    if key not in mapping:
        raise RouteCandidateSchemaError(f"{field} is required")
    value = mapping[key]
    if not isinstance(value, Mapping):
        raise RouteCandidateSchemaError(f"{field} must be a mapping")
    return value


def _reject_unknown_keys(mapping: Mapping[str, Any], allowed: set[str], field: str) -> None:
    unknown = set(mapping.keys()) - allowed
    if unknown:
        raise RouteCandidateSchemaError(f"unknown {field} field {sorted(unknown)[0]!r}")


def _candidate_sort_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
    return (item["route_group_id"], item["candidate_index"], item["candidate_id"])


def _validate_batch_indices(candidates: list[dict[str, Any]]) -> None:
    expected = 0
    for item in candidates:
        if item["candidate_index"] != expected:
            raise RouteCandidateSchemaError("candidate_index values must be deterministic and dense")
        expected += 1


def _validate_route_plan_link(route_plan_id: str, route_plan_hash: str) -> None:
    if not route_plan_id.startswith("route-plan-"):
        raise RouteCandidateSchemaError("route_plan_id linkage is invalid")
    if not route_plan_hash.startswith("sha256:"):
        raise RouteCandidateSchemaError("route_plan_hash linkage is invalid")
    suffix = route_plan_id.removeprefix("route-plan-")
    digest = route_plan_hash.removeprefix("sha256:")
    if len(suffix) != 8 or not all(ch in "0123456789abcdef" for ch in suffix.lower()):
        raise RouteCandidateSchemaError("route_plan_id linkage is invalid")
    if not digest.startswith(suffix):
        raise RouteCandidateSchemaError("route_plan mismatch")


def _sorted_jsonish(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _sorted_jsonish(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_sorted_jsonish(item) for item in value]
    if isinstance(value, tuple):
        return [_sorted_jsonish(item) for item in value]
    return value


def _to_json_compatible(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _to_json_compatible(value[key]) for key in value}
    if isinstance(value, tuple):
        return [_to_json_compatible(item) for item in value]
    if isinstance(value, list):
        return [_to_json_compatible(item) for item in value]
    return value


def _hash_payload(payload: Mapping[str, Any]) -> str:
    return "sha256:" + sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
