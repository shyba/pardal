"""Route intent compilation for physical specs."""

from __future__ import annotations

import copy
from dataclasses import dataclass
import itertools
import math
import re
from typing import Any, Iterable

from pardal.data_model import Board, TraceSegment, Via
from pardal.physical.commit_gate import (
    CommitViolation,
    KeepoutConstraint,
    RouteCandidate,
    RouteCommitError,
    commit_route_candidate,
    validate_route_candidate,
)
from pardal.physical.spec import PhysicalSpec, RouteCorridorIntent, parse_mm

MAX_HEADER_BANK_BUNDLE_COMBINATIONS = 256
MAX_ESCAPE_BUNDLE_CANDIDATES = 512


@dataclass(frozen=True)
class RouteReportEntry:
    net: str
    strategy: str
    segments: int
    vias: int
    length: float
    committed: bool
    message: str = ""
    used_layers: tuple[str, ...] = ()
    segment_layers: tuple[str, ...] = ()
    via_layers: tuple[tuple[str, ...], ...] = ()
    route_name: str = ""
    route_index: int | None = None
    source: str = ""
    alternative_name: str = ""
    replacement_removed_segments: int = 0
    replacement_removed_vias: int = 0
    replacement_nets: tuple[str, ...] = ()


@dataclass(frozen=True)
class _HeaderBankAlternative:
    net: str
    name: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class _HeaderBankStagedCandidate:
    alternative: _HeaderBankAlternative
    candidate: RouteCandidate


@dataclass(frozen=True)
class _EscapeBundleStagedCandidate:
    template_name: str
    assignment: dict[str, float]
    candidate: RouteCandidate
    stage: str = "route_template"


@dataclass(frozen=True)
class _EscapePlacementMove:
    name: str
    refs: tuple[str, ...]
    dx_token: Any
    dy_token: Any
    rotate_token: Any
    raw: dict[str, Any]


@dataclass(frozen=True)
class _EscapeAppliedMove:
    name: str
    ref: str
    original_position: tuple[float, float]
    staged_position: tuple[float, float]
    dx: float
    dy: float
    rotation: float | None


@dataclass(frozen=True)
class _EscapeFanoutTemplate:
    name: str
    ref: str
    pin: str
    net: str
    start_layer: str
    points: list[Any]
    raw: dict[str, Any]


@dataclass(frozen=True)
class _RouteReplacementIntent:
    nets: tuple[str, ...]
    refs: tuple[str, ...]
    include_fanout: bool
    require_all_nets: bool
    max_removed_segments: int
    max_removed_vias: int
    allow_power_nets: bool


@dataclass(frozen=True)
class RouteReplacementReport:
    nets: tuple[str, ...]
    removed_segments: int
    removed_vias: int
    by_net: tuple[dict[str, int | str], ...]


@dataclass(frozen=True)
class _EscapeAssignment:
    route_variables: dict[str, float]
    placement_variables: dict[str, float]
    fanout_variables: dict[str, float]

    @property
    def merged(self) -> dict[str, float]:
        return {
            **self.route_variables,
            **self.placement_variables,
            **self.fanout_variables,
        }


@dataclass(frozen=True)
class RouteFailureSegment:
    start: tuple[float, float]
    end: tuple[float, float]
    layer: str
    width: float


@dataclass(frozen=True)
class RouteFailureVia:
    position: tuple[float, float]
    size: float
    drill: float
    layers: tuple[str, ...]
    via_type: str


@dataclass(frozen=True)
class RouteFailureViolation:
    code: str
    message: str
    net: str | None = None
    layer: str | None = None
    source: str = ""
    distance: float | None = None


@dataclass(frozen=True)
class RouteFailureCandidate:
    segments: tuple[RouteFailureSegment, ...]
    vias: tuple[RouteFailureVia, ...]
    segment_layers: tuple[str, ...]
    via_layers: tuple[tuple[str, ...], ...]
    used_layers: tuple[str, ...]


@dataclass(frozen=True)
class RouteFailureReport:
    net: str
    strategy: str
    route_name: str
    route_index: int | None
    source: str
    candidate: RouteFailureCandidate
    violations: tuple[RouteFailureViolation, ...]
    alternative_name: str = ""
    template_name: str = ""
    assignment: dict[str, float] | None = None
    failed_stage: str = ""
    moved_refs: tuple[str, ...] = ()
    placement_moves: tuple[dict[str, Any], ...] = ()
    replacement_report: RouteReplacementReport | None = None


class RouteCommitFailureError(RouteCommitError):
    def __init__(
        self,
        report: RouteFailureReport,
        violations: list[CommitViolation],
        reports: list[RouteFailureReport] | None = None,
    ):
        self.report = report
        self.reports = reports or [report]
        super().__init__(violations)


def _source_display(raw: dict[str, Any]) -> str:
    source = raw.get("__pdl_source__")
    display = getattr(source, "display", None)
    return display() if callable(display) else ""


def _route_report_name(raw: dict[str, Any], index: int) -> str:
    name = raw.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    kind = str(raw.get("kind") or raw.get("strategy") or "route")
    return f"{kind}[{index + 1:04d}]"


def _ordered_layers(board: Board, layers: set[str]) -> tuple[str, ...]:
    known = [layer for layer in board.layers if layer in layers]
    extras = sorted(layer for layer in layers if layer not in board.layers)
    return tuple(known + extras)


