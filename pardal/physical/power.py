"""Power and plane intent compilation for physical specs."""

from __future__ import annotations

from typing import Any
import math

from pardal.data_model import Board, CopperZone, TraceSegment, Via
from pardal.physical.commit_gate import (
    CommitViolation,
    KeepoutConstraint,
    RouteCandidate,
    RouteCommitError,
    commit_route_candidate,
    validate_route_candidate,
)
from pardal.physical.routes import RouteReportEntry, route_layer_metadata
from pardal.physical.spec import PhysicalSpec, SOURCE_LOCATION_KEY, parse_mm


def _board_outline(board: Board, margin: float) -> list[tuple[float, float]]:
    return [
        (margin, margin),
        (board.width - margin, margin),
        (board.width - margin, board.height - margin),
        (margin, board.height - margin),
    ]


def apply_planes(board: Board, spec: PhysicalSpec) -> list[CopperZone]:
    zones: list[CopperZone] = []
    for plane in spec.planes:
        raw = plane.raw
        kind = str(raw.get("kind", "zone"))
        if kind != "zone":
            raise ValueError(f"Unsupported plane kind {kind!r}")
        if plane.net not in board.nets:
            raise ValueError(f"Plane references unknown net {plane.net!r}")
        if plane.layer not in board.layers:
            raise ValueError(f"Plane layer {plane.layer!r} is not in {board.layers}")

        outline_raw = raw.get("outline", "board")
        if outline_raw == "board":
            margin = parse_mm(raw.get("margin", "1.0mm"), field_name="plane.margin")
            outline = _board_outline(board, margin)
        else:
            raise ValueError(f"Unsupported plane outline {outline_raw!r}")

        zone = CopperZone(
            net_name=plane.net,
            net_code=board.nets[plane.net].code,
            layer=plane.layer,
            outline=outline,
            priority=int(raw.get("priority", 0)),
            clearance=parse_mm(raw.get("clearance", "0.25mm"), field_name="plane.clearance"),
            min_thickness=parse_mm(
                raw.get("min_thickness", "0.25mm"),
                field_name="plane.min_thickness",
            ),
            thermal_gap=parse_mm(
                raw.get("thermal_gap", "0.45mm"),
                field_name="plane.thermal_gap",
            ),
            thermal_bridge=parse_mm(
                raw.get("thermal_bridge", "0.35mm"),
                field_name="plane.thermal_bridge",
            ),
        )
        board.zones.append(zone)
        zones.append(zone)
    return zones


def _parse_xy(value: Any, *, field_name: str) -> tuple[float, float]:
    if not isinstance(value, list | tuple) or len(value) != 2:
        raise ValueError(f"{field_name} must be [x, y]")
    return (
        parse_mm(value[0], field_name=f"{field_name}[0]"),
        parse_mm(value[1], field_name=f"{field_name}[1]"),
    )


def _pad_point(board: Board, pad_ref: str) -> tuple[float, float]:
    try:
        ref, pin = pad_ref.split(".", 1)
    except ValueError as exc:
        raise ValueError(f"Expected pad reference like U1.4, got {pad_ref!r}") from exc
    comp = board.components.get(ref)
    if comp is None:
        raise ValueError(f"Unknown component reference {ref!r}")
    return comp.get_pad_position(pin)


def _refs_from(raw: dict[str, Any], key: str) -> list[str]:
    refs = raw.get(key) or {}
    if not isinstance(refs, dict) or not refs:
        if key == "refs":
            raise ValueError("power_stitch.refs must be a non-empty mapping")
        return []
    result = []
    for ref, pins in refs.items():
        if not isinstance(pins, list) or not pins:
            raise ValueError(f"power_stitch.{key}.{ref} must be a non-empty list")
        result.extend(f"{ref}.{pin}" for pin in pins)
    return result


def _pad_refs(raw: dict[str, Any]) -> list[str]:
    return _refs_from(raw, "refs")


def _deferred_pad_refs(raw: dict[str, Any]) -> list[str]:
    return _refs_from(raw, "deferred_refs")


