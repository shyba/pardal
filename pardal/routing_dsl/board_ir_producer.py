"""Pure producer for frozen routing DSL board IR payloads.

This module accepts a deterministic structured source description and emits a
`board.ir.json` payload that is accepted by :func:`pardal.routing_dsl.board_ir.load_board_ir`.
It does not read KiCad boards and does not mutate any source object.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from .board_ir import BOARD_IR_SCHEMA, BOARD_IR_VERSION, load_board_ir


BOARD_IR_PRODUCER_SCHEMA = "pardal.board_ir_source"
BOARD_IR_PRODUCER_VERSION = "0.1"

_VALID_OBSTACLE_SHAPES = {"rect"}
_VALID_ENVELOPE_SHAPES = {"rect"}


class BoardIRProducerError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class BoardIRProducerResult:
    payload: dict[str, Any]
    path: Path | None = None


def load_board_ir_source(source: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(source, Mapping):
        return dict(source)
    return json.loads(Path(source).read_text(encoding="utf-8"))


def produce_board_ir(
    source: str | Path | Mapping[str, Any],
    output_path: str | Path | None = None,
) -> BoardIRProducerResult:
    payload = _validate_source(load_board_ir_source(source))
    board_ir = _build_board_ir(payload)
    load_board_ir(board_ir)

    if output_path is not None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(board_ir, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        return BoardIRProducerResult(payload=board_ir, path=path)
    return BoardIRProducerResult(payload=board_ir, path=None)


def _validate_source(payload: Mapping[str, Any]) -> dict[str, Any]:
    _require(isinstance(payload, Mapping), "board IR source must be a mapping")
    _require(payload.get("schema") == BOARD_IR_PRODUCER_SCHEMA, "schema must be pardal.board_ir_source")
    _require(payload.get("version") == BOARD_IR_PRODUCER_VERSION, "version must be 0.1")

    board_ir_id = _require_string(payload, "board_ir_id")
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

    seen: set[str] = set()
    for label, items in (("layer", stackup), ("net", nets), ("component", components), ("pad", pads), ("obstacle", obstacles), ("envelope", envelopes)):
        for item in items:
            _require(item["id"] not in seen, f"duplicate stable id {item['id']!r}")
            seen.add(item["id"])

    layer_names = {layer["name"] for layer in stackup}
    net_ids = {net["id"] for net in nets}
    component_ids = {component["id"] for component in components}
    pad_ids = {pad["id"] for pad in pads}
    for pad in pads:
        _require(pad["component_id"] in component_ids, f"pad {pad['id']} references unknown component")
        _require(pad["layer"] in layer_names, f"pad {pad['id']} references unknown layer")
        _require(pad["net_id"] in net_ids, f"pad {pad['id']} references unknown net")
    for obstacle in obstacles:
        _require(obstacle["layer"] in layer_names, f"obstacle {obstacle['id']} references unknown layer")
    for envelope in envelopes:
        _require(envelope["layer"] in layer_names, f"envelope {envelope['id']} references unknown layer")
        _require(
            envelope["ref_id"] in component_ids or envelope["ref_id"] in pad_ids,
            f"envelope {envelope['id']} references unknown object",
        )

    source_copy = json.loads(json.dumps(_source_hash_payload(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    snapshot_hash = f"sha256:{_sha256_json(source_copy)}"
    frozen_snapshot_id = f"{board_ir_id}-snapshot-{snapshot_hash}"
    return {
        "schema": BOARD_IR_SCHEMA,
        "version": BOARD_IR_VERSION,
        "board_ir_id": board_ir_id,
        "frozen_board_snapshot_id": frozen_snapshot_id,
        "units": {"length": length_unit, "angle": angle_unit},
        "outline": outline,
        "bounds": bounds,
        "stackup": stackup,
        "nets": nets,
        "components": components,
        "pads": pads,
        "obstacles": obstacles,
        "envelopes": envelopes,
        "provenance": {
            **dict(provenance),
            "producer": {
                "schema": BOARD_IR_PRODUCER_SCHEMA,
                "version": BOARD_IR_PRODUCER_VERSION,
                "snapshot_hash": snapshot_hash,
            },
        },
        "route_plan_anchor_ids": route_plan_anchor_ids,
    }


def _build_board_ir(payload: Mapping[str, Any]) -> dict[str, Any]:
    return dict(payload)


def _source_hash_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "board_ir_id": payload["board_ir_id"],
        "units": payload["units"],
        "outline": payload["outline"],
        "bounds": payload["bounds"],
        "stackup": payload["stackup"],
        "nets": payload["nets"],
        "components": payload["components"],
        "pads": payload["pads"],
        "obstacles": payload["obstacles"],
        "envelopes": payload["envelopes"],
        "route_plan_anchor_ids": payload["route_plan_anchor_ids"],
    }


def _parse_layer(item: Any) -> dict[str, Any]:
    mapping = _require_mapping(item, "stackup item")
    kind = _require_string(mapping, "kind")
    _require(kind in {"signal", "plane", "mechanical", "keepout"}, f"invalid layer kind {kind!r}")
    return {"id": _require_string(mapping, "id"), "name": _require_string(mapping, "name"), "kind": kind, "order": _require_int(mapping, "order")}


def _parse_net(item: Any) -> dict[str, Any]:
    mapping = _require_mapping(item, "net")
    return {"id": _require_string(mapping, "id"), "name": _require_string(mapping, "name")}


def _parse_component(item: Any) -> dict[str, Any]:
    mapping = _require_mapping(item, "component")
    return {
        "id": _require_string(mapping, "id"),
        "refdes": _require_string(mapping, "refdes"),
        "footprint": _require_string(mapping, "footprint"),
        "layer": _require_string(mapping, "layer"),
        "position": _parse_xy(mapping.get("position"), "position"),
        "rotation": _parse_number(mapping, "rotation"),
    }


def _parse_pad(item: Any) -> dict[str, Any]:
    mapping = _require_mapping(item, "pad")
    return {
        "id": _require_string(mapping, "id"),
        "component_id": _require_string(mapping, "component_id"),
        "net_id": _require_string(mapping, "net_id"),
        "layer": _require_string(mapping, "layer"),
        "kind": _require_string(mapping, "kind"),
        "position": _parse_xy(mapping.get("position"), "position"),
    }


def _parse_obstacle(item: Any) -> dict[str, Any]:
    mapping = _require_mapping(item, "obstacle")
    shape = _require_mapping(mapping.get("shape"), "shape")
    shape_type = _require_string(shape, "type")
    _require(shape_type in _VALID_OBSTACLE_SHAPES, f"unsupported obstacle shape {shape_type!r}")
    return {"id": _require_string(mapping, "id"), "kind": _require_string(mapping, "kind"), "layer": _require_string(mapping, "layer"), "shape": _normalize_shape(shape)}


def _parse_envelope(item: Any) -> dict[str, Any]:
    mapping = _require_mapping(item, "envelope")
    shape = _require_mapping(mapping.get("shape"), "shape")
    shape_type = _require_string(shape, "type")
    _require(shape_type in _VALID_ENVELOPE_SHAPES, f"unsupported envelope shape {shape_type!r}")
    return {
        "id": _require_string(mapping, "id"),
        "kind": _require_string(mapping, "kind"),
        "ref_id": _require_string(mapping, "ref_id"),
        "layer": _require_string(mapping, "layer"),
        "shape": _normalize_shape(shape),
    }


def _normalize_shape(shape: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(shape)
    for key, value in normalized.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            _require(math.isfinite(float(value)), f"{key} must be finite")
    return normalized


def _parse_point_list(payload: Mapping[str, Any], key: str) -> list[dict[str, float]]:
    points = [_parse_xy(item, key) for item in _require_list(payload, key)]
    _require(len(points) >= 3, f"{key} must contain at least 3 points")
    return points


def _parse_bounds(payload: Mapping[str, Any], key: str) -> dict[str, float]:
    mapping = _require_mapping(payload.get(key), key)
    bounds = {name: _parse_number(mapping, name) for name in ("min_x", "min_y", "max_x", "max_y")}
    _require(bounds["min_x"] < bounds["max_x"], "bounds min_x must be < max_x")
    _require(bounds["min_y"] < bounds["max_y"], "bounds min_y must be < max_y")
    return bounds


def _parse_xy(item: Any, label: str) -> dict[str, float]:
    mapping = _require_mapping(item, label)
    return {"x": _parse_number(mapping, "x"), "y": _parse_number(mapping, "y")}


def _require_string(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    _require(isinstance(value, str) and value != "", f"{key} must be a non-empty string")
    return value


def _require_string_item(item: Any, label: str) -> str:
    _require(isinstance(item, str) and item != "", f"{label} entries must be non-empty strings")
    return item


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


def _sha256_json(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(raw.encode("utf-8")).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BoardIRProducerError(message)
