"""Physical design spec loading for Pardal.

The MVP format is YAML-backed and deliberately small: exact placements,
netclasses, and basic board/rule metadata. Routing intent is represented in the
schema but only placement is compiled in the first slice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SOURCE_LOCATION_KEY = "__pdl_source__"
ALLOWED_LAYER_ROLES = {
    "signal",
    "ground_reference",
    "power_plane",
    "analog_quiet",
    "restricted",
}


@dataclass(frozen=True)
class SourceLocation:
    path: Path
    line: int
    column: int = 1

    def display(self) -> str:
        return f"{self.path}:{self.line}"


@dataclass(frozen=True)
class ViaSpec:
    diameter: float
    drill: float


@dataclass(frozen=True)
class NetClassSpec:
    name: str
    width: float
    clearance: float | None = None
    via: ViaSpec | None = None


@dataclass(frozen=True)
class BoardRules:
    default_clearance: float = 0.2
    netclasses: dict[str, NetClassSpec] = field(default_factory=dict)


@dataclass(frozen=True)
class PartPlacement:
    ref: str
    footprint: str
    at: tuple[float, float]
    rotation: float = 0.0
    value: str | None = None


@dataclass(frozen=True)
class FanoutSpec:
    ref: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class RouteIntent:
    raw: dict[str, Any]


@dataclass(frozen=True)
class PlaneIntent:
    net: str
    layer: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PowerStitchIntent:
    raw: dict[str, Any]


@dataclass(frozen=True)
class DfmProfileSpec:
    profile: str
    assembly: str | None = None
    panelization: "PanelizationSpec | None" = None
    required_artifacts: list[str] = field(default_factory=list)
    lcsc_policy: str | None = None
    max_lcsc_exceptions: int | None = None
    lcsc_parts: dict[str, str] = field(default_factory=dict)
    assembly_methods: dict[str, str] = field(default_factory=dict)
    lcsc_exceptions: dict[str, str] = field(default_factory=dict)
    lcsc_alternates: dict[str, tuple[str, ...]] = field(default_factory=dict)
    lcsc_database: dict[str, Any] = field(default_factory=dict)
    lcsc_availability: dict[str, Any] = field(default_factory=dict)
    lcsc_cost: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PanelizationSpec:
    mode: str
    breakaway: str | None = None
    rail_width: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RailBudgetSpec:
    name: str
    nominal_voltage: float | None = None
    min_voltage: float | None = None
    max_voltage: float | None = None
    max_current: float | None = None
    source: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TestPointIntent:
    name: str
    net: str
    at: tuple[float, float] | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FiducialIntent:
    name: str
    at: tuple[float, float]
    diameter: float | None = None
    clearance: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MountingHoleIntent:
    name: str
    at: tuple[float, float]
    diameter: float
    drill: float
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KeepoutIntent:
    name: str
    layer: str
    kind: str
    at: tuple[float, float]
    size: tuple[float, float]
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RouteCorridorLaneIntent:
    name: str
    index: int
    nets: tuple[str, ...]
    pre_points: tuple[Any, ...] = ()
    entry_points: tuple[Any, ...] = ()
    exit_points: tuple[Any, ...] = ()
    run_from_x: float | None = None
    run_to_x: float | None = None
    run_from_y: float | None = None
    run_to_y: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RouteCorridorIntent:
    name: str
    layer: str
    axis: str
    lane_base: float
    lane_pitch: float
    lane_width: float
    clearance: float
    run_from_x: float | None = None
    run_to_x: float | None = None
    run_from_y: float | None = None
    run_to_y: float | None = None
    lanes: dict[str, RouteCorridorLaneIntent] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationTestSpec:
    name: str | None
    kind: str | None
    criteria: str | None
    rail: str | None = None
    net: str | None = None
    interface: str | None = None
    expected: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AtopileSourceSpec:
    project: Path
    ato_yaml: Path
    build: str
    entry: str


@dataclass(frozen=True)
class PhysicalSpec:
    path: Path
    source_netlist: Path | None
    width: float
    height: float
    stackup: str
    copper_layers: list[str] | None
    rules: BoardRules
    parts: dict[str, PartPlacement]
    netclass_assignments: dict[str, list[str]]
    source_format: str = "kicad_sexpr_netlist"
    source_atopile: AtopileSourceSpec | None = None
    footprint_aliases: dict[str, str] = field(default_factory=dict)
    fanouts: dict[str, FanoutSpec] = field(default_factory=dict)
    routes: list[RouteIntent] = field(default_factory=list)
    planes: list[PlaneIntent] = field(default_factory=list)
    power_stitches: list[PowerStitchIntent] = field(default_factory=list)
    dfm: DfmProfileSpec | None = None
    rails: dict[str, RailBudgetSpec] = field(default_factory=dict)
    testpoints: list[TestPointIntent] = field(default_factory=list)
    fiducials: list[FiducialIntent] = field(default_factory=list)
    mounting_holes: list[MountingHoleIntent] = field(default_factory=list)
    validation_tests: list[ValidationTestSpec] = field(default_factory=list)
    keepouts: list[KeepoutIntent] = field(default_factory=list)
    route_corridors: dict[str, RouteCorridorIntent] = field(default_factory=dict)
    layer_roles: dict[str, str] = field(default_factory=dict)
    layer_role_sources: dict[str, SourceLocation] = field(default_factory=dict)
    board_source: SourceLocation | None = None
    copper_layers_source: SourceLocation | None = None


def parse_mm(value: Any, *, field_name: str) -> float:
    """Parse an mm value and reject unitless physical strings."""
    if isinstance(value, int | float):
        raise ValueError(f"{field_name} must include an explicit unit, e.g. 10mm")
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string with mm units")
    text = value.strip()
    if not text.endswith("mm"):
        raise ValueError(f"{field_name} must use mm units, got {value!r}")
    number = text[:-2].strip()
    try:
        return float(number)
    except ValueError as exc:
        raise ValueError(f"{field_name} has invalid mm value {value!r}") from exc


def parse_voltage(value: Any, *, field_name: str) -> float:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string with V or mV units")
    text = value.strip()
    scale = 1.0
    if text.endswith("mV"):
        number = text[:-2].strip()
        scale = 0.001
    elif text.endswith("V"):
        number = text[:-1].strip()
    else:
        raise ValueError(f"{field_name} must use V or mV units, got {value!r}")
    try:
        return float(number) * scale
    except ValueError as exc:
        raise ValueError(f"{field_name} has invalid voltage value {value!r}") from exc


def parse_current(value: Any, *, field_name: str) -> float:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string with A or mA units")
    text = value.strip()
    scale = 1.0
    if text.endswith("mA"):
        number = text[:-2].strip()
        scale = 0.001
    elif text.endswith("A"):
        number = text[:-1].strip()
    else:
        raise ValueError(f"{field_name} must use A or mA units, got {value!r}")
    try:
        return float(number) * scale
    except ValueError as exc:
        raise ValueError(f"{field_name} has invalid current value {value!r}") from exc


def _parse_route_corridor_lanes(
    path: Path,
    name: str,
    axis: str,
    raw: Any,
) -> dict[str, RouteCorridorLaneIntent]:
    lanes = {}
    if raw is None:
        raise ValueError(f"route_corridors.{name}.lanes is required")
    if not isinstance(raw, dict) or not raw:
        raise ValueError(f"route_corridors.{name}.lanes must be a non-empty mapping")

    lane_indexes: set[int] = set()
    assigned_nets: set[str] = set()
    for lane_name, lane_raw in raw.items():
        lane_name = str(lane_name)
        if not isinstance(lane_raw, dict):
            raise ValueError(f"route_corridors.{name}.lanes.{lane_name} must be a mapping")

        if "index" not in lane_raw:
            raise ValueError(f"route_corridors.{name}.lanes.{lane_name}.index is required")
        try:
            index = int(lane_raw["index"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"route_corridors.{name}.lanes.{lane_name}.index must be an integer") from exc
        if index < 0:
            raise ValueError(f"route_corridors.{name}.lanes.{lane_name}.index must be non-negative")
        if index in lane_indexes:
            raise ValueError(f"route_corridors.{name} has duplicate lane index {index}")
        lane_indexes.add(index)

        nets_raw = lane_raw.get("nets")
        if not isinstance(nets_raw, list) or not nets_raw:
            raise ValueError(f"route_corridors.{name}.lanes.{lane_name}.nets must be a non-empty list")

        nets: list[str] = []
        for net in nets_raw:
            if not isinstance(net, str) or not net:
                raise ValueError(f"route_corridors.{name}.lanes.{lane_name}.nets must be non-empty strings")
            if net in assigned_nets:
                raise ValueError(f"route_corridors.{name} has net {net!r} assigned to multiple lanes")
            assigned_nets.add(net)
            nets.append(net)

        run_from_x = run_to_x = run_from_y = run_to_y = None
        if axis == "x":
            if "run_from_y" in lane_raw or "run_to_y" in lane_raw:
                raise ValueError(
                    f"route_corridors.{name}.lanes.{lane_name}.run_from_y/run_to_y "
                    "are only valid for axis y"
                )
            has_from = "run_from_x" in lane_raw
            has_to = "run_to_x" in lane_raw
            if has_from != has_to:
                raise ValueError(
                    f"route_corridors.{name}.lanes.{lane_name}.run_from_x and run_to_x "
                    "must be provided together"
                )
            if has_from:
                run_from_x = parse_mm(
                    lane_raw["run_from_x"],
                    field_name=f"route_corridors.{name}.lanes.{lane_name}.run_from_x",
                )
                run_to_x = parse_mm(
                    lane_raw["run_to_x"],
                    field_name=f"route_corridors.{name}.lanes.{lane_name}.run_to_x",
                )
        else:
            if "run_from_x" in lane_raw or "run_to_x" in lane_raw:
                raise ValueError(
                    f"route_corridors.{name}.lanes.{lane_name}.run_from_x/run_to_x "
                    "are only valid for axis x"
                )
            has_from = "run_from_y" in lane_raw
            has_to = "run_to_y" in lane_raw
            if has_from != has_to:
                raise ValueError(
                    f"route_corridors.{name}.lanes.{lane_name}.run_from_y and run_to_y "
                    "must be provided together"
                )
            if has_from:
                run_from_y = parse_mm(
                    lane_raw["run_from_y"],
                    field_name=f"route_corridors.{name}.lanes.{lane_name}.run_from_y",
                )
                run_to_y = parse_mm(
                    lane_raw["run_to_y"],
                    field_name=f"route_corridors.{name}.lanes.{lane_name}.run_to_y",
                )

        lanes[lane_name] = RouteCorridorLaneIntent(
            name=lane_name,
            index=index,
            nets=tuple(nets),
            pre_points=_parse_corridor_lane_points(
                lane_raw.get("pre_points"),
                field_name=f"route_corridors.{name}.lanes.{lane_name}.pre_points",
            ),
            entry_points=_parse_corridor_lane_points(
                lane_raw.get("entry_points"),
                field_name=f"route_corridors.{name}.lanes.{lane_name}.entry_points",
            ),
            exit_points=_parse_corridor_lane_points(
                lane_raw.get("exit_points"),
                field_name=f"route_corridors.{name}.lanes.{lane_name}.exit_points",
            ),
            run_from_x=run_from_x,
            run_to_x=run_to_x,
            run_from_y=run_from_y,
            run_to_y=run_to_y,
            raw=dict(lane_raw),
        )

    if not lane_indexes:
        raise ValueError(f"route_corridors.{name}.lanes must define at least one lane")
    max_index = max(lane_indexes)
    expected = set(range(max_index + 1))
    if lane_indexes != expected:
        missing = sorted(expected - lane_indexes)
        raise ValueError(f"route_corridors.{name} has missing lane indexes: {missing}")

    return lanes


def _parse_corridor_lane_points(raw: Any, *, field_name: str) -> tuple[Any, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"{field_name} must be a list of route points")

    points: list[Any] = []
    for index, point in enumerate(raw):
        point_field = f"{field_name}[{index}]"
        if isinstance(point, dict) and "via" in point:
            _parse_xy(point.get("via"), field_name=f"{point_field}.via")
            via_to = point.get("to")
            if not isinstance(via_to, str) or not via_to:
                raise ValueError(f"{point_field}.to must be a non-empty layer name")
            if "layers" in point:
                layers = point["layers"]
                if not isinstance(layers, list) or len(layers) < 2:
                    raise ValueError(f"{point_field}.layers must be a list of at least two layers")
                for layer_index, layer in enumerate(layers):
                    if not isinstance(layer, str) or not layer:
                        raise ValueError(f"{point_field}.layers[{layer_index}] must be a non-empty layer name")
            points.append(dict(point))
            continue
        _parse_xy(point, field_name=point_field)
        points.append(point)
    return tuple(points)


def _parse_xy(value: Any, *, field_name: str) -> tuple[float, float]:
    if not isinstance(value, list | tuple) or len(value) != 2:
        raise ValueError(f"{field_name} must be [x, y]")
    return (
        parse_mm(value[0], field_name=f"{field_name}[0]"),
        parse_mm(value[1], field_name=f"{field_name}[1]"),
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to load physical design specs") from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("physical spec root must be a mapping")
    return data


def _parse_lcsc_database_config(dfm_path: Path, dfm_raw: dict[str, Any]) -> dict[str, Any]:
    lcsc_database_raw = dfm_raw.get("lcsc_database")
    if lcsc_database_raw is None:
        return {}

    if not isinstance(lcsc_database_raw, dict):
        raise ValueError("dfm.lcsc_database must be a mapping")

    database_path_raw = lcsc_database_raw.get("path")
    if database_path_raw is None:
        raise ValueError("dfm.lcsc_database.path is required")

    if not isinstance(database_path_raw, str):
        raise ValueError("dfm.lcsc_database.path must be a non-empty string")

    database_path_text = database_path_raw.strip()
    if not database_path_text:
        raise ValueError("dfm.lcsc_database.path must be a non-empty string")

    strict_value = lcsc_database_raw.get("strict", True)
    if not isinstance(strict_value, bool):
        raise ValueError("dfm.lcsc_database.strict must be a boolean")

    return {
        "path": Path(database_path_text),
        "strict": strict_value,
        "source_key": _source_location_for_path(dfm_path, "dfm", "lcsc_database"),
    }


def _parse_lcsc_availability_config(dfm_path: Path, dfm_raw: dict[str, Any]) -> dict[str, Any]:
    lcsc_availability_raw = dfm_raw.get("lcsc_availability")
    if lcsc_availability_raw is None:
        return {}

    if not isinstance(lcsc_availability_raw, dict):
        raise ValueError("dfm.lcsc_availability must be a mapping")

    strict_value = lcsc_availability_raw.get("strict", True)
    if not isinstance(strict_value, bool):
        raise ValueError("dfm.lcsc_availability.strict must be a boolean")

    return {
        "strict": strict_value,
        "source_key": _source_location_for_path(dfm_path, "dfm", "lcsc_availability"),
    }


def _parse_lcsc_cost_config(dfm_path: Path, dfm_raw: dict[str, Any]) -> dict[str, Any]:
    lcsc_cost_raw = dfm_raw.get("lcsc_cost")
    if lcsc_cost_raw is None:
        return {}
    if not isinstance(lcsc_cost_raw, dict):
        raise ValueError("dfm.lcsc_cost must be a mapping")
    batch_quantity = lcsc_cost_raw.get("batch_quantity")
    if not isinstance(batch_quantity, int) or isinstance(batch_quantity, bool):
        raise ValueError("dfm.lcsc_cost.batch_quantity must be a positive integer")
    if batch_quantity <= 0:
        raise ValueError("dfm.lcsc_cost.batch_quantity must be a positive integer")
    return {
        "batch_quantity": batch_quantity,
        "source_key": _source_location_for_path(dfm_path, "dfm", "lcsc_cost"),
    }


def _source_locations_by_name(path: Path, section: str) -> dict[str, SourceLocation]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to load physical design specs") from exc
    root = yaml.compose(path.read_text(encoding="utf-8"))
    result: dict[str, SourceLocation] = {}
    if root is None or not isinstance(root, yaml.MappingNode):
        return result
    for key_node, value_node in root.value:
        if key_node.value != section or not isinstance(value_node, yaml.SequenceNode):
            continue
        for item_node in value_node.value:
            if not isinstance(item_node, yaml.MappingNode):
                continue
            name = None
            for item_key_node, item_value_node in item_node.value:
                if item_key_node.value == "name":
                    name = str(item_value_node.value)
                    break
            if name:
                result.setdefault(
                    name,
                    SourceLocation(
                        path=path,
                        line=item_node.start_mark.line + 1,
                        column=item_node.start_mark.column + 1,
                    ),
                )
    return result


def _source_locations_by_mapping_key(path: Path, section: str) -> dict[str, SourceLocation]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to load physical design specs") from exc
    root = yaml.compose(path.read_text(encoding="utf-8"))
    result: dict[str, SourceLocation] = {}
    if root is None or not isinstance(root, yaml.MappingNode):
        return result
    for key_node, value_node in root.value:
        if key_node.value != section or not isinstance(value_node, yaml.MappingNode):
            continue
        for item_key_node, _item_value_node in value_node.value:
            result.setdefault(
                str(item_key_node.value),
                SourceLocation(
                    path=path,
                    line=item_key_node.start_mark.line + 1,
                    column=item_key_node.start_mark.column + 1,
                ),
            )
    return result


def _source_location_for_path(path: Path, *keys: str) -> SourceLocation | None:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to load physical design specs") from exc
    root = yaml.compose(path.read_text(encoding="utf-8"))
    if root is None:
        return None

    node = root
    for key in keys:
        if not isinstance(node, yaml.MappingNode):
            return None
        next_node = None
        for key_node, value_node in node.value:
            if key_node.value == key:
                next_node = value_node
                break
        if next_node is None:
            return None
        node = next_node

    return SourceLocation(
        path=path,
        line=node.start_mark.line + 1,
        column=node.start_mark.column + 1,
    )


def _annotate_sources(path: Path, section: str, raws: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_locations = _source_locations_by_name(path, section)
    annotated = []
    for raw in raws:
        item = dict(raw)
        name = item.get("name")
        if name in source_locations:
            item[SOURCE_LOCATION_KEY] = source_locations[name]
        annotated.append(item)
    return annotated


def _annotate_mapping_sources(
    path: Path, section: str, raws: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    source_locations = _source_locations_by_mapping_key(path, section)
    annotated = {}
    for name, raw in raws.items():
        item = dict(raw)
        if name in source_locations:
            item[SOURCE_LOCATION_KEY] = source_locations[name]
        annotated[name] = item
    return annotated


def _source_locations_by_index(path: Path, section: str) -> list[SourceLocation]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to load physical design specs") from exc
    root = yaml.compose(path.read_text(encoding="utf-8"))
    result: list[SourceLocation] = []
    if root is None or not isinstance(root, yaml.MappingNode):
        return result
    for key_node, value_node in root.value:
        if key_node.value != section or not isinstance(value_node, yaml.SequenceNode):
            continue
        for item_node in value_node.value:
            result.append(
                SourceLocation(
                    path=path,
                    line=item_node.start_mark.line + 1,
                    column=item_node.start_mark.column + 1,
                )
            )
    return result


def _annotate_sources_by_index(path: Path, section: str, raws: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_locations = _source_locations_by_index(path, section)
    annotated = []
    for index, raw in enumerate(raws):
        item = dict(raw)
        if index < len(source_locations):
            item[SOURCE_LOCATION_KEY] = source_locations[index]
        annotated.append(item)
    return annotated


def load_physical_spec(path: Path) -> PhysicalSpec:
    data = _load_yaml(path)

    source_data = data.get("source") or {}
    if not isinstance(source_data, dict):
        raise ValueError("source must be a mapping")
    source_format = "kicad_sexpr_netlist"
    if "format" in source_data:
        format_raw = source_data.get("format")
        if not isinstance(format_raw, str) or not format_raw.strip():
            raise ValueError("source.format must be a non-empty string when provided")
        source_format = format_raw.strip()
    source_netlist = None
    if source_data.get("netlist"):
        source_netlist = Path(str(source_data["netlist"]))
    source_atopile = None
    if "atopile" in source_data:
        atopile_raw = source_data.get("atopile")
        if not isinstance(atopile_raw, dict):
            raise ValueError("source.atopile must be a mapping")

        def require_nonempty_string(field_name: str) -> str:
            value = atopile_raw.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"source.atopile.{field_name} must be a non-empty string")
            return value.strip()

        source_atopile = AtopileSourceSpec(
            project=Path(require_nonempty_string("project")),
            ato_yaml=Path(require_nonempty_string("ato_yaml")),
            build=require_nonempty_string("build"),
            entry=require_nonempty_string("entry"),
        )

    board_data = data.get("board")
    if not isinstance(board_data, dict):
        raise ValueError("physical spec requires a board mapping")
    width = parse_mm(board_data.get("width"), field_name="board.width")
    height = parse_mm(board_data.get("height"), field_name="board.height")
    stackup = str(board_data.get("stackup", "two_layer"))
    board_source = _source_location_for_path(path, "board")
    copper_layers_source = _source_location_for_path(path, "board", "copper_layers")
    copper_layers = None
    if "copper_layers" in board_data:
        copper_layers_raw = board_data["copper_layers"]
        if not isinstance(copper_layers_raw, list) or not copper_layers_raw:
            raise ValueError("board.copper_layers must be a non-empty list")
        copper_layers = [str(layer) for layer in copper_layers_raw]

    layer_roles_raw = data.get("layer_roles") or {}
    if not isinstance(layer_roles_raw, dict):
        raise ValueError("layer_roles must be a mapping")
    layer_role_sources = _source_locations_by_mapping_key(path, "layer_roles")
    layer_roles = {
        str(layer_name).strip(): (str(role).strip() if role is not None else "")
        for layer_name, role in layer_roles_raw.items()
    }

    rules_data = data.get("rules") or {}
    if not isinstance(rules_data, dict):
        raise ValueError("rules must be a mapping")
    default_clearance = parse_mm(
        rules_data.get("default_clearance", "0.2mm"),
        field_name="rules.default_clearance",
    )
    netclasses = {}
    for name, raw in (rules_data.get("netclasses") or {}).items():
        if not isinstance(raw, dict):
            raise ValueError(f"rules.netclasses.{name} must be a mapping")
        via_raw = raw.get("via") or {}
        via = None
        if via_raw:
            via = ViaSpec(
                diameter=parse_mm(
                    via_raw.get("diameter"),
                    field_name=f"rules.netclasses.{name}.via.diameter",
                ),
                drill=parse_mm(
                    via_raw.get("drill"),
                    field_name=f"rules.netclasses.{name}.via.drill",
                ),
            )
        netclasses[name] = NetClassSpec(
            name=name,
            width=parse_mm(raw.get("width"), field_name=f"rules.netclasses.{name}.width"),
            clearance=(
                parse_mm(raw["clearance"], field_name=f"rules.netclasses.{name}.clearance")
                if "clearance" in raw
                else None
            ),
            via=via,
        )

    parts = {}
    for ref, raw in (data.get("parts") or {}).items():
        if not isinstance(raw, dict):
            raise ValueError(f"parts.{ref} must be a mapping")
        footprint = raw.get("footprint")
        if not isinstance(footprint, str) or not footprint:
            raise ValueError(f"parts.{ref}.footprint is required")
        value_raw = raw.get("value")
        value: str | None = None
        if value_raw is not None:
            if not isinstance(value_raw, str) or not value_raw.strip():
                raise ValueError(f"parts.{ref}.value must be a non-empty string when provided")
            value = value_raw.strip()
        parts[ref] = PartPlacement(
            ref=ref,
            footprint=footprint,
            at=_parse_xy(raw.get("at"), field_name=f"parts.{ref}.at"),
            rotation=float(raw.get("rotation", 0.0)),
            value=value,
        )
    if not parts:
        raise ValueError("physical spec must define at least one part")

    fanouts = {
        str(ref): FanoutSpec(ref=str(ref), raw=dict(raw or {}))
        for ref, raw in (data.get("fanout") or {}).items()
    }
    route_raws = _annotate_sources(path, "routes", [dict(raw) for raw in data.get("routes") or []])
    plane_raws = _annotate_sources(path, "planes", [dict(raw) for raw in data.get("planes") or []])
    power_stitch_raws = _annotate_sources(
        path,
        "power_stitch",
        [dict(raw) for raw in data.get("power_stitch") or []],
    )
    routes = [RouteIntent(raw=raw) for raw in route_raws]
    planes = [
        PlaneIntent(net=str(raw["net"]), layer=str(raw["layer"]), raw=dict(raw))
        for raw in plane_raws
    ]
    power_stitches = [PowerStitchIntent(raw=raw) for raw in power_stitch_raws]
    dfm = None
    dfm_raw = data.get("dfm")
    if dfm_raw is not None:
        if not isinstance(dfm_raw, dict):
            raise ValueError("dfm must be a mapping")
        profile = dfm_raw.get("profile")
        if not isinstance(profile, str) or not profile:
            raise ValueError("dfm.profile is required")
        assembly = dfm_raw.get("assembly")
        panelization = None
        panelization_raw = dfm_raw.get("panelization")
        if panelization_raw is not None:
            if not isinstance(panelization_raw, dict):
                raise ValueError("dfm.panelization must be a mapping")
            mode = panelization_raw.get("mode")
            if not isinstance(mode, str) or not mode.strip():
                raise ValueError("dfm.panelization.mode is required when panelization is provided")
            breakaway = panelization_raw.get("breakaway")
            if breakaway is not None:
                breakaway = str(breakaway).strip() or None
            rail_width = None
            if "rail_width" in panelization_raw:
                rail_width = parse_mm(
                    panelization_raw["rail_width"],
                    field_name="dfm.panelization.rail_width",
                )
            panelization_data = dict(panelization_raw)
            panelization_source = _source_location_for_path(path, "dfm", "panelization")
            if panelization_source is not None:
                panelization_data[SOURCE_LOCATION_KEY] = panelization_source
            panelization = PanelizationSpec(
                mode=mode.strip(),
                breakaway=breakaway,
                rail_width=rail_width,
                raw=panelization_data,
            )
        required_artifacts_raw = dfm_raw.get("required_artifacts") or []
        if not isinstance(required_artifacts_raw, list):
            raise ValueError("dfm.required_artifacts must be a list")
        required_artifacts = []
        for idx, artifact in enumerate(required_artifacts_raw):
            if not isinstance(artifact, str) or not artifact.strip():
                raise ValueError(f"dfm.required_artifacts[{idx}] must be a non-empty string")
            required_artifacts.append(artifact.strip())
        lcsc_policy = dfm_raw.get("lcsc_policy")
        if lcsc_policy is not None:
            lcsc_policy = str(lcsc_policy).strip()
            if lcsc_policy not in {"require_or_exception"}:
                raise ValueError(
                    "dfm.lcsc_policy must be 'require_or_exception' when provided"
                )
        max_lcsc_exceptions = dfm_raw.get("max_lcsc_exceptions")
        if max_lcsc_exceptions is not None:
            if not isinstance(max_lcsc_exceptions, int):
                raise ValueError("dfm.max_lcsc_exceptions must be an integer when provided")
            if max_lcsc_exceptions < 0:
                raise ValueError("dfm.max_lcsc_exceptions must be >= 0")

        lcsc_parts_raw = dfm_raw.get("lcsc_parts") or {}
        if not isinstance(lcsc_parts_raw, dict):
            raise ValueError("dfm.lcsc_parts must be a mapping")
        lcsc_parts: dict[str, str] = {}
        for ref, part_number in lcsc_parts_raw.items():
            ref_text = str(ref).strip()
            part_text = str(part_number).strip()
            if not ref_text:
                raise ValueError("dfm.lcsc_parts contains empty reference key")
            if not part_text:
                raise ValueError(f"dfm.lcsc_parts.{ref_text} must be a non-empty string")
            lcsc_parts[ref_text] = part_text

        assembly_methods_raw = dfm_raw.get("assembly_methods") or {}
        if not isinstance(assembly_methods_raw, dict):
            raise ValueError("dfm.assembly_methods must be a mapping")
        allowed_assembly_methods = {"jlc_smt", "manual_tht", "hand_solder", "do_not_place"}
        assembly_methods: dict[str, str] = {}
        for ref, method in assembly_methods_raw.items():
            ref_text = str(ref).strip()
            method_text = str(method).strip()
            if not ref_text:
                raise ValueError("dfm.assembly_methods contains empty reference key")
            if method_text not in allowed_assembly_methods:
                raise ValueError(
                    f"dfm.assembly_methods.{ref_text} must be one of {sorted(allowed_assembly_methods)}"
                )
            assembly_methods[ref_text] = method_text

        lcsc_exceptions_raw = dfm_raw.get("lcsc_exceptions") or {}
        if not isinstance(lcsc_exceptions_raw, dict):
            raise ValueError("dfm.lcsc_exceptions must be a mapping")
        lcsc_exceptions: dict[str, str] = {}
        for ref, reason in lcsc_exceptions_raw.items():
            ref_text = str(ref).strip()
            reason_text = str(reason).strip()
            if not ref_text:
                raise ValueError("dfm.lcsc_exceptions contains empty reference key")
            if not reason_text:
                raise ValueError(f"dfm.lcsc_exceptions.{ref_text} must be a non-empty reason")
            lcsc_exceptions[ref_text] = reason_text

        lcsc_alternates_raw = dfm_raw.get("lcsc_alternates") or {}
        if not isinstance(lcsc_alternates_raw, dict):
            raise ValueError("dfm.lcsc_alternates must be a mapping")
        lcsc_alternates: dict[str, tuple[str, ...]] = {}
        for ref, alternates_raw in lcsc_alternates_raw.items():
            ref_text = str(ref).strip()
            if not ref_text:
                raise ValueError("dfm.lcsc_alternates contains empty reference key")
            if not isinstance(alternates_raw, list) or not alternates_raw:
                raise ValueError(f"dfm.lcsc_alternates.{ref_text} must be a non-empty list")
            alternates: list[str] = []
            seen_alternates: set[str] = set()
            for index, alternate_raw in enumerate(alternates_raw):
                alternate = str(alternate_raw).strip()
                if not alternate:
                    raise ValueError(
                        f"dfm.lcsc_alternates.{ref_text}[{index}] must be a non-empty string"
                    )
                if alternate in seen_alternates:
                    raise ValueError(
                        f"dfm.lcsc_alternates.{ref_text} contains duplicate alternate {alternate}"
                    )
                seen_alternates.add(alternate)
                alternates.append(alternate)
            lcsc_alternates[ref_text] = tuple(alternates)

        lcsc_database = _parse_lcsc_database_config(path, dfm_raw)
        lcsc_availability = _parse_lcsc_availability_config(path, dfm_raw)
        lcsc_cost = _parse_lcsc_cost_config(path, dfm_raw)
        dfm_data = dict(dfm_raw)
        dfm_source = _source_location_for_path(path, "dfm")
        if dfm_source is not None:
            dfm_data[SOURCE_LOCATION_KEY] = dfm_source
        dfm = DfmProfileSpec(
            profile=profile,
            assembly=str(assembly) if assembly is not None else None,
            panelization=panelization,
            required_artifacts=required_artifacts,
            lcsc_policy=lcsc_policy,
            max_lcsc_exceptions=max_lcsc_exceptions,
            lcsc_parts=lcsc_parts,
            assembly_methods=assembly_methods,
            lcsc_exceptions=lcsc_exceptions,
            lcsc_alternates=lcsc_alternates,
            lcsc_database=lcsc_database,
            lcsc_availability=lcsc_availability,
            lcsc_cost=lcsc_cost,
            raw=dfm_data,
        )

    rail_source = data.get("rails") or {}
    if not isinstance(rail_source, dict):
        raise ValueError("rails must be a mapping")
    rail_raws = _annotate_mapping_sources(
        path,
        "rails",
        {str(name): dict(raw or {}) for name, raw in rail_source.items()},
    )
    rails = {}
    for name, raw in rail_raws.items():
        rails[name] = RailBudgetSpec(
            name=name,
            nominal_voltage=(
                parse_voltage(raw["nominal"], field_name=f"rails.{name}.nominal")
                if "nominal" in raw
                else None
            ),
            min_voltage=(
                parse_voltage(raw["min"], field_name=f"rails.{name}.min")
                if "min" in raw
                else None
            ),
            max_voltage=(
                parse_voltage(raw["max"], field_name=f"rails.{name}.max")
                if "max" in raw
                else None
            ),
            max_current=(
                parse_current(raw["max_current"], field_name=f"rails.{name}.max_current")
                if "max_current" in raw
                else None
            ),
            source=str(raw["source"]) if "source" in raw else None,
            raw=dict(raw),
        )

    testpoint_raws = _annotate_sources(
        path,
        "testpoints",
        [dict(raw) for raw in data.get("testpoints") or []],
    )
    testpoints = []
    for raw in testpoint_raws:
        name = raw.get("name")
        net = raw.get("net")
        if not isinstance(name, str) or not name:
            raise ValueError("testpoints entries require name")
        if not isinstance(net, str) or not net:
            raise ValueError(f"testpoints.{name}.net is required")
        testpoints.append(
            TestPointIntent(
                name=name,
                net=net,
                at=(
                    _parse_xy(raw["at"], field_name=f"testpoints.{name}.at")
                    if "at" in raw
                    else None
                ),
                raw=dict(raw),
            )
        )

    fiducial_raws = _annotate_sources(
        path,
        "fiducials",
        [dict(raw) for raw in data.get("fiducials") or []],
    )
    fiducials = []
    for raw in fiducial_raws:
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("fiducials entries require name")
        fiducials.append(
            FiducialIntent(
                name=name,
                at=_parse_xy(raw.get("at"), field_name=f"fiducials.{name}.at"),
                diameter=(
                    parse_mm(raw["diameter"], field_name=f"fiducials.{name}.diameter")
                    if "diameter" in raw
                    else None
                ),
                clearance=(
                    parse_mm(raw["clearance"], field_name=f"fiducials.{name}.clearance")
                    if "clearance" in raw
                    else None
                ),
                raw=dict(raw),
            )
        )

    mounting_hole_raws = _annotate_sources(
        path,
        "mounting_holes",
        [dict(raw) for raw in data.get("mounting_holes") or []],
    )
    mounting_holes = []
    for raw in mounting_hole_raws:
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("mounting_holes entries require name")
        mounting_holes.append(
            MountingHoleIntent(
                name=name,
                at=_parse_xy(raw.get("at"), field_name=f"mounting_holes.{name}.at"),
                diameter=parse_mm(
                    raw.get("diameter"), field_name=f"mounting_holes.{name}.diameter"
                ),
                drill=parse_mm(raw.get("drill"), field_name=f"mounting_holes.{name}.drill"),
                raw=dict(raw),
            )
        )

    validation_test_raws = _annotate_sources_by_index(
        path,
        "validation_tests",
        [dict(raw or {}) for raw in data.get("validation_tests") or []],
    )
    validation_tests = []
    for index, raw in enumerate(validation_test_raws):
        name_value = raw.get("name")
        kind_value = raw.get("kind")
        criteria_value = raw.get("criteria")
        if name_value is not None and not isinstance(name_value, str):
            raise ValueError(f"validation_tests[{index}].name must be a string when provided")
        if kind_value is not None and not isinstance(kind_value, str):
            raise ValueError(f"validation_tests[{index}].kind must be a string when provided")
        if criteria_value is not None and not isinstance(criteria_value, str):
            raise ValueError(f"validation_tests[{index}].criteria must be a string when provided")
        validation_tests.append(
            ValidationTestSpec(
                name=name_value.strip() if isinstance(name_value, str) else None,
                kind=kind_value.strip() if isinstance(kind_value, str) else None,
                criteria=criteria_value.strip() if isinstance(criteria_value, str) else None,
                rail=str(raw["rail"]).strip() if "rail" in raw and raw["rail"] is not None else None,
                net=str(raw["net"]).strip() if "net" in raw and raw["net"] is not None else None,
                interface=(
                    str(raw["interface"]).strip()
                    if "interface" in raw and raw["interface"] is not None
                    else None
                ),
                expected=(
                    str(raw["expected"]).strip()
                    if "expected" in raw and raw["expected"] is not None
                    else None
                ),
                raw=dict(raw),
            )
        )

    keepout_raws = _annotate_sources(
        path,
        "keepouts",
        [dict(raw) for raw in data.get("keepouts") or []],
    )
    keepouts = []
    for raw in keepout_raws:
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("keepouts entries require name")
        layer = raw.get("layer")
        if not isinstance(layer, str) or not layer:
            raise ValueError(f"keepouts.{name}.layer is required")
        kind = str(raw.get("kind", "route")).strip()
        if kind not in {"route", "copper", "via"}:
            raise ValueError(f"keepouts.{name}.kind must be one of route|copper|via")
        keepouts.append(
            KeepoutIntent(
                name=name,
                layer=layer,
                kind=kind,
                at=_parse_xy(raw.get("at"), field_name=f"keepouts.{name}.at"),
                size=_parse_xy(raw.get("size"), field_name=f"keepouts.{name}.size"),
                raw=dict(raw),
            )
        )

    route_corridor_raws = _annotate_mapping_sources(
        path,
        "route_corridors",
        {
            str(name): dict(raw or {})
            for name, raw in (data.get("route_corridors") or {}).items()
        },
    )
    route_corridors: dict[str, RouteCorridorIntent] = {}
    for name, raw in route_corridor_raws.items():
        if not isinstance(raw, dict):
            raise ValueError(f"route_corridors.{name} must be a mapping")

        layer = raw.get("layer")
        if not isinstance(layer, str) or not layer:
            raise ValueError(f"route_corridors.{name}.layer is required")

        axis = str(raw.get("axis", "x")).strip()
        if axis not in {"x", "y"}:
            raise ValueError(f"route_corridors.{name}.axis must be x or y")

        run_from_x = run_to_x = run_from_y = run_to_y = None
        if axis == "x":
            if "run_from_x" not in raw or "run_to_x" not in raw:
                raise ValueError(f"route_corridors.{name}.run_from_x and run_to_x are required for axis x")
            run_from_x = parse_mm(raw["run_from_x"], field_name=f"route_corridors.{name}.run_from_x")
            run_to_x = parse_mm(raw["run_to_x"], field_name=f"route_corridors.{name}.run_to_x")
        else:
            if "run_from_y" not in raw or "run_to_y" not in raw:
                raise ValueError(f"route_corridors.{name}.run_from_y and run_to_y are required for axis y")
            run_from_y = parse_mm(raw["run_from_y"], field_name=f"route_corridors.{name}.run_from_y")
            run_to_y = parse_mm(raw["run_to_y"], field_name=f"route_corridors.{name}.run_to_y")

        route_corridors[name] = RouteCorridorIntent(
            name=name,
            layer=str(layer),
            axis=axis,
            run_from_x=run_from_x,
            run_to_x=run_to_x,
            run_from_y=run_from_y,
            run_to_y=run_to_y,
            lane_base=parse_mm(raw["lane_base"], field_name=f"route_corridors.{name}.lane_base"),
            lane_pitch=parse_mm(raw["lane_pitch"], field_name=f"route_corridors.{name}.lane_pitch"),
            lane_width=parse_mm(raw["lane_width"], field_name=f"route_corridors.{name}.lane_width"),
            clearance=parse_mm(raw["clearance"], field_name=f"route_corridors.{name}.clearance"),
            lanes=_parse_route_corridor_lanes(path, name, axis, raw.get("lanes")),
            raw=dict(raw),
        )

    return PhysicalSpec(
        path=path,
        source_netlist=source_netlist,
        source_format=source_format,
        source_atopile=source_atopile,
        width=width,
        height=height,
        stackup=stackup,
        copper_layers=copper_layers,
        rules=BoardRules(default_clearance=default_clearance, netclasses=netclasses),
        parts=parts,
        netclass_assignments={
            str(name): [str(net) for net in nets]
            for name, nets in (data.get("netclasses") or {}).items()
        },
        footprint_aliases={
            str(src): str(dst)
            for src, dst in (data.get("footprint_aliases") or {}).items()
        },
        fanouts=fanouts,
        routes=routes,
        planes=planes,
        power_stitches=power_stitches,
        dfm=dfm,
        rails=rails,
        testpoints=testpoints,
        fiducials=fiducials,
        mounting_holes=mounting_holes,
        validation_tests=validation_tests,
        keepouts=keepouts,
        route_corridors=route_corridors,
        layer_roles=layer_roles,
        layer_role_sources=layer_role_sources,
        board_source=board_source,
        copper_layers_source=copper_layers_source,
    )