def _ordered_unique_layers(*layer_groups: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for group in layer_groups:
        for layer in group:
            if layer in seen:
                continue
            ordered.append(layer)
            seen.add(layer)
    return tuple(ordered)


def route_layer_metadata(
    board: Board,
    candidate: RouteCandidate,
    *,
    committed: bool,
) -> dict[str, tuple[str, ...] | tuple[tuple[str, ...], ...]]:
    if not committed:
        return {
            "used_layers": (),
            "segment_layers": (),
            "via_layers": (),
        }
    segment_layers = _ordered_unique_layers((segment.layer for segment in candidate.segments))
    via_layers = tuple(tuple(via.layers) for via in candidate.vias)
    used = _ordered_unique_layers(
        segment_layers,
        (layer for via_span in via_layers for layer in via_span),
    )
    used = _ordered_layers(board, set(used))
    return {
        "used_layers": used,
        "segment_layers": segment_layers,
        "via_layers": via_layers,
    }


def _pad_point(board: Board, token: str) -> tuple[float, float]:
    try:
        ref, pin = token.split(".", 1)
    except ValueError as exc:
        raise ValueError(f"Expected pad reference like U1.64, got {token!r}") from exc
    comp = board.components.get(ref)
    if comp is None:
        raise ValueError(f"Unknown component reference {ref!r}")
    return comp.get_pad_position(pin)


_REL_RE = re.compile(
    r"^(?P<dir>north|south|east|west)\s+(?P<dist>[0-9.]+mm)(?:\s+from\s+(?P<ref>[A-Za-z0-9_]+[.][A-Za-z0-9_]+))?$"
)


def resolve_point(
    board: Board, raw: Any, previous: tuple[float, float] | None = None
) -> tuple[float, float]:
    if isinstance(raw, list | tuple):
        if len(raw) == 1:
            return resolve_point(board, raw[0], previous)
        if len(raw) == 2:
            return (
                parse_mm(raw[0], field_name="route point x"),
                parse_mm(raw[1], field_name="route point y"),
            )
        raise ValueError(f"Unsupported route point list {raw!r}")
    if not isinstance(raw, str):
        raise ValueError(f"Unsupported route point {raw!r}")

    text = raw.strip()
    match = _REL_RE.match(text)
    if match:
        if match.group("ref"):
            base = _pad_point(board, match.group("ref"))
        elif previous is not None:
            base = previous
        else:
            raise ValueError(f"Relative route point {text!r} needs a previous point")
        dist = parse_mm(match.group("dist"), field_name="relative route distance")
        direction = match.group("dir")
        dx, dy = {
            "north": (0.0, -dist),
            "south": (0.0, dist),
            "east": (dist, 0.0),
            "west": (-dist, 0.0),
        }[direction]
        return (base[0] + dx, base[1] + dy)

    if "." in text:
        return _pad_point(board, text)
    raise ValueError(f"Unsupported route point {raw!r}")


def _resolve_points(board: Board, raw_points: list[Any]) -> list[tuple[float, float]]:
    points = []
    previous = None
    for raw in raw_points:
        point = resolve_point(board, raw, previous)
        points.append(point)
        previous = point
    if len(points) < 2:
        raise ValueError("route needs at least two points")
    return points


def _segments_for_points(
    net_name: str, points: list[tuple[float, float]], layer: str, width: float
) -> list[TraceSegment]:
    return [
        TraceSegment(
            net_name=net_name,
            start=(round(a[0], 4), round(a[1], 4)),
            end=(round(b[0], 4), round(b[1], 4)),
            layer=layer,
            width=width,
        )
        for a, b in zip(points, points[1:])
    ]


def _route_length(segments: list[TraceSegment]) -> float:
    return sum(math.dist(segment.start, segment.end) for segment in segments)


def _commit(
    board: Board,
    candidate: RouteCandidate,
    strategy: str,
    *,
    strict: bool,
    keepouts: list[KeepoutConstraint] | None = None,
    route_name: str = "",
    route_index: int | None = None,
    source: str = "",
    alternative_name: str = "",
) -> tuple[RouteReportEntry, list[CommitViolation]]:
    try:
        commit_route_candidate(board, candidate, keepouts=keepouts)
        return (
            RouteReportEntry(
                net=candidate.net,
                strategy=strategy,
                segments=len(candidate.segments),
                vias=len(candidate.vias),
                length=_route_length(candidate.segments),
                committed=True,
                route_name=route_name,
                route_index=route_index,
                source=source,
                alternative_name=alternative_name,
                **route_layer_metadata(board, candidate, committed=True),
            ),
            [],
        )
    except RouteCommitError as exc:
        if strict:
            report = _route_failure_report(
                board,
                candidate,
                strategy,
                exc.violations,
                route_name=route_name,
                route_index=route_index,
                source=source,
                alternative_name=alternative_name,
            )
            raise RouteCommitFailureError(report, list(exc.violations))
        message = "; ".join(v.message for v in exc.violations[:3])
        return (
            RouteReportEntry(
                net=candidate.net,
                strategy=strategy,
                segments=len(candidate.segments),
                vias=len(candidate.vias),
                length=_route_length(candidate.segments),
                committed=False,
                message=message,
                route_name=route_name,
                route_index=route_index,
                source=source,
                alternative_name=alternative_name,
                **route_layer_metadata(board, candidate, committed=False),
            ),
            exc.violations,
        )


def _route_failure_report(
    board: Board,
    candidate: RouteCandidate,
    strategy: str,
    violations: list[CommitViolation],
    *,
    route_name: str = "",
    route_index: int | None = None,
    source: str = "",
    alternative_name: str = "",
    template_name: str = "",
    assignment: dict[str, float] | None = None,
    failed_stage: str = "",
    placement_moves: tuple[dict[str, Any], ...] = (),
    replacement_report: RouteReplacementReport | None = None,
) -> RouteFailureReport:
    route_layers = route_layer_metadata(board, candidate, committed=False)
    return RouteFailureReport(
        net=candidate.net,
        strategy=strategy,
        route_name=route_name,
        route_index=route_index,
        source=source,
        alternative_name=alternative_name,
        candidate=RouteFailureCandidate(
            segments=tuple(
                RouteFailureSegment(
                    start=segment.start,
                    end=segment.end,
                    layer=segment.layer,
                    width=segment.width,
                )
                for segment in candidate.segments
            ),
            vias=tuple(
                RouteFailureVia(
                    position=via.position,
                    size=via.size,
                    drill=via.drill,
                    layers=via.layers,
                    via_type=via.via_type,
                )
                for via in candidate.vias
            ),
            segment_layers=route_layers["segment_layers"],
            via_layers=route_layers["via_layers"],
            used_layers=route_layers["used_layers"],
        ),
        violations=tuple(
            RouteFailureViolation(
                code=violation.code,
                message=violation.message,
                net=violation.net,
                layer=violation.layer,
                source=violation.source,
                distance=getattr(violation, "distance", None),
            )
            for violation in violations
        ),
        template_name=template_name,
        assignment=assignment,
        failed_stage=failed_stage,
        moved_refs=tuple(str(move.get("ref", "")) for move in placement_moves),
        placement_moves=placement_moves,
        replacement_report=replacement_report,
    )


def _candidate_from_points(
    board: Board, net_name: str, points: list[tuple[float, float]], layer: str
) -> RouteCandidate:
    if net_name not in board.nets:
        raise ValueError(f"Unknown route net {net_name!r}")
    width = board.get_net_width(net_name)
    return RouteCandidate(
        net=net_name,
        segments=_segments_for_points(net_name, points, layer, width),
    )


def _net_via_size(board: Board, net_name: str) -> tuple[float, float]:
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
        raise ValueError("via layers override must be a list of at least two layers")
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


def _compile_layered_polyline(
    board: Board, net_name: str, raw_points: list[Any], start_layer: str
) -> RouteCandidate:
    if net_name not in board.nets:
        raise ValueError(f"Unknown route net {net_name!r}")

    current_layer = start_layer
    width = board.get_net_width(net_name)
    via_size, via_drill = _net_via_size(board, net_name)
    segments: list[TraceSegment] = []
    vias: list[Via] = []
    previous: tuple[float, float] | None = None

    for raw in raw_points:
        if isinstance(raw, dict) and "via" in raw:
            if "to" not in raw:
                raise ValueError(f"via route point for {net_name} requires a to layer")
            point = resolve_point(board, raw["via"], previous)
            if previous is not None and point != previous:
                segments.append(
                    _segments_for_points(net_name, [previous, point], current_layer, width)[0]
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
                    size=parse_mm(raw.get("diameter", f"{via_size}mm"), field_name="route via diameter"),
                    drill=parse_mm(raw.get("drill", f"{via_drill}mm"), field_name="route via drill"),
                    layers=layers,
                    via_type=str(raw.get("type", _via_type_for_layers(board, layers))),
                )
            )
            current_layer = to_layer
            previous = point
            continue

        point = resolve_point(board, raw, previous)
        if previous is not None:
            segments.append(
                _segments_for_points(net_name, [previous, point], current_layer, width)[0]
            )
        previous = point

    if previous is None:
        raise ValueError("route needs at least two points")
    if not segments and not vias:
        raise ValueError("route needs at least two points")
    return RouteCandidate(net=net_name, segments=segments, vias=vias)


def _compile_manual_polyline(board: Board, raw: dict[str, Any]) -> RouteCandidate:
    net_name = str(raw["net"])
    layer = str(raw.get("layer") or raw.get("prefer_layer") or "F.Cu")
    points_raw = raw.get("points")
    if not isinstance(points_raw, list):
        raise ValueError(f"manual_polyline route for {net_name} requires points")
    if any(isinstance(point, dict) and "via" in point for point in points_raw):
        return _compile_layered_polyline(board, net_name, points_raw, layer)
    return _candidate_from_points(board, net_name, _resolve_points(board, points_raw), layer)


def _compile_direct(board: Board, raw: dict[str, Any], net_name: str | None = None) -> RouteCandidate:
    net_name = net_name or str(raw["net"])
    layer = str(raw.get("layer") or raw.get("prefer_layer") or "F.Cu")
    if "from" in raw and "to" in raw:
        points = [resolve_point(board, raw["from"]), resolve_point(board, raw["to"])]
    else:
        net = board.nets.get(net_name)
        if net is None:
            raise ValueError(f"Unknown route net {net_name!r}")
        if len(net.connections) < 2:
            raise ValueError(f"Direct route for {net_name} needs at least two connections")
        points = [
            _pad_point(board, f"{net.connections[0][0]}.{net.connections[0][1]}"),
            _pad_point(board, f"{net.connections[1][0]}.{net.connections[1][1]}"),
        ]
    return _candidate_from_points(board, net_name, points, layer)


def _find_net_pad_token_on_ref(board: Board, net_name: str, ref: str) -> str:
    net = board.nets.get(net_name)
    if net is None:
        raise ValueError(f"Unknown route net {net_name!r}")
    for conn_ref, conn_pin in net.connections:
        if conn_ref == ref:
            return f"{conn_ref}.{conn_pin}"
    raise ValueError(f"header_bank net {net_name!r} has no pad on {ref!r}")


