"""Pure YAML parser and validator for routes.pdl.yaml source intent."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pardal.physical.spec import SOURCE_LOCATION_KEY, SourceLocation

ROUTES_SCHEMA = "pardal.routes"
ROUTE_SCOPE_MODES = {"hard", "soft"}
REPLACEMENT_MODES = {"scoped", "all", "none", "disabled"}


@dataclass
class RoutingSourceParseError(ValueError):
    message: str
    path: Path | None = None
    line: int | None = None

    def __str__(self) -> str:  # pragma: no cover - string formatting path
        if self.path is None and self.line is None:
            return self.message
        prefix = str(self.path) if self.path is not None else "<memory>"
        if self.line is None:
            return f"{prefix}: {self.message}"
        return f"{prefix}:{self.line}: {self.message}"


@dataclass(frozen=True)
class RouteSourceEnvelope:
    dx: tuple[float, float]
    dy: tuple[float, float]


@dataclass(frozen=True)
class RouteGroupPlacementMove:
    ref: str
    envelope: RouteSourceEnvelope
    rotations: tuple[float, ...]
    required: bool = False
    source: SourceLocation | None = None


@dataclass(frozen=True)
class RouteGroupReplacement:
    mode: str
    nets: tuple[str, ...]
    existing_route_groups: tuple[str, ...] | None
    allow_power: bool
    allow_planes: bool
    max_removed_segments: int | None
    max_removed_vias: int | None
    source: SourceLocation | None = None


@dataclass(frozen=True)
class RoutingScopeKeepout:
    id: str
    mode: str
    source: SourceLocation | None = None


@dataclass(frozen=True)
class RoutingScopeCorridor:
    id: str
    mode: str
    source: SourceLocation | None = None


@dataclass(frozen=True)
class RouteGroup:
    id: str
    name: str | None
    select_nets: tuple[str, ...]
    select_endpoints: tuple[tuple[str, tuple[str, ...]], ...]
    allowed_layers: tuple[str, ...]
    forbidden_layers: tuple[str, ...]
    corridors: tuple[RoutingScopeCorridor, ...]
    keepouts: tuple[RoutingScopeKeepout, ...]
    replacement: RouteGroupReplacement | None
    placement_moves: tuple[RouteGroupPlacementMove, ...]
    variables: tuple["RoutingVariable", ...]
    source: SourceLocation | None = None


@dataclass(frozen=True)
class RoutingVariable:
    name: str
    values: tuple[Any, ...]
    source: SourceLocation | None = None


@dataclass(frozen=True)
class RouteDefaultUnits:
    length: str = "mm"


@dataclass(frozen=True)
class RouteDefaultSearchConstraints:
    candidate_order: str | None = None
    max_candidates: int | None = None


@dataclass(frozen=True)
class RouteDefaultDiagnostics:
    emit_best_failed_candidate: bool = False


@dataclass(frozen=True)
class RoutingDefaults:
    units: RouteDefaultUnits
    search: RouteDefaultSearchConstraints
    diagnostics: RouteDefaultDiagnostics


@dataclass(frozen=True)
class RoutingSource:
    schema: str
    version: str
    board_ir_id: str
    frozen_board_snapshot_id: str
    defaults: RoutingDefaults
    route_groups: tuple[RouteGroup, ...]
    source: Path | None

    def to_json_payload(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "version": self.version,
            "board": {
                "board_ir_id": self.board_ir_id,
                "frozen_board_snapshot_id": self.frozen_board_snapshot_id,
            },
            "defaults": _defaults_to_payload(self.defaults),
            "route_groups": [_route_group_to_payload(route_group) for route_group in self.route_groups],
        }


def parse_routes_source(text: str, *, path: Path | None = None) -> RoutingSource:
    data = _load_yaml_map(text, path)
    if not isinstance(data, dict):
        raise RoutingSourceParseError("routes source root must be a mapping", path=path)

    schema = _require_string(data, "schema", path=path, field="schema")
    if schema != ROUTES_SCHEMA:
        raise RoutingSourceParseError(
            f"unexpected schema {schema!r}; expected {ROUTES_SCHEMA!r}",
            path=path,
        )

    version = _require_version(data, path=path)
    board = _require_mapping(data, "board", path=path)
    board_ir_id = _require_string(board, "board_ir_id", path=path, field="board.board_ir_id")
    frozen_board_snapshot_id = _require_string(
        board,
        "frozen_board_snapshot_id",
        path=path,
        field="board.frozen_board_snapshot_id",
    )
    if not board_ir_id.strip():
        raise RoutingSourceParseError(
            "board.board_ir_id must be a non-empty string",
            path=path,
        )
    if not frozen_board_snapshot_id.strip():
        raise RoutingSourceParseError(
            "board.frozen_board_snapshot_id must be a non-empty string",
            path=path,
        )

    defaults = _parse_defaults(data.get("defaults", {}), path=path)
    route_groups_raw = data.get("route_groups", [])
    if route_groups_raw is None:
        route_groups_raw = []
    if not isinstance(route_groups_raw, list):
        raise RoutingSourceParseError("route_groups must be a list", path=path)

    route_groups = _parse_route_groups(route_groups_raw, path=path)
    return RoutingSource(
        schema=schema,
        version=str(version),
        board_ir_id=board_ir_id,
        frozen_board_snapshot_id=frozen_board_snapshot_id,
        defaults=defaults,
        route_groups=tuple(route_groups),
        source=path,
    )


def load_routes_source(path: str | Path) -> RoutingSource:
    route_path = Path(path)
    return parse_routes_source(route_path.read_text(encoding="utf-8"), path=route_path)


def _load_yaml_map(text: str, path: Path | None) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - environment issue
        raise RuntimeError("PyYAML is required to parse routing DSL source") from exc
    data = yaml.safe_load(text)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise RoutingSourceParseError("routes source root must be a mapping", path=path)
    return data


def _require_string(
    mapping: dict[str, Any],
    key: str,
    *,
    path: Path | None,
    field: str,
) -> str:
    if key not in mapping:
        raise RoutingSourceParseError(f"{field} is required", path=path)
    value = mapping[key]
    if not isinstance(value, str):
        raise RoutingSourceParseError(
            f"{field} must be a non-empty string",
            path=path,
        )
    value_text = value.strip()
    if not value_text:
        raise RoutingSourceParseError(f"{field} must be a non-empty string", path=path)
    return value_text


def _require_version(mapping: dict[str, Any], *, path: Path | None) -> str:
    if "version" not in mapping:
        raise RoutingSourceParseError("version is required", path=path)
    value = mapping["version"]
    if not isinstance(value, str | int | float):
        raise RoutingSourceParseError("version must be scalar (string, int, or float)", path=path)
    return str(value)


def _require_mapping(mapping: dict[str, Any], key: str, *, path: Path | None) -> dict[str, Any]:
    if key not in mapping:
        raise RoutingSourceParseError(f"{key} is required", path=path)
    value = mapping[key]
    if not isinstance(value, dict):
        raise RoutingSourceParseError(f"{key} must be a mapping", path=path)
    return value


def _parse_defaults(raw: Any, *, path: Path | None) -> RoutingDefaults:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise RoutingSourceParseError("defaults must be a mapping", path=path)

    units_raw = raw.get("units", {})
    if units_raw is None:
        units_raw = {}
    if not isinstance(units_raw, dict):
        raise RoutingSourceParseError("defaults.units must be a mapping", path=path)
    length_unit = units_raw.get("length", "mm")
    if not isinstance(length_unit, str) or not length_unit.strip():
        raise RoutingSourceParseError("defaults.units.length must be a non-empty string", path=path)

    search_raw = raw.get("search", {})
    if search_raw is None:
        search_raw = {}
    if not isinstance(search_raw, dict):
        raise RoutingSourceParseError("defaults.search must be a mapping", path=path)
    candidate_order = None
    if "candidate_order" in search_raw and not isinstance(search_raw["candidate_order"], str):
        raise RoutingSourceParseError("defaults.search.candidate_order must be a string", path=path)
    candidate_order_value = search_raw.get("candidate_order")
    if isinstance(candidate_order_value, str):
        candidate_order = candidate_order_value.strip() or None
    max_candidates = None
    if "max_candidates" in search_raw:
        max_candidates = _require_positive_int(search_raw, "max_candidates", path=path, field="defaults.search.max_candidates")

    diagnostics_raw = raw.get("diagnostics", {})
    if diagnostics_raw is None:
        diagnostics_raw = {}
    if not isinstance(diagnostics_raw, dict):
        raise RoutingSourceParseError("defaults.diagnostics must be a mapping", path=path)
    emit_best_failed_candidate = False
    if "emit_best_failed_candidate" in diagnostics_raw:
        flag = diagnostics_raw["emit_best_failed_candidate"]
        if not isinstance(flag, bool):
            raise RoutingSourceParseError(
                "defaults.diagnostics.emit_best_failed_candidate must be boolean",
                path=path,
            )
        emit_best_failed_candidate = flag

    return RoutingDefaults(
        units=RouteDefaultUnits(length=length_unit.strip()),
        search=RouteDefaultSearchConstraints(
            candidate_order=candidate_order,
            max_candidates=max_candidates,
        ),
        diagnostics=RouteDefaultDiagnostics(
            emit_best_failed_candidate=emit_best_failed_candidate,
        ),
    )


def _defaults_to_payload(defaults: RoutingDefaults) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "units": {"length": defaults.units.length},
        "search": {},
        "diagnostics": {},
    }
    if defaults.search.candidate_order is not None:
        payload["search"]["candidate_order"] = defaults.search.candidate_order
    if defaults.search.max_candidates is not None:
        payload["search"]["max_candidates"] = defaults.search.max_candidates
    if defaults.diagnostics.emit_best_failed_candidate:
        payload["diagnostics"]["emit_best_failed_candidate"] = True
    return payload


def _route_group_to_payload(route_group: RouteGroup) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": route_group.id,
        "select": {
            "nets": list(route_group.select_nets),
            "endpoints": [
                {"ref": ref, "pads": list(pads)} for ref, pads in route_group.select_endpoints
            ],
        },
        "scope": {
            "allowed_layers": list(route_group.allowed_layers),
            "forbidden_layers": list(route_group.forbidden_layers),
            "corridors": [_scoped_item_to_payload(item) for item in route_group.corridors],
            "keepouts": [_scoped_item_to_payload(item) for item in route_group.keepouts],
        },
        "placement_moves": [_placement_move_to_payload(move) for move in route_group.placement_moves],
        "variables": {
            variable.name: {"values": list(variable.values)}
            for variable in route_group.variables
        },
    }
    if route_group.name is not None:
        payload["name"] = route_group.name
    if route_group.replacement is not None:
        payload["replacement"] = _replacement_to_payload(route_group.replacement)
    return payload


def _scoped_item_to_payload(item: RoutingScopeKeepout | RoutingScopeCorridor) -> dict[str, Any]:
    return {"id": item.id, "mode": item.mode}


def _placement_move_to_payload(move: RouteGroupPlacementMove) -> dict[str, Any]:
    return {
        "ref": move.ref,
        "envelope": {
            "dx": list(move.envelope.dx),
            "dy": list(move.envelope.dy),
        },
        "rotations": list(move.rotations),
        "required": move.required,
    }


def _replacement_to_payload(replacement: RouteGroupReplacement) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "mode": replacement.mode,
        "nets": list(replacement.nets),
        "allow_power": replacement.allow_power,
        "allow_planes": replacement.allow_planes,
    }
    if replacement.existing_route_groups is not None:
        payload["existing_route_groups"] = list(replacement.existing_route_groups)
    if replacement.max_removed_segments is not None:
        payload["max_removed_segments"] = replacement.max_removed_segments
    if replacement.max_removed_vias is not None:
        payload["max_removed_vias"] = replacement.max_removed_vias
    return payload


def _parse_route_groups(route_groups_raw: list[Any], *, path: Path | None) -> list[RouteGroup]:
    group_locations = _node_locations_by_index(path, "route_groups")
    groups: list[RouteGroup] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(route_groups_raw):
        if not isinstance(raw, dict):
            raise RoutingSourceParseError("each route_group must be a mapping", path=path)
        source = group_locations[index] if index < len(group_locations) else _placeholder_source(path)

        group_id = raw.get("id")
        if not isinstance(group_id, str) or not group_id.strip():
            raise RoutingSourceParseError(
                "missing route-group id",
                path=path,
            )
        group_id = group_id.strip()
        if group_id in seen_ids:
            raise RoutingSourceParseError(f"duplicate route-group id {group_id!r}", path=path)
        seen_ids.add(group_id)

        name = raw.get("name")
        if name is not None and (not isinstance(name, str) or not name.strip()):
            raise RoutingSourceParseError(
                f"route_group[{group_id}].name must be a non-empty string when set",
                path=path,
            )

        select = raw.get("select", {})
        if not isinstance(select, dict):
            raise RoutingSourceParseError(f"route_group[{group_id}].select must be a mapping", path=path)
        select_nets = _parse_string_list(select.get("nets", []), f"route_group[{group_id}].select.nets", path)
        select_endpoints = _parse_endpoints(select.get("endpoints", []), f"route_group[{group_id}].select.endpoints", path)
        scope = raw.get("scope", {})
        if not isinstance(scope, dict):
            raise RoutingSourceParseError(f"route_group[{group_id}].scope must be a mapping", path=path)
        allowed_layers = _parse_string_list(scope.get("allowed_layers", []), f"route_group[{group_id}].scope.allowed_layers", path)
        forbidden_layers = _parse_string_list(scope.get("forbidden_layers", []), f"route_group[{group_id}].scope.forbidden_layers", path)
        corridors = _parse_scoped_items(
            scope.get("corridors", []),
            f"route_group[{group_id}].scope.corridors",
            kind="corridor",
        )
        keepouts = _parse_scoped_items(
            scope.get("keepouts", []),
            f"route_group[{group_id}].scope.keepouts",
            kind="keepout",
        )

        replacement = _parse_replacement(raw.get("replacement"), path=path, group_id=group_id)
        placement_moves = _parse_placement_moves(
            raw.get("placement_moves", []),
            path=path,
            group_id=group_id,
        )
        variables = _parse_variables(raw.get("variables", {}), path=path, group_id=group_id)

        groups.append(
            RouteGroup(
                id=group_id,
                name=str(name).strip() if isinstance(name, str) and name.strip() else None,
                select_nets=tuple(select_nets),
                select_endpoints=tuple(select_endpoints),
                allowed_layers=tuple(allowed_layers),
                forbidden_layers=tuple(forbidden_layers),
                corridors=tuple(corridors),
                keepouts=tuple(keepouts),
                replacement=replacement,
                placement_moves=tuple(placement_moves),
                variables=tuple(variables),
                source=source,
            )
        )
    return groups


def _parse_string_list(value: Any, field: str, path: Path | None) -> list[str]:
    if not isinstance(value, list):
        raise RoutingSourceParseError(f"{field} must be a list", path=path)
    out: list[str] = []
    for index, entry in enumerate(value):
        if not isinstance(entry, str) or not entry.strip():
            raise RoutingSourceParseError(f"{field}[{index}] must be a non-empty string", path=path)
        out.append(entry.strip())
    return out


def _parse_endpoints(value: Any, field: str, path: Path | None) -> list[tuple[str, tuple[str, ...]]]:
    if not isinstance(value, list):
        raise RoutingSourceParseError(f"{field} must be a list", path=path)
    out = []
    for index, entry in enumerate(value):
        if not isinstance(entry, dict):
            raise RoutingSourceParseError(f"{field}[{index}] must be a mapping", path=path)
        ref = entry.get("ref")
        if not isinstance(ref, str) or not ref.strip():
            raise RoutingSourceParseError(f"{field}[{index}].ref must be a non-empty string", path=path)
        pads = entry.get("pads", [])
        if not isinstance(pads, list):
            raise RoutingSourceParseError(f"{field}[{index}].pads must be a list", path=path)
        pad_names = []
        for pad_index, pad_name in enumerate(pads):
            if not isinstance(pad_name, str) or not pad_name.strip():
                raise RoutingSourceParseError(
                    f"{field}[{index}].pads[{pad_index}] must be a non-empty string",
                    path=path,
                )
            pad_names.append(pad_name.strip())
        out.append((ref.strip(), tuple(pad_names)))
    return out


def _parse_scoped_items(
    value: Any,
    field: str,
    *,
    kind: str,
) -> list[RoutingScopeKeepout] | list[RoutingScopeCorridor]:
    if not isinstance(value, list):
        raise RoutingSourceParseError(f"{field} must be a list", path=None)
    result: list[RoutingScopeCorridor | RoutingScopeKeepout] = []
    for index, entry in enumerate(value):
        if not isinstance(entry, dict):
            raise RoutingSourceParseError(f"{field}[{index}] must be a mapping", path=None)
        item_id = entry.get("id")
        if not isinstance(item_id, str) or not item_id.strip():
            raise RoutingSourceParseError(f"{field}[{index}].id must be a non-empty string", path=None)
        mode = entry.get("mode", "hard")
        if not isinstance(mode, str) or mode not in ROUTE_SCOPE_MODES:
            raise RoutingSourceParseError(
                f"{field}[{index}].mode must be one of {sorted(ROUTE_SCOPE_MODES)}",
                path=None,
            )
        item = (
            RoutingScopeCorridor(item_id.strip(), mode.strip())
            if kind == "corridor"
            else RoutingScopeKeepout(item_id.strip(), mode.strip())
        )
        result.append(item)
    return result  # type: ignore[return-value]


def _parse_replacement(
    value: Any,
    *,
    path: Path | None,
    group_id: str,
) -> RouteGroupReplacement | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise RoutingSourceParseError(
            f"route_group[{group_id}].replacement must be a mapping",
            path=path,
        )

    mode = value.get("mode")
    if not isinstance(mode, str) or not mode.strip():
        raise RoutingSourceParseError(
            f"route_group[{group_id}].replacement requires explicit mode",
            path=path,
        )
    mode = mode.strip()
    if mode not in REPLACEMENT_MODES:
        raise RoutingSourceParseError(
            f"route_group[{group_id}].replacement mode must be one of {sorted(REPLACEMENT_MODES)}",
            path=path,
        )

    existing_route_groups = value.get("existing_route_groups")
    parsed_existing: tuple[str, ...] | None = None
    if existing_route_groups is not None:
        parsed_existing = tuple(_parse_string_list(
            existing_route_groups,
            f"route_group[{group_id}].replacement.existing_route_groups",
            path,
        ))
    elif mode == "scoped":
        raise RoutingSourceParseError(
            f"route_group[{group_id}].replacement requires existing_route_groups for mode=scoped",
            path=path,
        )

    nets = tuple(
        _parse_string_list(
            value.get("nets", []),
            f"route_group[{group_id}].replacement.nets",
            path,
        )
    )

    allow_power = bool(value.get("allow_power", False))
    if "allow_power" in value and not isinstance(value["allow_power"], bool):
        raise RoutingSourceParseError(
            f"route_group[{group_id}].replacement.allow_power must be boolean",
            path=path,
        )
    allow_planes = bool(value.get("allow_planes", False))
    if "allow_planes" in value and not isinstance(value["allow_planes"], bool):
        raise RoutingSourceParseError(
            f"route_group[{group_id}].replacement.allow_planes must be boolean",
            path=path,
        )

    max_segments = _optional_positive_int(value, "max_removed_segments", path=path, field=f"route_group[{group_id}].replacement.max_removed_segments")
    max_vias = _optional_positive_int(value, "max_removed_vias", path=path, field=f"route_group[{group_id}].replacement.max_removed_vias")

    return RouteGroupReplacement(
        mode=mode,
        nets=nets,
        existing_route_groups=parsed_existing,
        allow_power=allow_power,
        allow_planes=allow_planes,
        max_removed_segments=max_segments,
        max_removed_vias=max_vias,
    )


def _parse_placement_moves(
    value: Any,
    *,
    path: Path | None,
    group_id: str,
) -> list[RouteGroupPlacementMove]:
    if not isinstance(value, list):
        raise RoutingSourceParseError(
            f"route_group[{group_id}].placement_moves must be a list",
            path=path,
        )
    moves: list[RouteGroupPlacementMove] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise RoutingSourceParseError(
                f"route_group[{group_id}].placement_moves[{index}] must be a mapping",
                path=path,
            )
        ref = item.get("ref")
        if not isinstance(ref, str) or not ref.strip():
            raise RoutingSourceParseError(
                f"route_group[{group_id}].placement_moves[{index}].ref must be a non-empty string",
                path=path,
            )
        envelope_raw = item.get("envelope")
        if not isinstance(envelope_raw, dict):
            raise RoutingSourceParseError(
                f"route_group[{group_id}].placement_moves[{index}] requires finite envelope",
                path=path,
            )
        envelope = _parse_envelope(envelope_raw, path=path, group_id=group_id, index=index)
        rotations = item.get("rotations", [])
        if not isinstance(rotations, list) or not rotations:
            raise RoutingSourceParseError(
                f"route_group[{group_id}].placement_moves[{index}].rotations must be a non-empty list",
                path=path,
            )
        parsed_rotations = []
        for rot_index, rotation_raw in enumerate(rotations):
            if not isinstance(rotation_raw, (int, float)):
                raise RoutingSourceParseError(
                    f"route_group[{group_id}].placement_moves[{index}].rotations[{rot_index}] must be a number",
                    path=path,
                )
            parsed_rotations.append(float(rotation_raw))
        moves.append(
            RouteGroupPlacementMove(
                ref=ref.strip(),
                envelope=envelope,
                rotations=tuple(parsed_rotations),
                required=bool(item.get("required", False)),
            )
        )
    return moves


def _parse_variables(raw: Any, *, path: Path | None, group_id: str) -> list[RoutingVariable]:
    if raw is None:
        return []
    if not isinstance(raw, dict):
        raise RoutingSourceParseError(
            f"route_group[{group_id}].variables must be a mapping",
            path=path,
        )
    variables: list[RoutingVariable] = []
    for var_name, var_raw in raw.items():
        if not isinstance(var_name, str) or not var_name.strip():
            raise RoutingSourceParseError(
                f"route_group[{group_id}].variables has invalid variable name",
                path=path,
            )
        var_name = var_name.strip()
        if not isinstance(var_raw, dict):
            raise RoutingSourceParseError(
                f"route_group[{group_id}].variables[{var_name}] must be a mapping",
                path=path,
            )
        if "values" not in var_raw:
            raise RoutingSourceParseError(
                f"route_group[{group_id}].variables[{var_name}] uses an unbounded variable domain",
                path=path,
            )
        if any(key in var_raw for key in {"min", "max", "start", "end", "step"}):
            raise RoutingSourceParseError(
                f"route_group[{group_id}].variables[{var_name}] uses an unbounded variable domain",
                path=path,
            )
        values_raw = var_raw["values"]
        if not isinstance(values_raw, list) or not values_raw:
            raise RoutingSourceParseError(
                f"route_group[{group_id}].variables[{var_name}].values must be a non-empty list",
                path=path,
            )
        values = [value for value in values_raw]
        variables.append(RoutingVariable(name=var_name, values=tuple(values)))
    return variables


def _parse_envelope(
    raw: Any,
    *,
    path: Path | None,
    group_id: str,
    index: int,
) -> RouteSourceEnvelope:
    dx = raw.get("dx")
    dy = raw.get("dy")
    if dx is None or dy is None:
        raise RoutingSourceParseError(
            f"route_group[{group_id}].placement_moves[{index}].envelope must define dx and dy",
            path=path,
        )

    dx_range = _parse_length_range(dx, f"route_group[{group_id}].placement_moves[{index}].envelope.dx", path)
    dy_range = _parse_length_range(dy, f"route_group[{group_id}].placement_moves[{index}].envelope.dy", path)
    return RouteSourceEnvelope(dx=dx_range, dy=dy_range)


def _parse_length_range(raw: Any, field: str, path: Path | None) -> tuple[float, float]:
    if not isinstance(raw, list) or len(raw) != 2:
        raise RoutingSourceParseError(f"{field} must be a two-value range list", path=path)
    lo = _parse_length(raw[0], field=f"{field}[0]")
    hi = _parse_length(raw[1], field=f"{field}[1]")
    if not (lo <= hi):
        raise RoutingSourceParseError(f"{field}[0] must be <= {field}[1]", path=path)
    if not (float("inf") > lo > float("-inf")) or not (float("inf") > hi > float("-inf")):
        raise RoutingSourceParseError(f"{field} must be finite", path=path)
    return (lo, hi)


def _parse_length(value: Any, *, field: str) -> float:
    if isinstance(value, int | float):
        raise RoutingSourceParseError(f"{field} must include units (for example 1.0mm)")
    if not isinstance(value, str):
        raise RoutingSourceParseError(f"{field} must be a numeric string with mm units")
    text = value.strip()
    if not text:
        raise RoutingSourceParseError(f"{field} must be a non-empty string with mm units")
    if not text.endswith("mm"):
        raise RoutingSourceParseError(f"{field} must use explicit length units (for example 1.0mm)")
    try:
        parsed = float(text[:-2].strip())
    except ValueError as exc:
        raise RoutingSourceParseError(f"{field} has invalid length {value!r}") from exc
    if not float("-inf") < parsed < float("inf"):
        raise RoutingSourceParseError(f"{field} must be finite")
    return parsed


def _require_positive_int(
    mapping: dict[str, Any],
    key: str,
    *,
    path: Path | None,
    field: str,
) -> int:
    value = mapping.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise RoutingSourceParseError(f"{field} must be an integer", path=path)
    if value <= 0:
        raise RoutingSourceParseError(f"{field} must be positive", path=path)
    return value


def _optional_positive_int(
    mapping: dict[str, Any],
    key: str,
    *,
    path: Path | None,
    field: str,
) -> int | None:
    if key not in mapping:
        return None
    return _require_positive_int(mapping, key, path=path, field=field)


def _node_locations_by_index(path: Path | None, section: str) -> list[SourceLocation]:
    if path is None:
        return []
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - environment issue
        raise RuntimeError("PyYAML is required to load routing DSL source") from exc
    root = yaml.compose(path.read_text(encoding="utf-8"))
    if root is None or not isinstance(root, yaml.MappingNode):
        return []
    for key_node, value_node in root.value:
        if key_node.value == section and isinstance(value_node, yaml.SequenceNode):
            return [
                SourceLocation(path=path, line=item_node.start_mark.line + 1, column=1)
                for item_node in value_node.value
                if isinstance(item_node, yaml.MappingNode)
            ]
    return []


def _placeholder_source(path: Path | None) -> SourceLocation:
    if path is None:
        return SourceLocation(path=Path("<memory>"), line=1, column=1)
    return SourceLocation(path=path, line=1, column=1)