def _validate_deferred_power_intent(board: Board, raw: dict[str, Any]) -> None:
    for pad_ref in _pad_refs(raw):
        _pad_point(board, pad_ref)


def _stitch_via_size(board: Board, net_name: str, raw: dict[str, Any]) -> tuple[float, float]:
    via_raw = raw.get("via") or {}
    if via_raw:
        return (
            parse_mm(via_raw.get("diameter"), field_name="power_stitch.via.diameter"),
            parse_mm(via_raw.get("drill"), field_name="power_stitch.via.drill"),
        )
    net = board.nets[net_name]
    if net.net_class and net.net_class in board.net_classes:
        net_class = board.net_classes[net.net_class]
        return net_class.via_size, net_class.via_drill
    return net.via_size, net.via_drill


def _report(
    board: Board,
    candidate: RouteCandidate,
    committed: bool,
    message: str = "",
    strategy: str = "power_stitch",
) -> RouteReportEntry:
    length = sum(math.dist(segment.start, segment.end) for segment in candidate.segments)
    return RouteReportEntry(
        net=candidate.net,
        strategy=strategy,
        segments=len(candidate.segments),
        vias=len(candidate.vias),
        length=length,
        committed=committed,
        message=message,
        **route_layer_metadata(board, candidate, committed=committed),
    )


def _candidate_for_pad(
    board: Board,
    net_name: str,
    layer: str,
    pad_ref: str,
    via_position: tuple[float, float],
    via_size: float,
    via_drill: float,
) -> RouteCandidate:
    pad_position = _pad_point(board, pad_ref)
    width = board.get_net_width(net_name)
    return RouteCandidate(
        net=net_name,
        segments=[
            TraceSegment(
                net_name=net_name,
                start=(round(pad_position[0], 4), round(pad_position[1], 4)),
                end=(round(via_position[0], 4), round(via_position[1], 4)),
                layer=layer,
                width=width,
            )
        ],
        vias=[
            Via(
                net_name=net_name,
                position=(round(via_position[0], 4), round(via_position[1], 4)),
                size=via_size,
                drill=via_drill,
                layers=tuple(board.layers),
                via_type="through",
            )
        ],
    )


def _direction_vector(direction: str) -> tuple[float, float]:
    return {
        "north": (0.0, -1.0),
        "south": (0.0, 1.0),
        "east": (1.0, 0.0),
        "west": (-1.0, 0.0),
    }[direction]


def _lateral_vector(direction: str) -> tuple[float, float]:
    dx, dy = _direction_vector(direction)
    return (-dy, dx)


def _outward_direction(board: Board, pad_ref: str) -> str:
    ref, _pin = pad_ref.split(".", 1)
    comp = board.components[ref]
    pad = _pad_point(board, pad_ref)
    dx = pad[0] - comp.position[0]
    dy = pad[1] - comp.position[1]
    if abs(dx) >= abs(dy):
        return "east" if dx >= 0 else "west"
    return "south" if dy >= 0 else "north"


def _auto_directions(board: Board, pad_ref: str, raw: dict[str, Any]) -> list[str]:
    auto = raw.get("auto") or {}
    directions_raw = auto.get("directions", ["outward", "north", "south", "east", "west"])
    if not isinstance(directions_raw, list) or not directions_raw:
        raise ValueError("power_stitch.auto.directions must be a non-empty list")
    result = []
    for item in directions_raw:
        direction = str(item)
        if direction == "outward":
            direction = _outward_direction(board, pad_ref)
        if direction not in {"north", "south", "east", "west"}:
            raise ValueError(f"Unsupported power_stitch auto direction {item!r}")
        if direction not in result:
            result.append(direction)
    return result


def _auto_distances(raw: dict[str, Any], key: str, default: list[str]) -> list[float]:
    auto = raw.get("auto") or {}
    values = auto.get(key, default)
    if not isinstance(values, list) or not values:
        raise ValueError(f"power_stitch.auto.{key} must be a non-empty list")
    return [
        parse_mm(value, field_name=f"power_stitch.auto.{key}")
        for value in values
    ]


