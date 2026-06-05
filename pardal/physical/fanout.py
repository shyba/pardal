"""Fanout intent compilation for physical specs."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from pardal.data_model import Board, Component, TraceSegment, Via
from pardal.physical.commit_gate import (
    CommitViolation,
    KeepoutConstraint,
    RouteCandidate,
    RouteCommitError,
    commit_route_candidate,
)
from pardal.physical.routes import RouteReportEntry, resolve_point, route_layer_metadata
from pardal.physical.spec import FanoutSpec, PhysicalSpec, SOURCE_LOCATION_KEY, parse_mm


@dataclass(frozen=True)
class QfpSide:
    name: str
    outward: tuple[float, float]
    tangent: tuple[float, float]


SIDES = {
    "left": QfpSide("left", (-1.0, 0.0), (0.0, 1.0)),
    "right": QfpSide("right", (1.0, 0.0), (0.0, 1.0)),
    "top": QfpSide("top", (0.0, -1.0), (1.0, 0.0)),
    "bottom": QfpSide("bottom", (0.0, 1.0), (1.0, 0.0)),
}


def _pad_net_map(board: Board) -> dict[tuple[str, str], str]:
    result = {}
    for net_name, net in board.nets.items():
        for ref, pin in net.connections:
            result[(ref, str(pin))] = net_name
    return result


def _local_to_board(component: Component, point: tuple[float, float]) -> tuple[float, float]:
    angle_rad = math.radians(-component.rotation)
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    return (
        component.position[0] + point[0] * cos_a - point[1] * sin_a,
        component.position[1] + point[0] * sin_a + point[1] * cos_a,
    )


def _classify_qfp_side(offset: tuple[float, float]) -> QfpSide:
    x, y = offset
    if abs(x) >= abs(y):
        return SIDES["right"] if x > 0 else SIDES["left"]
    return SIDES["bottom"] if y > 0 else SIDES["top"]


def _net_via_size(board: Board, net_name: str, raw: dict[str, Any]) -> tuple[float, float]:
    via_raw = raw.get("via") or {}
    if via_raw:
        return (
            parse_mm(via_raw.get("diameter"), field_name="fanout.via.diameter"),
            parse_mm(via_raw.get("drill"), field_name="fanout.via.drill"),
        )
    net = board.nets[net_name]
    if net.net_class and net.net_class in board.net_classes:
        net_class = board.net_classes[net.net_class]
        return net_class.via_size, net_class.via_drill
    return net.via_size, net.via_drill


def _via_layers(board: Board, from_layer: str, to_layer: str) -> tuple[str, ...]:
    if from_layer not in board.layers:
        raise ValueError(f"Via from layer {from_layer} is not in board stack {board.layers}")
    if to_layer not in board.layers:
        raise ValueError(f"Via to layer {to_layer} is not in board stack {board.layers}")
    start = board.layers.index(from_layer)
    end = board.layers.index(to_layer)
    if start <= end:
        return tuple(board.layers[start : end + 1])
    return tuple(board.layers[end : start + 1])


def _explicit_via_layers(board: Board, raw_layers: Any) -> tuple[str, ...]:
    if not isinstance(raw_layers, list) or len(raw_layers) < 2:
        raise ValueError("fanout via layers override must be a list of at least two layers")
    layers = tuple(str(layer) for layer in raw_layers)
    for layer in layers:
        if layer not in board.layers:
            raise ValueError(f"Via layer {layer} is not in board stack {board.layers}")
    return layers


def _via_type_for_layers(board: Board, layers: tuple[str, ...]) -> str:
    if layers[0] == board.layers[0] and layers[-1] == board.layers[-1]:
        return "through"
    if "F.Cu" in layers or "B.Cu" in layers:
        return "blind"
    return "buried"


def _side_lane_groups(
    component: Component, pins: list[str]
) -> dict[str, list[tuple[str, QfpSide, float]]]:
    groups: dict[str, list[tuple[str, QfpSide, float]]] = {}
    for pin in pins:
        pad = component.get_pad_by_number(pin)
        if pad is None:
            raise ValueError(f"Pad {pin} not found on component {component.ref}")
        side = _classify_qfp_side(pad.position_offset)
        tangent_pos = (
            pad.position_offset[0] * side.tangent[0]
            + pad.position_offset[1] * side.tangent[1]
        )
        groups.setdefault(side.name, []).append((pin, side, tangent_pos))
    for side_pins in groups.values():
        side_pins.sort(key=lambda item: item[2])
    return groups


def _compile_authored_pin_escape(
    board: Board,
    component: Component,
    fanout: FanoutSpec,
    pin: str,
    net_name: str,
    raw_points: list[Any],
    start_layer: str,
) -> RouteCandidate:
    if not raw_points:
        raise ValueError(f"fanout.{component.ref}.points_by_pin.{pin} must not be empty")
    current_layer = start_layer
    width = board.get_net_width(net_name)
    via_size, via_drill = _net_via_size(board, net_name, fanout.raw)
    segments: list[TraceSegment] = []
    vias: list[Via] = []
    previous = component.get_pad_position(pin)

    for raw in raw_points:
        if isinstance(raw, dict) and "via" in raw:
            if "to" not in raw:
                raise ValueError(f"fanout.{component.ref}.points_by_pin.{pin} via requires a to layer")
            point = resolve_point(board, raw["via"], previous)
            if point != previous:
                segments.append(
                    TraceSegment(
                        net_name,
                        (round(previous[0], 4), round(previous[1], 4)),
                        (round(point[0], 4), round(point[1], 4)),
                        current_layer,
                        width,
                    )
                )
            to_layer = str(raw["to"])
            layers = (
                _explicit_via_layers(board, raw["layers"])
                if "layers" in raw
                else _via_layers(board, current_layer, to_layer)
            )
            vias.append(
                Via(
                    net_name=net_name,
                    position=(round(point[0], 4), round(point[1], 4)),
                    size=parse_mm(raw.get("diameter", f"{via_size}mm"), field_name="fanout via diameter"),
                    drill=parse_mm(raw.get("drill", f"{via_drill}mm"), field_name="fanout via drill"),
                    layers=layers,
                    via_type=str(raw.get("type", _via_type_for_layers(board, layers))),
                )
            )
            current_layer = to_layer
            previous = point
            continue

        point = resolve_point(board, raw, previous)
        segments.append(
            TraceSegment(
                net_name,
                (round(previous[0], 4), round(previous[1], 4)),
                (round(point[0], 4), round(point[1], 4)),
                current_layer,
                width,
            )
        )
        previous = point

    if not segments and not vias:
        raise ValueError(f"fanout.{component.ref}.points_by_pin.{pin} needs at least one route point")
    return RouteCandidate(net_name, segments, vias)


def compile_qfp_escape_candidates(
    board: Board, component: Component, fanout: FanoutSpec
) -> list[RouteCandidate]:
    raw = fanout.raw
    pins_raw = raw.get("pins") or raw.get("only") or []
    if not isinstance(pins_raw, list) or not pins_raw:
        raise ValueError(f"fanout.{component.ref}.pins must be a non-empty list")
    pins = [str(pin) for pin in pins_raw]
    layer = str(raw.get("layer", "F.Cu"))
    via_layer = raw.get("via_layer")
    if layer not in board.layers:
        raise ValueError(f"fanout.{component.ref}.layer {layer} is not in {board.layers}")
    if via_layer is not None and str(via_layer) not in board.layers:
        raise ValueError(f"fanout.{component.ref}.via_layer {via_layer} is not in {board.layers}")

    escape_length = parse_mm(raw.get("escape_length", "1.2mm"), field_name="fanout.escape_length")
    via_offset = parse_mm(raw.get("via_offset", "2.2mm"), field_name="fanout.via_offset")
    lane_pitch = parse_mm(raw.get("lane_pitch", "0.6mm"), field_name="fanout.lane_pitch")
    pad_nets = _pad_net_map(board)
    candidates: list[RouteCandidate] = []
    points_by_pin = raw.get("points_by_pin") or {}
    if not isinstance(points_by_pin, dict):
        raise ValueError(f"fanout.{component.ref}.points_by_pin must be a mapping when provided")

    for side_pins in _side_lane_groups(component, pins).values():
        center_lane = (len(side_pins) - 1) / 2.0
        for lane_index, (pin, side, _tangent_pos) in enumerate(side_pins):
            net_name = pad_nets.get((component.ref, pin))
            if net_name is None:
                raise ValueError(f"fanout.{component.ref}.{pin} is not connected to a net")
            authored_points = points_by_pin.get(pin)
            if authored_points is not None:
                if not isinstance(authored_points, list):
                    raise ValueError(f"fanout.{component.ref}.points_by_pin.{pin} must be a list")
                candidates.append(
                    _compile_authored_pin_escape(
                        board, component, fanout, pin, net_name, authored_points, layer
                    )
                )
                continue
            pad = component.get_pad_by_number(pin)
            assert pad is not None
            width = board.get_net_width(net_name)
            pad_local = pad.position_offset
            escape_local = (
                pad_local[0] + side.outward[0] * escape_length,
                pad_local[1] + side.outward[1] * escape_length,
            )
            lane_delta = (lane_index - center_lane) * lane_pitch
            via_local = (
                pad_local[0] + side.outward[0] * via_offset + side.tangent[0] * lane_delta,
                pad_local[1] + side.outward[1] * via_offset + side.tangent[1] * lane_delta,
            )
            pad_point = component.get_pad_position(pin)
            escape_point = _local_to_board(component, escape_local)
            segments = [
                TraceSegment(
                    net_name,
                    (round(pad_point[0], 4), round(pad_point[1], 4)),
                    (round(escape_point[0], 4), round(escape_point[1], 4)),
                    layer,
                    width,
                )
            ]
            vias = []
            if via_layer is not None:
                via_point = _local_to_board(component, via_local)
                segments.append(
                    TraceSegment(
                        net_name,
                        (round(escape_point[0], 4), round(escape_point[1], 4)),
                        (round(via_point[0], 4), round(via_point[1], 4)),
                        layer,
                        width,
                    )
                )
                via_size, via_drill = _net_via_size(board, net_name, raw)
                layers = _via_layers(board, layer, str(via_layer))
                vias.append(
                    Via(
                        net_name,
                        (round(via_point[0], 4), round(via_point[1], 4)),
                        via_size,
                        via_drill,
                        layers,
                        _via_type_for_layers(board, layers),
                    )
                )
            candidates.append(RouteCandidate(net_name, segments, vias))
    return candidates


def _route_length(candidate: RouteCandidate) -> float:
    return sum(math.dist(segment.start, segment.end) for segment in candidate.segments)


def _report(
    board: Board,
    candidate: RouteCandidate,
    committed: bool,
    message: str = "",
) -> RouteReportEntry:
    return RouteReportEntry(
        net=candidate.net,
        strategy="qfp_escape",
        segments=len(candidate.segments),
        vias=len(candidate.vias),
        length=_route_length(candidate),
        committed=committed,
        message=message,
        **route_layer_metadata(board, candidate, committed=committed),
    )


def compile_fanouts(
    board: Board, spec: PhysicalSpec, *, strict: bool = False
) -> tuple[list[RouteReportEntry], list[CommitViolation]]:
    reports: list[RouteReportEntry] = []
    violations: list[CommitViolation] = []
    keepouts = [
        KeepoutConstraint(
            name=intent.name,
            layer=intent.layer,
            kind=intent.kind,
            at=intent.at,
            size=intent.size,
            source=(
                intent.raw[SOURCE_LOCATION_KEY].display()
                if SOURCE_LOCATION_KEY in intent.raw
                else ""
            ),
        )
        for intent in spec.keepouts
    ]
    for ref, fanout in spec.fanouts.items():
        raw = fanout.raw
        kind = str(raw.get("kind") or raw.get("type") or "")
        if kind != "qfp_escape":
            if kind:
                raise ValueError(f"Unsupported fanout kind {kind!r}")
            continue
        component = board.components.get(ref)
        if component is None:
            raise ValueError(f"fanout references missing component {ref}")
        for candidate in compile_qfp_escape_candidates(board, component, fanout):
            try:
                commit_route_candidate(board, candidate, keepouts=keepouts)
                reports.append(_report(board, candidate, True))
            except RouteCommitError as exc:
                if strict:
                    raise
                message = "; ".join(v.message for v in exc.violations[:3])
                reports.append(_report(board, candidate, False, message))
                violations.extend(exc.violations)
    return reports, violations
