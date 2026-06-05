"""Frozen board IR loader and validator for routing DSL geometry."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
import json
import math


BOARD_IR_SCHEMA = "pardal.board_ir"
BOARD_IR_VERSION = "0.1"

_VALID_LAYER_TYPES = {"signal", "plane", "mechanical", "keepout"}
_VALID_PAD_KINDS = {"thru_hole", "smd", "npth"}
_VALID_OBSTACLE_KINDS = {"keepout", "mechanical", "courtyard"}
_VALID_ENVELOPE_KINDS = {"placement", "route"}


@dataclass(frozen=True, slots=True)
class BoardLayer:
    id: str
    name: str
    kind: str
    order: int


@dataclass(frozen=True, slots=True)
class BoardNet:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class BoardPad:
    id: str
    component_id: str
    net_id: str | None
    layer: str
    kind: str
    position: tuple[float, float]


@dataclass(frozen=True, slots=True)
class BoardObstacle:
    id: str
    kind: str
    layer: str
    shape: dict[str, Any]


@dataclass(frozen=True, slots=True)
class BoardEnvelope:
    id: str
    kind: str
    ref_id: str | None
    shape: dict[str, Any]


@dataclass(frozen=True, slots=True)
class BoardComponent:
    id: str
    refdes: str
    footprint: str
    layer: str
    position: tuple[float, float]
    rotation: float


@dataclass(frozen=True, slots=True)
class FrozenBoardIR:
    board_ir_id: str
    frozen_board_snapshot_id: str
    units: dict[str, str]
    outline: list[tuple[float, float]]
    bounds: dict[str, float]
    stackup: list[BoardLayer]
    nets: list[BoardNet]
    components: list[BoardComponent]
    pads: list[BoardPad]
    obstacles: list[BoardObstacle]
    envelopes: list[BoardEnvelope]
    provenance: dict[str, Any]
    route_plan_anchor_ids: list[str]

    def to_json_payload(self) -> dict[str, Any]:
        return {
            "schema": BOARD_IR_SCHEMA,
            "version": BOARD_IR_VERSION,
            "board_ir_id": self.board_ir_id,
            "frozen_board_snapshot_id": self.frozen_board_snapshot_id,
            "units": dict(self.units),
            "outline": [{"x": x, "y": y} for x, y in self.outline],
            "bounds": dict(self.bounds),
            "stackup": [
                {"id": layer.id, "name": layer.name, "kind": layer.kind, "order": layer.order}
                for layer in self.stackup
            ],
            "nets": [{"id": net.id, "name": net.name} for net in self.nets],
            "components": [
                {
                    "id": component.id,
                    "refdes": component.refdes,
                    "footprint": component.footprint,
                    "layer": component.layer,
                    "position": {"x": component.position[0], "y": component.position[1]},
                    "rotation": component.rotation,
                }
                for component in self.components
            ],
            "pads": [
                {
                    "id": pad.id,
                    "component_id": pad.component_id,
                    "net_id": pad.net_id,
                    "layer": pad.layer,
                    "kind": pad.kind,
                    "position": {"x": pad.position[0], "y": pad.position[1]},
                }
                for pad in self.pads
            ],
            "obstacles": [
                {"id": obstacle.id, "kind": obstacle.kind, "layer": obstacle.layer, "shape": dict(obstacle.shape)}
                for obstacle in self.obstacles
            ],
            "envelopes": [
                {
                    "id": envelope.id,
                    "kind": envelope.kind,
                    "ref_id": envelope.ref_id,
                    "shape": dict(envelope.shape),
                }
                for envelope in self.envelopes
            ],
            "provenance": dict(self.provenance),
            "route_plan_anchor_ids": list(self.route_plan_anchor_ids),
        }


class BoardIRValidationError(ValueError):
    pass


def load_board_ir(source: str | Path | Mapping[str, Any]) -> FrozenBoardIR:
    payload = _load_payload(source)
    return _validate_board_ir(payload)


def _load_payload(source: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(source, Mapping):
        return dict(source)
    path = Path(source)
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_board_ir(payload: Mapping[str, Any]) -> FrozenBoardIR:
    _require(payload.get("schema") == BOARD_IR_SCHEMA, "schema must be pardal.board_ir")
    _require(payload.get("version") == BOARD_IR_VERSION, "version must be 0.1")
    board_ir_id = _require_string(payload, "board_ir_id")
    snapshot_id = _require_string(payload, "frozen_board_snapshot_id")
    units = _require_mapping(payload.get("units"), "units")
    length_unit = _require_string(units, "length")
    angle_unit = _require_string(units, "angle")
    _require(length_unit in {"mm", "mil"}, "units.length must be mm or mil")
    _require(angle_unit in {"deg", "rad"}, "units.angle must be deg or rad")

    outline = _parse_point_list(payload, "outline")
    bounds = _parse_bounds(payload, "bounds")
    stackup = [_parse_layer(item) for item in _require_list(payload, "stackup")]
    nets = [_parse_net(item) for item in _require_list(payload, "nets")]
    components = [_parse_component(item) for item in _require_list(payload, "components")]
    pads = [_parse_pad(item) for item in _require_list(payload, "pads")]
    obstacles = [_parse_obstacle(item) for item in _require_list(payload, "obstacles")]
    envelopes = [_parse_envelope(item) for item in _require_list(payload, "envelopes")]
    provenance = _require_mapping(payload.get("provenance"), "provenance")
    route_plan_anchor_ids = [_require_string_item(item, "route_plan_anchor_ids") for item in _require_list(payload, "route_plan_anchor_ids")]

    ids: dict[str, str] = {}
    for label, items in (
        ("layer", stackup),
        ("net", nets),
        ("component", components),
        ("pad", pads),
        ("obstacle", obstacles),
        ("envelope", envelopes),
    ):
        for item in items:
            _register_id(ids, label, item.id)

    layer_names = {layer.name for layer in stackup}
    component_ids = {component.id for component in components}
    net_ids = {net.id for net in nets}
    for pad in pads:
        _require(pad.component_id in component_ids, f"pad {pad.id} references unknown component")
        _require(pad.layer in layer_names, f"pad {pad.id} references unknown layer")
        if pad.net_id is not None:
            _require(pad.net_id in net_ids, f"pad {pad.id} references unknown net")
    for obstacle in obstacles:
        _require(obstacle.layer in layer_names, f"obstacle {obstacle.id} references unknown layer")
    for envelope in envelopes:
        if envelope.ref_id is not None:
            _require(
                envelope.ref_id in component_ids or envelope.ref_id in {pad.id for pad in pads},
                f"envelope {envelope.id} references unknown object",
            )

    return FrozenBoardIR(
        board_ir_id=board_ir_id,
        frozen_board_snapshot_id=snapshot_id,
        units={"length": length_unit, "angle": angle_unit},
        outline=outline,
        bounds=bounds,
        stackup=stackup,
        nets=nets,
        components=components,
        pads=pads,
        obstacles=obstacles,
        envelopes=envelopes,
        provenance=dict(provenance),
        route_plan_anchor_ids=route_plan_anchor_ids,
    )


def _parse_layer(item: Any) -> BoardLayer:
    mapping = _require_mapping(item, "stackup item")
    kind = _require_string(mapping, "kind")
    _require(kind in _VALID_LAYER_TYPES, f"invalid layer kind {kind!r}")
    return BoardLayer(
        id=_require_string(mapping, "id"),
        name=_require_string(mapping, "name"),
        kind=kind,
        order=_require_int(mapping, "order"),
    )


def _parse_net(item: Any) -> BoardNet:
    mapping = _require_mapping(item, "net")
    return BoardNet(id=_require_string(mapping, "id"), name=_require_string(mapping, "name"))


def _parse_component(item: Any) -> BoardComponent:
    mapping = _require_mapping(item, "component")
    position = _parse_xy(mapping.get("position"), "position")
    rotation = _parse_number(mapping, "rotation")
    return BoardComponent(
        id=_require_string(mapping, "id"),
        refdes=_require_string(mapping, "refdes"),
        footprint=_require_string(mapping, "footprint"),
        layer=_require_string(mapping, "layer"),
        position=position,
        rotation=rotation,
    )


def _parse_pad(item: Any) -> BoardPad:
    mapping = _require_mapping(item, "pad")
    kind = _require_string(mapping, "kind")
    _require(kind in _VALID_PAD_KINDS, f"invalid pad kind {kind!r}")
    return BoardPad(
        id=_require_string(mapping, "id"),
        component_id=_require_string(mapping, "component_id"),
        net_id=_optional_string(mapping, "net_id"),
        layer=_require_string(mapping, "layer"),
        kind=kind,
        position=_parse_xy(mapping.get("position"), "position"),
    )


def _parse_obstacle(item: Any) -> BoardObstacle:
    mapping = _require_mapping(item, "obstacle")
    kind = _require_string(mapping, "kind")
    _require(kind in _VALID_OBSTACLE_KINDS, f"invalid obstacle kind {kind!r}")
    return BoardObstacle(
        id=_require_string(mapping, "id"),
        kind=kind,
        layer=_require_string(mapping, "layer"),
        shape=_require_mapping(mapping, "shape"),
    )


def _parse_envelope(item: Any) -> BoardEnvelope:
    mapping = _require_mapping(item, "envelope")
    kind = _require_string(mapping, "kind")
    _require(kind in _VALID_ENVELOPE_KINDS, f"invalid envelope kind {kind!r}")
    ref_id = _optional_string(mapping, "ref_id")
    shape = _require_mapping(mapping, "shape")
    return BoardEnvelope(id=_require_string(mapping, "id"), kind=kind, ref_id=ref_id, shape=shape)


def _parse_point_list(payload: Mapping[str, Any], key: str) -> list[tuple[float, float]]:
    points = []
    for item in _require_list(payload, key):
        points.append(_parse_xy(item, key))
    _require(len(points) >= 3, f"{key} must contain at least 3 points")
    return points


def _parse_bounds(payload: Mapping[str, Any], key: str) -> dict[str, float]:
    mapping = _require_mapping(payload.get(key), key)
    bounds = {name: _parse_number(mapping, name) for name in ("min_x", "min_y", "max_x", "max_y")}
    _require(bounds["min_x"] < bounds["max_x"], "bounds min_x must be < max_x")
    _require(bounds["min_y"] < bounds["max_y"], "bounds min_y must be < max_y")
    return bounds


def _parse_xy(item: Any, label: str) -> tuple[float, float]:
    mapping = _require_mapping(item, label)
    return (_parse_number(mapping, "x"), _parse_number(mapping, "y"))


def _require_string(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    _require(isinstance(value, str) and value != "", f"{key} must be a non-empty string")
    return value


def _require_string_item(item: Any, label: str) -> str:
    _require(isinstance(item, str) and item != "", f"{label} entries must be non-empty strings")
    return item


def _optional_string(mapping: Mapping[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    _require(isinstance(value, str) and value != "", f"{key} must be a non-empty string when set")
    return value


def _require_number(mapping: Mapping[str, Any], key: str) -> float:
    value = mapping.get(key)
    _require(isinstance(value, (int, float)) and not isinstance(value, bool), f"{key} must be numeric")
    number = float(value)
    _require(math.isfinite(number), f"{key} must be finite")
    return number


def _parse_number(mapping: Mapping[str, Any], key: str) -> float:
    return _require_number(mapping, key)


def _require_int(mapping: Mapping[str, Any], key: str) -> int:
    value = mapping.get(key)
    _require(isinstance(value, int) and not isinstance(value, bool), f"{key} must be an integer")
    return value


def _require_list(mapping: Mapping[str, Any], key: str) -> list[Any]:
    value = mapping.get(key)
    _require(isinstance(value, list), f"{key} must be a list")
    return value


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label} must be an object")
    return value


def _register_id(seen: dict[str, str], kind: str, item_id: str) -> None:
    _require(item_id not in seen, f"duplicate id {item_id!r}")
    seen[item_id] = kind


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BoardIRValidationError(message)