def _compile_header_bank(
    board: Board, raw: dict[str, Any], route_corridors: dict[str, RouteCorridorIntent], net_name: str
) -> RouteCandidate:
    # Note: compile-time header-bank corridor refs are resolved by the caller.
    # keep this function focused on point materialization.
    from_ref = str(raw["from_ref"])
    to_ref = str(raw["to_ref"])
    layer = str(raw.get("layer") or raw.get("prefer_layer") or "F.Cu")
    from_by_net = raw.get("from_by_net") or {}
    to_by_net = raw.get("to_by_net") or {}
    if not isinstance(from_by_net, dict):
        raise ValueError("header_bank from_by_net must be a mapping when provided")
    if not isinstance(to_by_net, dict):
        raise ValueError("header_bank to_by_net must be a mapping when provided")

    start_raw = from_by_net.get(net_name, _find_net_pad_token_on_ref(board, net_name, from_ref))
    end_raw = to_by_net.get(net_name, _find_net_pad_token_on_ref(board, net_name, to_ref))

    raw_points: list[Any] = [start_raw]
    for raw_point in raw.get("waypoints") or []:
        raw_points.append(raw_point)
    if raw.get("corridor"):
        raw_points.extend(
            _header_bank_corridor_points(
                board=board,
                raw=raw,
                route_corridors=route_corridors,
                net_name=net_name,
                previous=raw_points[-1],
            )
        )
    per_net_waypoints = raw.get("waypoints_by_net") or {}
    if not isinstance(per_net_waypoints, dict):
        raise ValueError("header_bank waypoints_by_net must be a mapping when provided")
    for raw_point in per_net_waypoints.get(net_name) or []:
        raw_points.append(raw_point)
    raw_points.append(end_raw)
    return _compile_layered_polyline(board, net_name, raw_points, layer)


def _header_bank_alternatives(raw: dict[str, Any], net_name: str) -> list[tuple[str, dict[str, Any]]]:
    alternatives_by_net = raw.get("alternatives_by_net") or {}
    if not isinstance(alternatives_by_net, dict):
        raise ValueError("header_bank alternatives_by_net must be a mapping when provided")
    raw_alternatives = alternatives_by_net.get(net_name) or []
    if not isinstance(raw_alternatives, list):
        raise ValueError(f"header_bank alternatives_by_net.{net_name} must be a list")

    alternatives: list[tuple[str, dict[str, Any]]] = [("", raw)]
    for index, alternative in enumerate(raw_alternatives):
        if not isinstance(alternative, dict):
            raise ValueError(f"header_bank alternatives_by_net.{net_name}[{index}] must be a mapping")
        name = alternative.get("name", f"alternative_{index + 1}")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"header_bank alternatives_by_net.{net_name}[{index}].name must be non-empty")
        merged = dict(raw)
        merged.update(alternative)
        merged.pop("name", None)
        alternatives.append((name.strip(), merged))
    return alternatives


def _commit_header_bank_candidates(
    board: Board,
    spec: PhysicalSpec,
    raw: dict[str, Any],
    net_name: str,
    *,
    strict: bool,
    keepouts: list[KeepoutConstraint],
    route_name: str,
    route_index: int,
    route_source: str,
) -> tuple[RouteReportEntry, list[CommitViolation]]:
    failed_reports: list[RouteFailureReport] = []
    failed_violations: list[CommitViolation] = []

    for alternative_name, candidate_raw in _header_bank_alternatives(raw, net_name):
        candidate = _compile_header_bank(board, candidate_raw, spec.route_corridors, net_name)
        violations = validate_route_candidate(board, candidate, keepouts=keepouts)
        if not violations:
            commit_route_candidate(board, candidate, keepouts=keepouts)
            return (
                RouteReportEntry(
                    net=candidate.net,
                    strategy="header_bank",
                    segments=len(candidate.segments),
                    vias=len(candidate.vias),
                    length=_route_length(candidate.segments),
                    committed=True,
                    route_name=route_name,
                    route_index=route_index,
                    source=route_source,
                    alternative_name=alternative_name,
                    **route_layer_metadata(board, candidate, committed=True),
                ),
                [],
            )

        failed_violations.extend(violations)
        failed_reports.append(
            _route_failure_report(
                board,
                candidate,
                "header_bank",
                violations,
                route_name=route_name,
                route_index=route_index,
                source=route_source,
                alternative_name=alternative_name,
            )
        )

    if strict:
        report = failed_reports[-1]
        raise RouteCommitFailureError(report, failed_violations, reports=failed_reports)

    report = failed_reports[-1]
    return (
        RouteReportEntry(
            net=report.net,
            strategy=report.strategy,
            segments=len(report.candidate.segments),
            vias=len(report.candidate.vias),
            length=_route_length(
                [
                    TraceSegment(
                        net_name=report.net,
                        start=segment.start,
                        end=segment.end,
                        layer=segment.layer,
                        width=segment.width,
                    )
                    for segment in report.candidate.segments
                ]
            ),
            committed=False,
            message="; ".join(v.message for v in failed_violations[:3]),
            route_name=route_name,
            route_index=route_index,
            source=route_source,
            alternative_name=report.alternative_name,
        ),
        failed_violations,
    )


def _header_bank_bundle_alternatives(
    raw: dict[str, Any],
    nets: list[str],
) -> list[list[_HeaderBankAlternative]]:
    alternatives_by_net = [
        [
            _HeaderBankAlternative(net=net_name, name=alternative_name, raw=candidate_raw)
            for alternative_name, candidate_raw in _header_bank_alternatives(raw, net_name)
        ]
        for net_name in nets
    ]
    combination_count = math.prod(len(alternatives) for alternatives in alternatives_by_net)
    if combination_count > MAX_HEADER_BANK_BUNDLE_COMBINATIONS:
        raise ValueError(
            "header_bank alternative combinations exceed "
            f"{MAX_HEADER_BANK_BUNDLE_COMBINATIONS}: {combination_count}"
        )
    return alternatives_by_net


def _route_report_from_candidate(
    board: Board,
    candidate: RouteCandidate,
    strategy: str,
    *,
    committed: bool,
    route_name: str,
    route_index: int,
    source: str,
    alternative_name: str = "",
    message: str = "",
    replacement_report: RouteReplacementReport | None = None,
) -> RouteReportEntry:
    return RouteReportEntry(
        net=candidate.net,
        strategy=strategy,
        segments=len(candidate.segments),
        vias=len(candidate.vias),
        length=_route_length(candidate.segments),
        committed=committed,
        message=message,
        route_name=route_name,
        route_index=route_index,
        source=source,
        alternative_name=alternative_name,
        replacement_removed_segments=(
            replacement_report.removed_segments if replacement_report is not None else 0
        ),
        replacement_removed_vias=(
            replacement_report.removed_vias if replacement_report is not None else 0
        ),
        replacement_nets=replacement_report.nets if replacement_report is not None else (),
        **route_layer_metadata(board, candidate, committed=committed),
    )