def _auto_candidates(
    board: Board, pad_ref: str, raw: dict[str, Any]
) -> list[tuple[float, float]]:
    pad = _pad_point(board, pad_ref)
    offsets = _auto_distances(raw, "offsets", ["0.8mm", "1.2mm", "1.6mm", "2.0mm", "2.4mm"])
    laterals = _auto_distances(raw, "laterals", ["0mm", "0.25mm", "-0.25mm", "0.5mm", "-0.5mm"])
    candidates = []
    for direction in _auto_directions(board, pad_ref, raw):
        dx, dy = _direction_vector(direction)
        lx, ly = _lateral_vector(direction)
        for offset in offsets:
            for lateral in laterals:
                candidates.append((
                    pad[0] + dx * offset + lx * lateral,
                    pad[1] + dy * offset + ly * lateral,
                ))
    return candidates


def _commit_candidate(
    board: Board,
    candidate: RouteCandidate,
    *,
    strict: bool,
    keepouts: list[KeepoutConstraint] | None = None,
) -> tuple[RouteReportEntry, list[CommitViolation]]:
    try:
        commit_route_candidate(board, candidate, keepouts=keepouts)
        return _report(board, candidate, True), []
    except RouteCommitError as exc:
        if strict:
            raise
        message = "; ".join(v.message for v in exc.violations[:3])
        return _report(board, candidate, False, message), exc.violations


def _commit_auto_candidate(
    board: Board,
    net_name: str,
    layer: str,
    pad_ref: str,
    via_size: float,
    via_drill: float,
    raw: dict[str, Any],
    *,
    strict: bool,
    keepouts: list[KeepoutConstraint] | None = None,
) -> tuple[RouteReportEntry, list[CommitViolation]]:
    failures: list[CommitViolation] = []
    for via_position in _auto_candidates(board, pad_ref, raw):
        candidate = _candidate_for_pad(
            board,
            net_name,
            layer,
            pad_ref,
            via_position,
            via_size,
            via_drill,
        )
        try:
            commit_route_candidate(board, candidate, keepouts=keepouts)
            return _report(board, candidate, True, "auto-selected via"), []
        except RouteCommitError as exc:
            failures.extend(exc.violations)
            continue

    probe = _candidate_for_pad(
        board,
        net_name,
        layer,
        pad_ref,
        _pad_point(board, pad_ref),
        via_size,
        via_drill,
    )
    message = f"no legal auto stitch candidate for {pad_ref}"
    if strict:
        raise ValueError(message)
    return _report(board, probe, False, message), failures


def _failure_summary(violations: list[CommitViolation], limit: int = 3) -> str:
    messages = []
    for violation in violations:
        if violation.message not in messages:
            messages.append(violation.message)
        if len(messages) >= limit:
            break
    return "; ".join(messages)


def _probe_label(raw: dict[str, Any], pad_ref: str) -> str:
    name = raw.get("name")
    return f"{name} {pad_ref}" if name else pad_ref


def _probe_auto_candidate(
    board: Board,
    net_name: str,
    layer: str,
    pad_ref: str,
    via_size: float,
    via_drill: float,
    raw: dict[str, Any],
    keepouts: list[KeepoutConstraint] | None = None,
) -> RouteReportEntry:
    failures: list[CommitViolation] = []
    attempts = 0
    label = _probe_label(raw, pad_ref)
    for via_position in _auto_candidates(board, pad_ref, raw):
        attempts += 1
        candidate = _candidate_for_pad(
            board,
            net_name,
            layer,
            pad_ref,
            via_position,
            via_size,
            via_drill,
        )
        candidate_failures = validate_route_candidate(board, candidate, keepouts=keepouts)
        if not candidate_failures:
            via = candidate.vias[0]
            return _report(
                board,
                candidate,
                False,
                f"probe {label} found legal via at ({via.position[0]:.3f}, {via.position[1]:.3f}); not committed",
                strategy="power_probe",
            )
        failures.extend(candidate_failures)

    probe = _candidate_for_pad(
        board,
        net_name,
        layer,
        pad_ref,
        _pad_point(board, pad_ref),
        via_size,
        via_drill,
    )
    details = _failure_summary(failures)
    suffix = f": {details}" if details else ""
    return _report(
        board,
        probe,
        False,
        f"probe {label} found no legal auto stitch candidate after {attempts} candidate(s){suffix}",
        strategy="power_probe",
    )


