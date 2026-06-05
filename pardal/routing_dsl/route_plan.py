"""Deterministic resolver from routes source intent to route-plan IR."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import itertools
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from .board_ir import FrozenBoardIR, load_board_ir
from .source import (
    RouteGroup,
    RouteGroupPlacementMove,
    RouteGroupReplacement,
    RoutingDefaults,
    RoutingSource,
    RoutingSourceParseError,
    load_routes_source,
)


ROUTE_PLAN_SCHEMA = "pardal.route_plan"
ROUTE_PLAN_VERSION = "0.1"


@dataclass(frozen=True)
class RoutePlanResolutionError(ValueError):
    message: str
    path: Path | None = None

    def __str__(self) -> str:  # pragma: no cover - formatting only
        if self.path is None:
            return self.message
        return f"{self.path}: {self.message}"


def load_route_plan(
    routes_source: str | Path | RoutingSource | Mapping[str, Any],
    board_ir: str | Path | FrozenBoardIR | Mapping[str, Any],
) -> dict[str, Any]:
    source = _load_routes_source(routes_source)
    board = _load_board_ir(board_ir)
    return resolve_route_plan(source, board)


def normalize_route_plan_payload(payload: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    if isinstance(payload, (str, Path)):
        payload = json.loads(Path(payload).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise RoutePlanResolutionError("route plan payload must be a mapping")

    route_plan = json.loads(json.dumps(dict(payload), sort_keys=True, ensure_ascii=True))
    route_plan["route_groups"] = [
        _normalize_route_group_payload(group) for group in route_plan.get("route_groups", [])
    ]
    route_plan["defaults"] = _normalize_defaults_payload(route_plan.get("defaults", {}))
    route_plan["source"] = _normalize_source_payload(route_plan.get("source", {}))
    if "route_plan_hash" not in route_plan or "route_plan_id" not in route_plan:
        digest = _hash_payload_json(_route_plan_hash_payload(route_plan))
        route_plan["route_plan_hash"] = f"sha256:{digest}"
        route_plan["route_plan_id"] = f"route-plan-{digest[:8]}"
    return route_plan


def route_plan_hash_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = normalize_route_plan_payload(payload)
    return _route_plan_hash_payload(normalized)


def resolve_route_plan(routes_source: RoutingSource | Mapping[str, Any], board_ir: FrozenBoardIR | Mapping[str, Any]) -> dict[str, Any]:
    source = _coerce_routes_source(routes_source)
    board = _coerce_board_ir(board_ir)

    if source.board_ir_id != board.board_ir_id:
        raise RoutePlanResolutionError(
            f"routes source board_ir_id {source.board_ir_id!r} does not match board_ir {board.board_ir_id!r}"
        )
    if source.frozen_board_snapshot_id != board.frozen_board_snapshot_id:
        raise RoutePlanResolutionError(
            "routes source frozen_board_snapshot_id does not match board_ir snapshot"
        )

    board_layers = {layer.name: layer for layer in board.stackup}
    board_nets = {net.name: net for net in board.nets}
    board_components = {component.refdes: component for component in board.components}
    board_pads = {pad.id: pad for pad in board.pads}
    board_obstacles = {obstacle.id: obstacle for obstacle in board.obstacles}

    resolved_groups: list[dict[str, Any]] = []
    seen_output_ids: set[str] = set()
    candidate_limit = _candidate_limit(source.defaults.search.max_candidates)

    for group_index, group in enumerate(source.route_groups):
        resolved = _resolve_group(
            group,
            group_index=group_index,
            source=source,
            board=board,
            board_layers=board_layers,
            board_nets=board_nets,
            board_components=board_components,
            board_pads=board_pads,
            board_obstacles=board_obstacles,
            candidate_limit=candidate_limit,
        )
        output_id = resolved["route_group_output_id"]
        if output_id in seen_output_ids:
            raise RoutePlanResolutionError(f"duplicate route plan output id {output_id!r}")
        seen_output_ids.add(output_id)
        resolved_groups.append(resolved)

    payload = {
        "schema": ROUTE_PLAN_SCHEMA,
        "version": ROUTE_PLAN_VERSION,
        "board_ir_id": board.board_ir_id,
        "frozen_board_snapshot_id": board.frozen_board_snapshot_id,
        "defaults": _defaults_payload(source.defaults),
        "route_groups": resolved_groups,
        "source": {
            "schema": source.schema,
            "version": source.version,
            "path": str(source.source) if source.source is not None else "",
        },
    }
    route_plan_digest = _hash_payload_json(_route_plan_hash_payload(payload))
    payload["route_plan_hash"] = f"sha256:{route_plan_digest}"
    payload["route_plan_id"] = f"route-plan-{route_plan_digest[:8]}"
    return payload


def _load_routes_source(value: str | Path | RoutingSource | Mapping[str, Any]) -> RoutingSource:
    if isinstance(value, RoutingSource):
        return value
    if isinstance(value, Mapping):
        return _coerce_routes_source(value)
    return load_routes_source(value)


def _load_board_ir(value: str | Path | FrozenBoardIR | Mapping[str, Any]) -> FrozenBoardIR:
    if isinstance(value, FrozenBoardIR):
        return value
    if isinstance(value, Mapping):
        return load_board_ir(value)
    return load_board_ir(value)


def _coerce_routes_source(value: RoutingSource | Mapping[str, Any]) -> RoutingSource:
    if isinstance(value, RoutingSource):
        return value
    raise RoutePlanResolutionError("resolve_route_plan requires a parsed RoutingSource")


def _coerce_board_ir(value: FrozenBoardIR | Mapping[str, Any]) -> FrozenBoardIR:
    if isinstance(value, FrozenBoardIR):
        return value
    raise RoutePlanResolutionError("resolve_route_plan requires a parsed FrozenBoardIR")


def _resolve_group(
    group: RouteGroup,
    *,
    group_index: int,
    source: RoutingSource,
    board: FrozenBoardIR,
    board_layers: Mapping[str, Any],
    board_nets: Mapping[str, Any],
    board_components: Mapping[str, Any],
    board_pads: Mapping[str, Any],
    board_obstacles: Mapping[str, Any],
    candidate_limit: int,
) -> dict[str, Any]:
    resolved_nets = []
    for net_name in group.select_nets:
        net = board_nets.get(net_name)
        if net is None:
            raise RoutePlanResolutionError(
                f"route_group {group.id!r} references unknown net {net_name!r}"
            )
        resolved_nets.append({"id": net.id, "name": net.name})

    resolved_endpoints = []
    endpoint_ids: list[str] = []
    for ref, pad_names in group.select_endpoints:
        component = board_components.get(ref)
        if component is None:
            raise RoutePlanResolutionError(
                f"route_group {group.id!r} references unknown endpoint ref {ref!r}"
            )
        endpoint_pads = []
        for pad_name in pad_names:
            pad = _resolve_pad_selector(ref, pad_name, board_pads)
            if pad is None:
                raise RoutePlanResolutionError(
                    f"route_group {group.id!r} references unknown pad {pad_name!r} for {ref!r}"
                )
            endpoint_pads.append(_pad_payload(pad))
            endpoint_ids.append(pad.id)
        resolved_endpoints.append(
            {
                "ref": component.refdes,
                "component_id": component.id,
                "pads": endpoint_pads,
            }
        )

    allowed_layers = _resolve_layers(group.allowed_layers, board_layers, group.id, "allowed_layers")
    forbidden_layers = _resolve_layers(group.forbidden_layers, board_layers, group.id, "forbidden_layers")
    corridor_refs = _resolve_obstacle_refs(group.corridors, board_obstacles, group.id, "corridors")
    keepout_refs = _resolve_obstacle_refs(group.keepouts, board_obstacles, group.id, "keepouts")
    replacement = _resolve_replacement(group.replacement, group.id, source, board)
    placement_moves = [_resolve_placement_move(move, board_components, board, group.id) for move in group.placement_moves]
    variables = _resolve_variables(group.variables, group.id)

    candidates = list(_expand_candidates(variables, candidate_limit, group.id))

    source_span = _source_span(group.source)
    route_group_output_id = f"{source.board_ir_id}:{group.id}"
    route_group_payload = {
        "route_group_id": group.id,
        "route_group_output_id": route_group_output_id,
        "source_route_group_name": group.name or "",
        "source_span": source_span,
        "index": group_index,
        "select": {
            "nets": resolved_nets,
            "endpoints": resolved_endpoints,
        },
        "scope": {
            "allowed_layers": allowed_layers,
            "forbidden_layers": forbidden_layers,
            "corridors": corridor_refs,
            "keepouts": keepout_refs,
        },
        "replacement": replacement,
        "placement_moves": placement_moves,
        "variables": variables,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    route_group_payload["assignment_hash"] = _hash_payload(
        {
            "route_group_id": group.id,
            "candidates": candidates,
        }
    )
    return route_group_payload


def _resolve_pad_selector(
    ref: str,
    pad_name: str,
    board_pads: Mapping[str, Any],
) -> Any | None:
    if pad_name in board_pads:
        pad = board_pads[pad_name]
        if pad.component_id == _component_id_from_ref(ref):
            return pad
    candidate_id = f"pad-{ref.lower()}-{pad_name.lower()}"
    if candidate_id in board_pads:
        return board_pads[candidate_id]
    return None


def _component_id_from_ref(ref: str) -> str:
    return f"comp-{ref.lower()}"


def _pad_payload(pad: Any) -> dict[str, Any]:
    return {
        "id": pad.id,
        "component_id": pad.component_id,
        "net_id": pad.net_id or "",
        "layer": pad.layer,
        "kind": pad.kind,
        "position": {"x": pad.position[0], "y": pad.position[1]},
    }


def _resolve_layers(values: Sequence[str], board_layers: Mapping[str, Any], group_id: str, field: str) -> list[dict[str, Any]]:
    resolved = []
    for value in values:
        layer = board_layers.get(value)
        if layer is None:
            raise RoutePlanResolutionError(f"route_group {group_id!r} references unknown layer {value!r} in {field}")
        resolved.append({"id": layer.id, "name": layer.name, "kind": layer.kind, "order": layer.order})
    return resolved


def _resolve_obstacle_refs(
    values: Sequence[Any],
    board_obstacles: Mapping[str, Any],
    group_id: str,
    field: str,
) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for item in values:
        obstacle = board_obstacles.get(item.id)
        if obstacle is None:
            raise RoutePlanResolutionError(
                f"route_group {group_id!r} references unknown obstacle {item.id!r} in {field}"
            )
        resolved.append(
            {
                "id": obstacle.id,
                "kind": obstacle.kind,
                "layer": obstacle.layer,
                "mode": item.mode,
                "source_span": _source_span(item.source),
            }
        )
    return resolved


def _resolve_replacement(
    replacement: RouteGroupReplacement | None,
    group_id: str,
    source: RoutingSource,
    board: FrozenBoardIR,
) -> dict[str, Any] | None:
    if replacement is None:
        return None
    resolved_nets = []
    board_net_names = {net.name for net in board.nets}
    for net_name in replacement.nets:
        if net_name not in board_net_names:
            raise RoutePlanResolutionError(
                f"route_group {group_id!r} references unknown replacement net {net_name!r}"
            )
        resolved_nets.append(net_name)
    return {
        "mode": replacement.mode,
        "nets": resolved_nets,
        "existing_route_groups": list(replacement.existing_route_groups or []),
        "allow_power": replacement.allow_power,
        "allow_planes": replacement.allow_planes,
        "max_removed_segments": replacement.max_removed_segments,
        "max_removed_vias": replacement.max_removed_vias,
        "source_span": _source_span(replacement.source),
    }


def _resolve_placement_move(
    move: RouteGroupPlacementMove,
    board_components: Mapping[str, Any],
    board: FrozenBoardIR,
    group_id: str,
) -> dict[str, Any]:
    component = board_components.get(move.ref)
    if component is None:
        raise RoutePlanResolutionError(f"route_group {group_id!r} references unknown placement ref {move.ref!r}")
    envelope = move.envelope
    dx = _finite_pair(envelope.dx, f"route_group {group_id!r} placement envelope dx")
    dy = _finite_pair(envelope.dy, f"route_group {group_id!r} placement envelope dy")
    return {
        "ref": component.refdes,
        "component_id": component.id,
        "envelope": {"dx": dx, "dy": dy},
        "rotations": _finite_numbers(move.rotations, f"route_group {group_id!r} placement rotations"),
        "required": move.required,
        "source_span": _source_span(move.source),
    }


def _resolve_variables(variables: Sequence[Any], group_id: str) -> list[dict[str, Any]]:
    resolved = []
    for variable in sorted(variables, key=lambda item: item.name):
        values = _resolve_variable_values(variable.values, group_id, variable.name)
        if not values:
            raise RoutePlanResolutionError(f"route_group {group_id!r} variable {variable.name!r} has no values")
        resolved.append({"name": variable.name, "values": values, "source_span": _source_span(variable.source)})
    return resolved


def _resolve_variable_values(values: Sequence[Any], group_id: str, variable_name: str) -> list[Any]:
    resolved: list[Any] = []
    for value in values:
        resolved.append(_sanitize_value(value, group_id, variable_name))
    return resolved


def _sanitize_value(value: Any, group_id: str, variable_name: str) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise RoutePlanResolutionError(
                f"route_group {group_id!r} variable {variable_name!r} contains non-finite value"
            )
        return float(value) if isinstance(value, float) else int(value)
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return [_sanitize_value(item, group_id, variable_name) for item in value]
    if isinstance(value, dict):
        return {str(k): _sanitize_value(v, group_id, variable_name) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    raise RoutePlanResolutionError(
        f"route_group {group_id!r} variable {variable_name!r} contains unsupported value type {type(value).__name__}"
    )


def _expand_candidates(variables: Sequence[dict[str, Any]], candidate_limit: int, group_id: str) -> list[dict[str, Any]]:
    total = 1
    for variable in variables:
        total *= len(variable["values"])
        if total > candidate_limit:
            raise RoutePlanResolutionError(
                f"route_group {group_id!r} candidate count exceeds cap {candidate_limit}"
            )
    if not variables:
        assignment = {}
        return [
            {
                "candidate_index": 0,
                "assignment": assignment,
                "assignment_hash": _hash_payload(assignment),
            }
        ]

    names = [variable["name"] for variable in variables]
    value_sets = [variable["values"] for variable in variables]
    candidates: list[dict[str, Any]] = []
    for candidate_index, combination in enumerate(itertools.product(*value_sets)):
        assignment = {name: value for name, value in zip(names, combination)}
        candidates.append(
            {
                "candidate_index": candidate_index,
                "assignment": assignment,
                "assignment_hash": _hash_payload(assignment),
            }
        )
    return candidates


def _candidate_limit(value: int | None) -> int:
    if value is None:
        return 512
    if value <= 0:
        raise RoutePlanResolutionError("defaults.search.max_candidates must be positive")
    return value


def _finite_pair(values: Sequence[Any], field: str) -> tuple[float, float]:
    if len(values) != 2:
        raise RoutePlanResolutionError(f"{field} must contain exactly 2 values")
    first, second = values
    return (_finite_number(first, field), _finite_number(second, field))


def _finite_numbers(values: Sequence[Any], field: str) -> tuple[float, ...]:
    return tuple(_finite_number(value, field) for value in values)


def _finite_number(value: Any, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise RoutePlanResolutionError(f"{field} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise RoutePlanResolutionError(f"{field} must be finite")
    return numeric


def _defaults_payload(defaults: RoutingDefaults) -> dict[str, Any]:
    return {
        "units": {"length": defaults.units.length},
        "search": {
            "candidate_order": defaults.search.candidate_order or "",
            "max_candidates": defaults.search.max_candidates,
        },
        "diagnostics": {
            "emit_best_failed_candidate": defaults.diagnostics.emit_best_failed_candidate,
        },
    }


def _source_span(source: Any) -> dict[str, Any]:
    if source is None:
        return {}
    if hasattr(source, "path") and hasattr(source, "line"):
        source_path = Path(str(getattr(source, "path")))
        payload = {"path": source_path.name, "line": int(getattr(source, "line"))}
        column = getattr(source, "column", None)
        if isinstance(column, int):
            payload["column"] = column
        return payload
    return {}


def _hash_payload(payload: Any) -> str:
    return _hash_text(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True))


def _hash_text(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()[:12]


def _hash_payload_json(payload: Any) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()


def _route_plan_hash_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    normalized.pop("route_plan_hash", None)
    normalized.pop("route_plan_id", None)
    return normalized


def _normalize_defaults_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {"units": {}, "search": {}, "diagnostics": {}}
    return {
        "units": dict(payload.get("units", {})),
        "search": dict(payload.get("search", {})),
        "diagnostics": dict(payload.get("diagnostics", {})),
    }


def _normalize_source_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    return {
        "schema": str(payload.get("schema", "")),
        "version": str(payload.get("version", "")),
        "path": str(payload.get("path", "")),
    }


def _normalize_route_group_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    group = json.loads(json.dumps(dict(payload), sort_keys=True, ensure_ascii=True))
    group.setdefault("placement_moves", [])
    group.setdefault("variables", [])
    return group