def _commit_header_bank_bundle(
    board: Board,
    spec: PhysicalSpec,
    raw: dict[str, Any],
    nets: list[str],
    *,
    strict: bool,
    keepouts: list[KeepoutConstraint],
    route_name: str,
    route_index: int,
    route_source: str,
) -> tuple[list[RouteReportEntry], list[CommitViolation]]:
    alternatives_by_net = _header_bank_bundle_alternatives(raw, nets)
    failed_reports: list[RouteFailureReport] = []
    failed_violations: list[CommitViolation] = []

    for combination in itertools.product(*alternatives_by_net):
        staged_board = copy.deepcopy(board)
        staged_candidates: list[_HeaderBankStagedCandidate] = []
        combination_valid = True

        for alternative in combination:
            candidate = _compile_header_bank(
                staged_board,
                alternative.raw,
                spec.route_corridors,
                alternative.net,
            )
            violations = validate_route_candidate(staged_board, candidate, keepouts=keepouts)
            if violations:
                failed_violations.extend(violations)
                failed_reports.append(
                    _route_failure_report(
                        staged_board,
                        candidate,
                        "header_bank",
                        violations,
                        route_name=route_name,
                        route_index=route_index,
                        source=route_source,
                        alternative_name=alternative.name,
                    )
                )
                combination_valid = False
                break

            commit_route_candidate(staged_board, candidate, keepouts=keepouts)
            staged_candidates.append(
                _HeaderBankStagedCandidate(alternative=alternative, candidate=candidate)
            )

        if not combination_valid:
            continue

        reports: list[RouteReportEntry] = []
        for staged in staged_candidates:
            board.nets[staged.candidate.net].segments.extend(staged.candidate.segments)
            board.nets[staged.candidate.net].vias.extend(staged.candidate.vias)
            reports.append(
                _route_report_from_candidate(
                    board,
                    staged.candidate,
                    "header_bank",
                    committed=True,
                    route_name=route_name,
                    route_index=route_index,
                    source=route_source,
                    alternative_name=staged.alternative.name,
                )
            )
        return reports, []

    if strict:
        report = failed_reports[-1]
        raise RouteCommitFailureError(report, failed_violations, reports=failed_reports)

    report = failed_reports[-1]
    candidate = RouteCandidate(
        report.net,
        [
            TraceSegment(
                net_name=report.net,
                start=segment.start,
                end=segment.end,
                layer=segment.layer,
                width=segment.width,
            )
            for segment in report.candidate.segments
        ],
        [
            Via(
                net_name=report.net,
                position=via.position,
                size=via.size,
                drill=via.drill,
                layers=via.layers,
                via_type=via.via_type,
            )
            for via in report.candidate.vias
        ],
    )
    return (
        [
            _route_report_from_candidate(
                board,
                candidate,
                report.strategy,
                committed=False,
                message="; ".join(v.message for v in failed_violations[:3]),
                route_name=route_name,
                route_index=route_index,
                source=route_source,
                alternative_name=report.alternative_name,
            )
        ],
        failed_violations,
    )


def _escape_variable_values(raw: dict[str, Any]) -> list[float]:
    values = raw.get("values")
    if not isinstance(values, list) or not values:
        raise ValueError("escape_bundle variables currently require non-empty explicit values lists")
    return [
        parse_mm(value, field_name="escape_bundle variable value")
        for value in values
    ]


def _escape_variable_group(raw: dict[str, Any], key: str) -> tuple[list[str], list[list[float]]]:
    variables = raw.get(key) or {}
    if not isinstance(variables, dict):
        raise ValueError(f"escape_bundle {key} must be a mapping")
    names = [str(name) for name in variables]
    value_lists: list[list[float]] = []
    for name in names:
        variable = variables[name]
        if not isinstance(variable, dict):
            raise ValueError(f"escape_bundle {key}.{name} must be a mapping")
        if "range" in variable:
            raise ValueError("escape_bundle range variables are not supported in this slice; use values")
        value_lists.append(_escape_variable_values(variable))
    return names, value_lists


def _escape_assignments(raw: dict[str, Any]) -> list[_EscapeAssignment]:
    route_names, route_values = _escape_variable_group(raw, "variables")
    placement_names, placement_values = _escape_variable_group(raw, "placement_variables")
    fanout_names, fanout_values = _escape_variable_group(raw, "fanout_variables")
    all_lists = route_values + placement_values + fanout_values
    if not all_lists:
        return [_EscapeAssignment({}, {}, {})]
    candidate_count = math.prod(len(values) for values in all_lists)
    max_candidates = int((raw.get("search") or {}).get("max_candidates", MAX_ESCAPE_BUNDLE_CANDIDATES))
    max_candidates = min(max_candidates, MAX_ESCAPE_BUNDLE_CANDIDATES)
    if candidate_count > max_candidates:
        raise ValueError(
            "escape_bundle candidate assignments exceed "
            f"{max_candidates}: {candidate_count}"
        )
    assignments: list[_EscapeAssignment] = []
    for values in itertools.product(*all_lists):
        offset = 0
        route_count = len(route_names)
        placement_count = len(placement_names)
        route_part = values[offset : offset + route_count]
        offset += route_count
        placement_part = values[offset : offset + placement_count]
        offset += placement_count
        fanout_part = values[offset:]
        assignments.append(
            _EscapeAssignment(
                dict(zip(route_names, route_part, strict=True)),
                dict(zip(placement_names, placement_part, strict=True)),
                dict(zip(fanout_names, fanout_part, strict=True)),
            )
        )
    return assignments


def _escape_symbol_value(token: str, assignment: dict[str, float]) -> float:
    axis, _, name = token.partition(":")
    if axis not in {"x", "y"} or not name:
        raise ValueError(f"Unsupported escape_bundle symbolic point token {token!r}")
    if name not in assignment:
        raise ValueError(f"escape_bundle symbolic point token {token!r} has no variable assignment")
    return assignment[name]


def _substitute_escape_scalar(raw: Any, assignment: dict[str, float], *, field_name: str) -> float:
    if isinstance(raw, str) and raw.strip().startswith(("x:", "y:")):
        return _escape_symbol_value(raw.strip(), assignment)
    return parse_mm(raw, field_name=field_name)


def _substitute_escape_point(raw: Any, assignment: dict[str, float]) -> Any:
    if isinstance(raw, str):
        if raw.startswith(("x:", "y:")):
            return f"{_escape_symbol_value(raw, assignment)}mm"
        return raw
    if isinstance(raw, list):
        if len(raw) == 2 and any(isinstance(item, str) and item.startswith(("x:", "y:")) for item in raw):
            return [
                _substitute_escape_point(raw[0], assignment),
                _substitute_escape_point(raw[1], assignment),
            ]
        return [_substitute_escape_point(item, assignment) for item in raw]
    if isinstance(raw, dict):
        return {
            key: _substitute_escape_point(value, assignment)
            for key, value in raw.items()
        }
    return raw


_HELPER_REF_RE = re.compile(r"^(?:TP|FID|MH)\d+$")


def _escape_placement_moves(raw: dict[str, Any]) -> list[_EscapePlacementMove]:
    moves = raw.get("placement_moves") or []
    if not isinstance(moves, list):
        raise ValueError("escape_bundle placement_moves must be a list")
    result: list[_EscapePlacementMove] = []
    for index, move in enumerate(moves):
        if not isinstance(move, dict):
            raise ValueError(f"escape_bundle placement_moves[{index}] must be a mapping")
        name = str(move.get("name", f"placement_move_{index + 1}")).strip()
        refs_raw = move.get("refs")
        if not isinstance(refs_raw, list) or not refs_raw:
            raise ValueError(f"escape_bundle placement move {name} requires non-empty refs")
        refs = tuple(str(ref).strip() for ref in refs_raw)
        if any(not ref for ref in refs):
            raise ValueError(f"escape_bundle placement move {name} has an empty ref")
        helper_refs = [ref for ref in refs if _HELPER_REF_RE.match(ref)]
        if helper_refs and not move.get("allow_helper_movement", False):
            raise ValueError(
                "escape_bundle placement_moves cannot move generated helper refs by default: "
                + ", ".join(helper_refs)
            )
        rotate = move.get("rotate")
        if rotate not in (None, "", "0deg", "0", 0, 0.0):
            raise ValueError("escape_bundle placement_moves only support absent or 0deg rotate")
        result.append(
            _EscapePlacementMove(
                name=name,
                refs=refs,
                dx_token=move.get("dx", "0mm"),
                dy_token=move.get("dy", "0mm"),
                rotate_token=rotate,
                raw=move,
            )
        )
    return result


def _apply_escape_placement_moves(
    board: Board,
    moves: list[_EscapePlacementMove],
    assignment: dict[str, float],
) -> list[_EscapeAppliedMove]:
    applied: list[_EscapeAppliedMove] = []
    for move in moves:
        dx = _substitute_escape_scalar(
            move.dx_token, assignment, field_name=f"escape_bundle placement move {move.name} dx"
        )
        dy = _substitute_escape_scalar(
            move.dy_token, assignment, field_name=f"escape_bundle placement move {move.name} dy"
        )
        for ref in move.refs:
            comp = board.components.get(ref)
            if comp is None:
                raise ValueError(f"escape_bundle placement move {move.name} unknown ref {ref!r}")
            original = comp.position
            staged = (round(original[0] + dx, 4), round(original[1] + dy, 4))
            comp.position = staged
            applied.append(
                _EscapeAppliedMove(
                    name=move.name,
                    ref=ref,
                    original_position=original,
                    staged_position=staged,
                    dx=dx,
                    dy=dy,
                    rotation=None,
                )
            )
    return applied