def _probe_deferred_without_auto(
    board: Board,
    net_name: str,
    layer: str,
    pad_ref: str,
    via_size: float,
    via_drill: float,
    raw: dict[str, Any],
) -> RouteReportEntry:
    probe = _candidate_for_pad(
        board,
        net_name,
        layer,
        pad_ref,
        _pad_point(board, pad_ref),
        via_size,
        via_drill,
    )
    return _report(
        board,
        probe,
        False,
        f"probe {_probe_label(raw, pad_ref)} skipped: no auto block",
        strategy="power_probe",
    )


def apply_power_stitches(
    board: Board,
    spec: PhysicalSpec,
    *,
    strict: bool = False,
    probe_deferred: bool = False,
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
    for stitch in spec.power_stitches:
        raw = stitch.raw
        kind = str(raw.get("kind", "pad_vias"))
        if kind in {"deferred", "unrouted", "airwire"}:
            net_name = str(raw["net"])
            if net_name not in board.nets:
                raise ValueError(f"power_stitch references unknown net {net_name!r}")
            _validate_deferred_power_intent(board, raw)
            if probe_deferred:
                layer = str(raw.get("layer", "F.Cu"))
                if layer not in board.layers:
                    raise ValueError(f"power_stitch layer {layer!r} is not in {board.layers}")
                via_size, via_drill = _stitch_via_size(board, net_name, raw)
                for pad_ref in _pad_refs(raw):
                    if "auto" in raw:
                        reports.append(
                            _probe_auto_candidate(
                                board,
                                net_name,
                                layer,
                                pad_ref,
                                via_size,
                                via_drill,
                                raw,
                                keepouts=keepouts,
                            )
                        )
                    else:
                        reports.append(
                            _probe_deferred_without_auto(
                                board,
                                net_name,
                                layer,
                                pad_ref,
                                via_size,
                                via_drill,
                                raw,
                            )
                        )
            continue
        if kind != "pad_vias":
            raise ValueError(f"Unsupported power_stitch kind {kind!r}")
        net_name = str(raw["net"])
        if net_name not in board.nets:
            raise ValueError(f"power_stitch references unknown net {net_name!r}")
        layer = str(raw.get("layer", "F.Cu"))
        if layer not in board.layers:
            raise ValueError(f"power_stitch layer {layer!r} is not in {board.layers}")
        via_positions = raw.get("vias") or {}
        if not isinstance(via_positions, dict):
            raise ValueError("power_stitch.vias must be a mapping of pad refs to [x, y]")
        via_size, via_drill = _stitch_via_size(board, net_name, raw)
        for pad_ref in _deferred_pad_refs(raw):
            _pad_point(board, pad_ref)
        for pad_ref in _pad_refs(raw):
            if pad_ref not in via_positions:
                if "auto" not in raw:
                    raise ValueError(f"power_stitch missing via coordinate for {pad_ref}")
                report, failed = _commit_auto_candidate(
                    board,
                    net_name,
                    layer,
                    pad_ref,
                    via_size,
                    via_drill,
                    raw,
                    strict=strict,
                    keepouts=keepouts,
                )
                reports.append(report)
                violations.extend(failed)
                continue
            candidate = _candidate_for_pad(
                board,
                net_name,
                layer,
                pad_ref,
                _parse_xy(via_positions[pad_ref], field_name=f"power_stitch.vias.{pad_ref}"),
                via_size,
                via_drill,
            )
            report, failed = _commit_candidate(
                board,
                candidate,
                strict=strict,
                keepouts=keepouts,
            )
            reports.append(report)
            violations.extend(failed)
    return reports, violations