def _placement_move_payload(applied: list[_EscapeAppliedMove]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "name": move.name,
            "ref": move.ref,
            "original_position": move.original_position,
            "staged_position": move.staged_position,
            "dx": move.dx,
            "dy": move.dy,
        }
        for move in applied
    )


def _escape_fanout_templates(raw: dict[str, Any]) -> list[_EscapeFanoutTemplate]:
    templates = raw.get("fanout_templates") or []
    if not isinstance(templates, list):
        raise ValueError("escape_bundle fanout_templates must be a list")
    result: list[_EscapeFanoutTemplate] = []
    for index, template in enumerate(templates):
        if not isinstance(template, dict):
            raise ValueError(f"escape_bundle fanout_templates[{index}] must be a mapping")
        name = str(template.get("name", f"fanout_template_{index + 1}")).strip()
        ref = str(template.get("ref", "")).strip()
        pin = str(template.get("pin", "")).strip()
        net = str(template.get("net", "")).strip()
        if not ref or not pin or not net:
            raise ValueError(f"escape_bundle fanout template {name} requires ref, pin, and net")
        points = template.get("points")
        if not isinstance(points, list):
            raise ValueError(f"escape_bundle fanout template {name} requires points")
        result.append(
            _EscapeFanoutTemplate(
                name=name,
                ref=ref,
                pin=pin,
                net=net,
                start_layer=str(template.get("start_layer") or template.get("layer") or "F.Cu"),
                points=points,
                raw=template,
            )
        )
    return result


def _compile_escape_fanout_template(
    board: Board,
    template: _EscapeFanoutTemplate,
    assignment: dict[str, float],
) -> RouteCandidate:
    pad_token = f"{template.ref}.{template.pin}"
    raw_points = [pad_token, *template.points]
    return _compile_layered_polyline(
        board,
        template.net,
        [_substitute_escape_point(point, assignment) for point in raw_points],
        template.start_layer,
    )


def _compile_escape_template(
    board: Board,
    template: dict[str, Any],
    assignment: dict[str, float],
) -> RouteCandidate:
    template_name = str(template.get("name", "")).strip()
    net_name = str(template.get("net", "")).strip()
    if not net_name:
        raise ValueError(f"escape_bundle template {template_name or '<unnamed>'} requires net")
    start_layer = str(template.get("start_layer") or template.get("layer") or "F.Cu")
    points = template.get("points")
    if not isinstance(points, list):
        raise ValueError(f"escape_bundle template {template_name or net_name} requires points")
    return _compile_layered_polyline(
        board,
        net_name,
        [_substitute_escape_point(point, assignment) for point in points],
        start_layer,
    )


def _escape_templates(raw: dict[str, Any]) -> list[dict[str, Any]]:
    templates = raw.get("templates")
    if not isinstance(templates, list) or len(templates) < 2:
        raise ValueError("escape_bundle requires at least two templates")
    seen_nets: set[str] = set()
    result: list[dict[str, Any]] = []
    for index, template in enumerate(templates):
        if not isinstance(template, dict):
            raise ValueError(f"escape_bundle templates[{index}] must be a mapping")
        name = str(template.get("name", f"template_{index + 1}")).strip()
        if not name:
            raise ValueError(f"escape_bundle templates[{index}].name must be non-empty")
        net_name = str(template.get("net", "")).strip()
        if not net_name:
            raise ValueError(f"escape_bundle template {name} requires net")
        seen_nets.add(net_name)
        merged = dict(template)
        merged["name"] = name
        result.append(merged)
    if len(seen_nets) < 2:
        raise ValueError("escape_bundle requires templates for at least two nets")
    return result


def _assignment_label(assignment: dict[str, float]) -> str:
    if not assignment:
        return ""
    return ",".join(f"{name}={value:g}mm" for name, value in sorted(assignment.items()))


def _parse_bool(value: Any, *, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError(f"{field_name} must be true or false")


def _parse_non_negative_int(value: Any, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _is_powerish_net(name: str) -> bool:
    normalized = re.sub(r"[^A-Z0-9]+", "", name.upper())
    return (
        normalized in {"GND", "GROUND", "VCC", "VDD", "VSS", "VBAT", "VIN", "VOUT"}
        or normalized.startswith(("GND", "VCC", "VDD", "VSS"))
        or normalized.endswith(("GND", "VCC", "VDD", "VSS"))
        or bool(re.fullmatch(r"[0-9]+V[0-9]*", normalized))
    )


def _parse_route_replacement(raw: dict[str, Any], route_name: str) -> _RouteReplacementIntent | None:
    replacement = raw.get("replace_existing")
    if replacement is None:
        return None
    if not isinstance(replacement, dict):
        raise ValueError(f"escape_bundle {route_name} replace_existing must be a mapping")
    nets_raw = replacement.get("nets") or []
    if not isinstance(nets_raw, list):
        raise ValueError(f"escape_bundle {route_name} replace_existing.nets must be a list")
    nets: list[str] = []
    seen_nets: set[str] = set()
    for net in nets_raw:
        net_name = str(net).strip()
        if not net_name:
            raise ValueError(f"escape_bundle {route_name} replace_existing.nets contains an empty net")
        if net_name in seen_nets:
            continue
        nets.append(net_name)
        seen_nets.add(net_name)
    refs_raw = replacement.get("refs") or []
    if not isinstance(refs_raw, list):
        raise ValueError(f"escape_bundle {route_name} replace_existing.refs must be a list")
    refs = tuple(str(ref).strip() for ref in refs_raw if str(ref).strip())
    if refs:
        raise ValueError(
            f"escape_bundle {route_name} replace_existing.refs is not supported in this slice"
        )
    return _RouteReplacementIntent(
        nets=tuple(nets),
        refs=refs,
        include_fanout=_parse_bool(
            replacement.get("include_fanout", True),
            field_name=f"escape_bundle {route_name} replace_existing.include_fanout",
        ),
        require_all_nets=_parse_bool(
            replacement.get("require_all_nets", True),
            field_name=f"escape_bundle {route_name} replace_existing.require_all_nets",
        ),
        max_removed_segments=_parse_non_negative_int(
            replacement.get("max_removed_segments", 64),
            field_name=f"escape_bundle {route_name} replace_existing.max_removed_segments",
        ),
        max_removed_vias=_parse_non_negative_int(
            replacement.get("max_removed_vias", 16),
            field_name=f"escape_bundle {route_name} replace_existing.max_removed_vias",
        ),
        allow_power_nets=_parse_bool(
            replacement.get("allow_power_nets", False),
            field_name=f"escape_bundle {route_name} replace_existing.allow_power_nets",
        ),
    )


def _validate_route_replacement(
    board: Board,
    intent: _RouteReplacementIntent | None,
    templates: list[dict[str, Any]],
    fanout_templates: list[_EscapeFanoutTemplate],
    route_name: str,
) -> None:
    if intent is None or not intent.nets:
        return
    missing = [net for net in intent.nets if net not in board.nets]
    if missing and intent.require_all_nets:
        raise ValueError(
            f"escape_bundle {route_name} replace_existing missing nets: {', '.join(missing)}"
        )
    if not intent.allow_power_nets:
        power_nets = [net for net in intent.nets if _is_powerish_net(net)]
        if power_nets:
            raise ValueError(
                f"escape_bundle {route_name} replace_existing refuses power nets by default: "
                + ", ".join(power_nets)
            )
    produced = {str(template.get("net", "")).strip() for template in templates}
    produced.update(template.net for template in fanout_templates)
    unproduced = [net for net in intent.nets if net in board.nets and net not in produced]
    if unproduced:
        raise ValueError(
            f"escape_bundle {route_name} replace_existing nets lack replacement templates: "
            + ", ".join(unproduced)
        )
    segment_count = sum(len(board.nets[net].segments) for net in intent.nets if net in board.nets)
    via_count = sum(len(board.nets[net].vias) for net in intent.nets if net in board.nets)
    if segment_count > intent.max_removed_segments:
        raise ValueError(
            f"escape_bundle {route_name} replace_existing would remove {segment_count} "
            f"segments, exceeding max_removed_segments={intent.max_removed_segments}"
        )
    if via_count > intent.max_removed_vias:
        raise ValueError(
            f"escape_bundle {route_name} replace_existing would remove {via_count} "
            f"vias, exceeding max_removed_vias={intent.max_removed_vias}"
        )


def _clear_replaced_net_geometry(
    board: Board, intent: _RouteReplacementIntent | None
) -> RouteReplacementReport | None:
    if intent is None or not intent.nets:
        return None
    by_net: list[dict[str, int | str]] = []
    total_segments = 0
    total_vias = 0
    for net_name in intent.nets:
        net = board.nets.get(net_name)
        if net is None:
            continue
        removed_segments = len(net.segments)
        removed_vias = len(net.vias)
        total_segments += removed_segments
        total_vias += removed_vias
        by_net.append(
            {
                "net": net_name,
                "removed_segments": removed_segments,
                "removed_vias": removed_vias,
            }
        )
        net.segments.clear()
        net.vias.clear()
    return RouteReplacementReport(
        nets=intent.nets,
        removed_segments=total_segments,
        removed_vias=total_vias,
        by_net=tuple(by_net),
    )


def _replay_escape_candidate(board: Board, candidate: RouteCandidate) -> None:
    board.nets[candidate.net].segments.extend(candidate.segments)
    board.nets[candidate.net].vias.extend(candidate.vias)


def _commit_escape_bundle(
    board: Board,
    raw: dict[str, Any],
    *,
    strict: bool,
    keepouts: list[KeepoutConstraint],
    route_name: str,
    route_index: int,
    route_source: str,
) -> tuple[list[RouteReportEntry], list[CommitViolation]]:
    templates = _escape_templates(raw)
    placement_moves = _escape_placement_moves(raw)
    fanout_templates = _escape_fanout_templates(raw)
    replacement_intent = _parse_route_replacement(raw, route_name)
    _validate_route_replacement(board, replacement_intent, templates, fanout_templates, route_name)
    failed_reports: list[RouteFailureReport] = []
    failed_violations: list[CommitViolation] = []

    for assignment in _escape_assignments(raw):
        assignment_values = assignment.merged
        staged_board = copy.deepcopy(board)
        replacement_report = _clear_replaced_net_geometry(staged_board, replacement_intent)
        staged_candidates: list[_EscapeBundleStagedCandidate] = []
        applied_moves = _apply_escape_placement_moves(
            staged_board, placement_moves, assignment_values
        )
        placement_payload = _placement_move_payload(applied_moves)
        assignment_valid = True

        for fanout_template in fanout_templates:
            candidate = _compile_escape_fanout_template(
                staged_board, fanout_template, assignment_values
            )
            violations = validate_route_candidate(staged_board, candidate, keepouts=keepouts)
            if violations:
                failed_violations.extend(violations)
                failed_reports.append(
                    _route_failure_report(
                        staged_board,
                        candidate,
                        "escape_bundle_fanout",
                        violations,
                        route_name=route_name,
                        route_index=route_index,
                        source=route_source,
                        alternative_name=_assignment_label(assignment_values),
                        template_name=fanout_template.name,
                        assignment=dict(assignment_values),
                        failed_stage="fanout_template",
                        placement_moves=placement_payload,
                        replacement_report=replacement_report,
                    )
                )
                assignment_valid = False
                break

            commit_route_candidate(staged_board, candidate, keepouts=keepouts)
            staged_candidates.append(
                _EscapeBundleStagedCandidate(
                    template_name=fanout_template.name,
                    assignment=dict(assignment_values),
                    candidate=candidate,
                    stage="fanout_template",
                )
            )

        if not assignment_valid:
            continue

        for template in templates:
            candidate = _compile_escape_template(staged_board, template, assignment_values)
            template_name = str(template["name"])
            violations = validate_route_candidate(staged_board, candidate, keepouts=keepouts)
            if violations:
                failed_violations.extend(violations)
                failed_reports.append(
                    _route_failure_report(
                        staged_board,
                        candidate,
                        "escape_bundle",
                        violations,
                        route_name=route_name,
                        route_index=route_index,
                        source=route_source,
                        alternative_name=_assignment_label(assignment_values),
                        template_name=template_name,
                        assignment=dict(assignment_values),
                        failed_stage="route_template",
                        placement_moves=placement_payload,
                        replacement_report=replacement_report,
                    )
                )
                assignment_valid = False
                break

            commit_route_candidate(staged_board, candidate, keepouts=keepouts)
            staged_candidates.append(
                _EscapeBundleStagedCandidate(
                    template_name=template_name,
                    assignment=dict(assignment_values),
                    candidate=candidate,
                )
            )

        if not assignment_valid:
            continue

        reports: list[RouteReportEntry] = []
        for move in applied_moves:
            board.components[move.ref].position = move.staged_position
        real_replacement_report = _clear_replaced_net_geometry(board, replacement_intent)
        for staged in staged_candidates:
            _replay_escape_candidate(board, staged.candidate)
            reports.append(
                _route_report_from_candidate(
                    board,
                    staged.candidate,
                    "escape_bundle_fanout" if staged.stage == "fanout_template" else "escape_bundle",
                    committed=True,
                    route_name=route_name,
                    route_index=route_index,
                    source=route_source,
                    alternative_name=f"{staged.template_name}:{_assignment_label(staged.assignment)}",
                    replacement_report=real_replacement_report,
                )
            )
        return reports, []

    if not failed_reports:
        raise ValueError("escape_bundle produced no candidate assignments")
    if strict:
        report = failed_reports[-1]
        raise RouteCommitFailureError(report, failed_violations, reports=failed_reports)

    report = failed_reports[-1]
    candidate = RouteCandidate(
        report.net,
        [
            TraceSegment(
                net_name=report.net,
                start=segment.start,
                end=segment.end,
                layer=segment.layer,
                width=segment.width,
            )
            for segment in report.candidate.segments
        ],
        [
            Via(
                net_name=report.net,
                position=via.position,
                size=via.size,
                drill=via.drill,
                layers=via.layers,
                via_type=via.via_type,
            )
            for via in report.candidate.vias
        ],
    )
    return (
        [
            _route_report_from_candidate(
                board,
                candidate,
                report.strategy,
                committed=False,
                message="; ".join(v.message for v in failed_violations[:3]),
                route_name=route_name,
                route_index=route_index,
                source=route_source,
                alternative_name=report.alternative_name,
            )
        ],
        failed_violations,
    )


def _lane_value(raw: dict[str, Any], base_key: str, pitch_key: str, lane: int) -> float:
    return parse_mm(raw[base_key], field_name=f"header_bank.corridor.{base_key}") + lane * parse_mm(
        raw[pitch_key],
        field_name=f"header_bank.corridor.{pitch_key}",
    )


def _lane_index_for_net(
    spec_corridor: RouteCorridorIntent,
    net_name: str,
    lane_by_net: dict[str, int],
) -> int:
    if net_name in lane_by_net:
        return lane_by_net[net_name]

    for lane in spec_corridor.lanes.values():
        if net_name in lane.nets:
            return lane.index
    raise ValueError(f"header_bank corridor net {net_name!r} not assigned in lane metadata")


def _lane_by_net_mapping(raw: dict[str, Any], corridor_ref: str) -> dict[str, int]:
    lane_by_net: dict[str, int] = {}
    raw = raw.get("lane_by_net") or {}
    if not isinstance(raw, dict):
        raise ValueError("header_bank corridor lane_by_net must be a mapping when provided")

    for net_name, lane_index_raw in raw.items():
        net_name = str(net_name)
        try:
            lane_index = int(lane_index_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"header_bank corridor.ref {corridor_ref!r} lane_by_net.{net_name} must be an integer"
            ) from exc
        if lane_index < 0:
            raise ValueError(
                f"header_bank corridor.ref {corridor_ref!r} lane_by_net.{net_name} must be non-negative"
            )
        lane_by_net[net_name] = lane_index
    return lane_by_net


def _resolve_lane_for_corridor(
    route_corridors: dict[str, RouteCorridorIntent],
    raw: dict[str, Any],
    net_name: str,
) -> tuple[RouteCorridorIntent, int]:
    corridor = raw.get("corridor") or {}
    ref = corridor.get("ref")
    if ref is None:
        raise ValueError("header_bank corridor.ref is required when using named corridor generation")
    if not isinstance(ref, str) or not ref.strip():
        raise ValueError("header_bank corridor.ref must be a non-empty string")
    spec_corridor = route_corridors.get(ref)
    if spec_corridor is None:
        raise ValueError(f"header_bank corridor.ref {ref!r} does not match a defined route_corridor")

    lane_by_net = _lane_by_net_mapping(corridor, ref)
    lane = _lane_index_for_net(spec_corridor, net_name, lane_by_net)
    return spec_corridor, lane


def _corridor_lane_x_bounds(
    corridor: RouteCorridorIntent, lane: RouteCorridorLaneIntent | None
) -> tuple[float, float]:
    run_from_x = lane.run_from_x if lane is not None and lane.run_from_x is not None else corridor.run_from_x
    run_to_x = lane.run_to_x if lane is not None and lane.run_to_x is not None else corridor.run_to_x
    if run_from_x is None or run_to_x is None:
        raise ValueError(f"route_corridor {corridor.name!r} is missing run_from_x/run_to_x")
    return run_from_x, run_to_x


def _corridor_lane_y_bounds(
    corridor: RouteCorridorIntent, lane: RouteCorridorLaneIntent | None
) -> tuple[float, float]:
    run_from_y = lane.run_from_y if lane is not None and lane.run_from_y is not None else corridor.run_from_y
    run_to_y = lane.run_to_y if lane is not None and lane.run_to_y is not None else corridor.run_to_y
    if run_from_y is None or run_to_y is None:
        raise ValueError(f"route_corridor {corridor.name!r} is missing run_from_y/run_to_y")
    return run_from_y, run_to_y


def _header_bank_corridor_points(
    board: Board,
    raw: dict[str, Any],
    route_corridors: dict[str, RouteCorridorIntent],
    net_name: str,
    previous: Any,
) -> list[Any]:
    corridor = raw.get("corridor") or {}
    if not isinstance(corridor, dict):
        raise ValueError("header_bank corridor must be a mapping when provided")

    points: list[Any] = []
    spec_corridor: RouteCorridorIntent | None = None
    spec_lane = None
    if "ref" in corridor:
        spec_corridor, lane_index = _resolve_lane_for_corridor(route_corridors, raw, net_name)
        spec_lane = next(
            (lane for lane in spec_corridor.lanes.values() if lane.index == lane_index),
            None,
        )
        axis = spec_corridor.axis
    else:
        axis = str(corridor.get("axis", "x"))
        if axis not in {"x", "y"}:
            raise ValueError("header_bank corridor axis must be x or y")
        lane_from_nets = [str(net) for net in raw.get("nets") or []]
        if net_name not in lane_from_nets:
            raise ValueError(f"header_bank corridor net {net_name!r} is not listed in raw nets")
        lane_index = lane_from_nets.index(net_name)

    if spec_lane is not None:
        points.extend(_corridor_lane_route_points(spec_lane.pre_points))

    entry_by_net = corridor.get("entry_by_net") or {}
    if not isinstance(entry_by_net, dict):
        raise ValueError("header_bank corridor entry_by_net must be a mapping when provided")
    entry = entry_by_net.get(net_name, previous)

    if entry != previous:
        points.append(entry)
    via_at = corridor.get("via_at")
    if via_at is not None:
        if via_at != "entry":
            raise ValueError("header_bank corridor via_at must be 'entry' when provided")
        via_to_by_net = corridor.get("via_to_by_net") or {}
        if not isinstance(via_to_by_net, dict):
            raise ValueError("header_bank corridor via_to_by_net must be a mapping when provided")
        via_to = via_to_by_net.get(net_name, corridor.get("via_to"))
        if not isinstance(via_to, str) or not via_to:
            raise ValueError("header_bank corridor via_to is required when via_at is set")
        if via_to not in board.layers:
            raise ValueError(f"header_bank corridor via_to {via_to!r} is not in {board.layers}")
        via_point: dict[str, Any] = {"via": entry, "to": via_to}
        via_layers_by_net = corridor.get("via_layers_by_net") or {}
        if not isinstance(via_layers_by_net, dict):
            raise ValueError("header_bank corridor via_layers_by_net must be a mapping when provided")
        via_layers = via_layers_by_net.get(net_name, corridor.get("via_layers"))
        if via_layers is not None:
            if not isinstance(via_layers, list) or len(via_layers) < 2:
                raise ValueError("header_bank corridor via_layers must be a list of at least two layers")
            via_point["layers"] = via_layers
        points.append(via_point)

    if corridor.get("exit") == "direct":
        return points

    if spec_corridor is not None:
        lane_center = spec_corridor.lane_base + lane_index * spec_corridor.lane_pitch
        if spec_lane is not None:
            points.extend(_corridor_lane_route_points(spec_lane.entry_points))
        if axis == "x":
            run_from_x, run_to_x = _corridor_lane_x_bounds(spec_corridor, spec_lane)
            run_points = [
                [f"{run_from_x}mm", f"{lane_center}mm"],
                [f"{run_to_x}mm", f"{lane_center}mm"],
            ]
        else:
            run_from_y, run_to_y = _corridor_lane_y_bounds(spec_corridor, spec_lane)
            run_points = [
                [f"{lane_center}mm", f"{run_from_y}mm"],
                [f"{lane_center}mm", f"{run_to_y}mm"],
            ]
        points.extend(run_points)
        if spec_lane is not None:
            points.extend(_corridor_lane_route_points(spec_lane.exit_points))
        return points

    if axis == "x":
        run_x = parse_mm(corridor["run_to_x"], field_name="header_bank.corridor.run_to_x")
        exit_x = parse_mm(corridor["exit_x"], field_name="header_bank.corridor.exit_x")
        run_y = _lane_value(
            corridor,
            "run_base",
            "run_lane_pitch",
            lane_index,
        )
        exit_y = _lane_value(
            corridor,
            "exit_base",
            "exit_lane_pitch",
            lane_index,
        )
        points.append([f"{run_x}mm", f"{run_y}mm"])
        if abs(exit_y - run_y) > 1e-9:
            points.append([f"{run_x}mm", f"{exit_y}mm"])
        points.append([f"{exit_x}mm", f"{exit_y}mm"])
    else:
        run_y = parse_mm(corridor["run_to_y"], field_name="header_bank.corridor.run_to_y")
        exit_y = parse_mm(corridor["exit_y"], field_name="header_bank.corridor.exit_y")
        run_x = _lane_value(
            corridor,
            "run_base",
            "run_lane_pitch",
            lane_index,
        )
        exit_x = _lane_value(
            corridor,
            "exit_base",
            "exit_lane_pitch",
            lane_index,
        )
        points.append([f"{run_x}mm", f"{run_y}mm"])
        if abs(exit_x - run_x) > 1e-9:
            points.append([f"{exit_x}mm", f"{run_y}mm"])
        points.append([f"{exit_x}mm", f"{exit_y}mm"])
    return points


def _corridor_lane_route_points(raw_points: tuple[Any, ...]) -> list[Any]:
    points: list[Any] = []
    for raw_point in raw_points:
        if isinstance(raw_point, dict):
            points.append(dict(raw_point))
        elif (
            isinstance(raw_point, tuple)
            and len(raw_point) == 2
            and all(isinstance(value, int | float) for value in raw_point)
        ):
            points.append([f"{raw_point[0]}mm", f"{raw_point[1]}mm"])
        else:
            points.append(raw_point)
    return points


def _route_kind(raw: dict[str, Any]) -> str:
    return str(raw.get("kind") or raw.get("strategy") or "")


def _build_route_corridor_keepouts(route_corridors: dict[str, RouteCorridorIntent]) -> list[KeepoutConstraint]:
    keepouts: list[KeepoutConstraint] = []
    for corridor in route_corridors.values():
        axis = corridor.axis
        if axis == "x":
            width_y = corridor.lane_width + 2.0 * corridor.clearance
            for lane in corridor.lanes.values():
                run_from_x, run_to_x = _corridor_lane_x_bounds(corridor, lane)
                center_x = (run_from_x + run_to_x) / 2.0
                length = abs(run_to_x - run_from_x)
                base_size_x = length + 2.0 * corridor.clearance
                lane_center = corridor.lane_base + lane.index * corridor.lane_pitch
                keepouts.append(
                    KeepoutConstraint(
                        name=f"route_corridor.{corridor.name}.lane.{lane.name}",
                        layer=corridor.layer,
                        kind="route",
                        at=(center_x, lane_center),
                        size=(base_size_x, width_y),
                        allowed_nets=lane.nets,
                        source=_source_display(corridor.raw),
                    )
                )
        else:
            width_x = corridor.lane_width + 2.0 * corridor.clearance
            for lane in corridor.lanes.values():
                run_from_y, run_to_y = _corridor_lane_y_bounds(corridor, lane)
                center_y = (run_from_y + run_to_y) / 2.0
                length = abs(run_to_y - run_from_y)
                base_size_y = length + 2.0 * corridor.clearance
                lane_center = corridor.lane_base + lane.index * corridor.lane_pitch
                keepouts.append(
                    KeepoutConstraint(
                        name=f"route_corridor.{corridor.name}.lane.{lane.name}",
                        layer=corridor.layer,
                        kind="route",
                        at=(lane_center, center_y),
                        size=(width_x, base_size_y),
                        allowed_nets=lane.nets,
                        source=_source_display(corridor.raw),
                    )
                )
    return keepouts


def _validate_deferred_route(board: Board, raw: dict[str, Any]) -> None:
    net_name = raw.get("net")
    if net_name is not None and str(net_name) not in board.nets:
        raise ValueError(f"Unknown deferred route net {net_name!r}")
    for net_name in raw.get("nets") or []:
        if str(net_name) not in board.nets:
            raise ValueError(f"Unknown deferred route net {net_name!r}")


def _route_group_enabled(raw: dict[str, Any], enabled_groups: set[str] | None) -> bool:
    if enabled_groups is None:
        return True
    group = raw.get("group")
    if group is None:
        return True
    if isinstance(group, list):
        return any(str(item) in enabled_groups for item in group)
    return str(group) in enabled_groups


def _validate_route_group_group(group: Any) -> None:
    if isinstance(group, str):
        if not group.strip():
            raise ValueError("route_group group must be a non-empty string or list of non-empty strings")
        return
    if isinstance(group, list):
        if not group:
            raise ValueError("route_group group must be a non-empty string or list of non-empty strings")
        for item in group:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("route_group group must be a non-empty string or list of non-empty strings")
        return
    raise ValueError("route_group group must be a non-empty string or list of non-empty strings")


def _validate_route_group_library(library: Any) -> None:
    if not isinstance(library, dict):
        raise ValueError("route_group library must be a mapping when present")
    for key in ("entry_id", "pattern_family", "expanded_by"):
        if key in library and (not isinstance(library[key], str) or not library[key].strip()):
            raise ValueError(f"route_group library.{key} must be a non-empty string when present")
    if "catalog_schema_version" in library and library["catalog_schema_version"] != 1:
        raise ValueError("route_group library.catalog_schema_version must be integer 1 when present")
    if "parameters" in library and not isinstance(library["parameters"], dict):
        raise ValueError("route_group library.parameters must be a mapping when present")


def _validate_route_group(raw: dict[str, Any]) -> None:
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("route_group requires a non-empty name")
    if "schema_version" in raw and raw["schema_version"] != 1:
        raise ValueError("route_group schema_version must be integer 1 when present")
    if "group" in raw:
        _validate_route_group_group(raw["group"])
    if "description" in raw and not isinstance(raw["description"], str):
        raise ValueError("route_group description must be a string when present")
    if "library" in raw:
        _validate_route_group_library(raw["library"])


def apply_routes(
    board: Board,
    spec: PhysicalSpec,
    *,
    strict: bool = False,
    enabled_groups: set[str] | None = None,
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
            source=intent.raw.get("__pdl_source__").display()
            if intent.raw.get("__pdl_source__")
            else "",
        )
        for intent in spec.keepouts
    ]
    keepouts.extend(_build_route_corridor_keepouts(spec.route_corridors))
    for route_index, intent in enumerate(spec.routes):
        raw = intent.raw
        if not _route_group_enabled(raw, enabled_groups):
            continue
        kind = _route_kind(raw)
        route_name = _route_report_name(raw, route_index)
        route_source = _source_display(raw)
        if kind == "manual_polyline":
            candidate = _compile_manual_polyline(board, raw)
            report, failed = _commit(
                board,
                candidate,
                kind,
                strict=strict,
                keepouts=keepouts,
                route_name=route_name,
                route_index=route_index,
                source=route_source,
            )
            reports.append(report)
            violations.extend(failed)
        elif kind == "direct":
            if "nets" in raw:
                for net_name in raw["nets"]:
                    candidate = _compile_direct(board, raw, str(net_name))
                    report, failed = _commit(
                        board,
                        candidate,
                        kind,
                        strict=strict,
                        keepouts=keepouts,
                        route_name=route_name,
                        route_index=route_index,
                        source=route_source,
                    )
                    reports.append(report)
                    violations.extend(failed)
            else:
                candidate = _compile_direct(board, raw)
                report, failed = _commit(
                    board,
                    candidate,
                    kind,
                    strict=strict,
                    keepouts=keepouts,
                    route_name=route_name,
                    route_index=route_index,
                    source=route_source,
                )
                reports.append(report)
                violations.extend(failed)
        elif kind == "bus":
            nets = raw.get("nets") or []
            starts = raw.get("from") or []
            ends = raw.get("to") or []
            if not (len(nets) == len(starts) == len(ends)):
                raise ValueError("bus route requires equal length nets/from/to lists")
            layer = str(raw.get("layer") or raw.get("prefer_layer") or "F.Cu")
            for net_name, start, end in zip(nets, starts, ends):
                candidate = _candidate_from_points(
                    board,
                    str(net_name),
                    [resolve_point(board, start), resolve_point(board, end)],
                    layer,
                )
                report, failed = _commit(
                    board,
                    candidate,
                    kind,
                    strict=strict,
                    keepouts=keepouts,
                    route_name=route_name,
                    route_index=route_index,
                    source=route_source,
                )
                reports.append(report)
                violations.extend(failed)
        elif kind == "header_bank":
            nets = raw.get("nets") or []
            if not isinstance(nets, list) or not nets:
                raise ValueError("header_bank route requires a non-empty nets list")
            if len({str(net) for net in nets}) != len(nets):
                raise ValueError("header_bank route nets must not contain duplicates")
            if not raw.get("from_ref") or not raw.get("to_ref"):
                raise ValueError("header_bank route requires from_ref and to_ref")
            if "waypoints" in raw and not isinstance(raw.get("waypoints"), list):
                raise ValueError("header_bank waypoints must be a list when provided")
            if "corridor" in raw and not isinstance(raw.get("corridor"), dict):
                raise ValueError("header_bank corridor must be a mapping when provided")
            header_reports, failed = _commit_header_bank_bundle(
                board,
                spec,
                raw,
                [str(net_name) for net_name in nets],
                strict=strict,
                keepouts=keepouts,
                route_name=route_name,
                route_index=route_index,
                route_source=route_source,
            )
            reports.extend(header_reports)
            violations.extend(failed)
        elif kind == "escape_bundle":
            escape_reports, failed = _commit_escape_bundle(
                board,
                raw,
                strict=strict,
                keepouts=keepouts,
                route_name=route_name,
                route_index=route_index,
                route_source=route_source,
            )
            reports.extend(escape_reports)
            violations.extend(failed)
        elif kind == "route_group":
            _validate_route_group(raw)
            escape_reports, failed = _commit_escape_bundle(
                board,
                raw,
                strict=strict,
                keepouts=keepouts,
                route_name=route_name,
                route_index=route_index,
                route_source=route_source,
            )
            reports.extend(escape_reports)
            violations.extend(failed)
        elif kind in {"deferred", "unrouted", "airwire"}:
            _validate_deferred_route(board, raw)
        elif kind:
            raise ValueError(f"Unsupported route kind {kind!r}")
    return reports, violations
