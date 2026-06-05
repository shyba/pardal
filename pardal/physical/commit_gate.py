"""Structured pre-commit checks for physical route candidates."""

from __future__ import annotations

from dataclasses import dataclass, field
import math

from pardal.data_model import Board, CopperZone, TraceSegment, Via


GEOMETRY_EPSILON = 1e-9


@dataclass(frozen=True)
class RouteCandidate:
    net: str
    segments: list[TraceSegment]
    vias: list[Via] = field(default_factory=list)


@dataclass(frozen=True)
class CommitViolation:
    code: str
    message: str
    net: str | None = None
    layer: str | None = None
    source: str = ""
    distance: float | None = None


@dataclass(frozen=True)
class KeepoutConstraint:
    name: str
    layer: str
    kind: str
    at: tuple[float, float]
    size: tuple[float, float]
    allowed_nets: tuple[str, ...] = ()
    source: str = ""


class RouteCommitError(Exception):
    def __init__(self, violations: list[CommitViolation]):
        self.violations = violations
        super().__init__("; ".join(v.message for v in violations))


def _point_to_segment_distance(
    px: float, py: float, x1: float, y1: float, x2: float, y2: float
) -> float:
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    closest_x = x1 + t * dx
    closest_y = y1 + t * dy
    return math.hypot(px - closest_x, py - closest_y)


def _local_point(component, point: tuple[float, float]) -> tuple[float, float]:
    x = point[0] - component.position[0]
    y = point[1] - component.position[1]
    angle_rad = math.radians(component.rotation)
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    return (x * cos_a - y * sin_a, x * sin_a + y * cos_a)


def _point_to_rect_distance(
    point: tuple[float, float],
    center: tuple[float, float],
    size: tuple[float, float],
) -> float:
    dx = max(abs(point[0] - center[0]) - size[0] / 2.0, 0.0)
    dy = max(abs(point[1] - center[1]) - size[1] / 2.0, 0.0)
    return math.hypot(dx, dy)


def _segment_to_rect_distance(
    start: tuple[float, float],
    end: tuple[float, float],
    center: tuple[float, float],
    size: tuple[float, float],
) -> float:
    min_x = center[0] - size[0] / 2.0
    max_x = center[0] + size[0] / 2.0
    min_y = center[1] - size[1] / 2.0
    max_y = center[1] + size[1] / 2.0

    if (
        min_x <= start[0] <= max_x
        and min_y <= start[1] <= max_y
        or min_x <= end[0] <= max_x
        and min_y <= end[1] <= max_y
    ):
        return 0.0

    edges = [
        ((min_x, min_y), (max_x, min_y)),
        ((max_x, min_y), (max_x, max_y)),
        ((max_x, max_y), (min_x, max_y)),
        ((min_x, max_y), (min_x, min_y)),
    ]
    segment = TraceSegment("_probe", start, end, "F.Cu", 0.01)
    for edge_start, edge_end in edges:
        edge = TraceSegment("_probe", edge_start, edge_end, "F.Cu", 0.01)
        if _segments_intersect(segment, edge):
            return 0.0

    return min(
        _point_to_rect_distance(start, center, size),
        _point_to_rect_distance(end, center, size),
        *[
            _point_to_segment_distance(*corner, *start, *end)
            for corner in (
                (min_x, min_y),
                (max_x, min_y),
                (max_x, max_y),
                (min_x, max_y),
            )
        ],
    )


def _orientation(a, b, c) -> int:
    val = (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1])
    if abs(val) < GEOMETRY_EPSILON:
        return 0
    return 1 if val > 0 else 2


def _on_segment(a, b, c) -> bool:
    return (
        min(a[0], c[0]) - GEOMETRY_EPSILON <= b[0] <= max(a[0], c[0]) + GEOMETRY_EPSILON
        and min(a[1], c[1]) - GEOMETRY_EPSILON <= b[1] <= max(a[1], c[1]) + GEOMETRY_EPSILON
    )


def _segments_intersect(seg1: TraceSegment, seg2: TraceSegment) -> bool:
    p1, q1 = seg1.start, seg1.end
    p2, q2 = seg2.start, seg2.end
    o1 = _orientation(p1, q1, p2)
    o2 = _orientation(p1, q1, q2)
    o3 = _orientation(p2, q2, p1)
    o4 = _orientation(p2, q2, q1)
    if o1 != o2 and o3 != o4:
        return True
    return (
        (o1 == 0 and _on_segment(p1, p2, q1))
        or (o2 == 0 and _on_segment(p1, q2, q1))
        or (o3 == 0 and _on_segment(p2, p1, q2))
        or (o4 == 0 and _on_segment(p2, q1, q2))
    )


def _segment_distance(seg1: TraceSegment, seg2: TraceSegment) -> float:
    if _segments_intersect(seg1, seg2):
        return 0.0
    return min(
        _point_to_segment_distance(*seg1.start, *seg2.start, *seg2.end),
        _point_to_segment_distance(*seg1.end, *seg2.start, *seg2.end),
        _point_to_segment_distance(*seg2.start, *seg1.start, *seg1.end),
        _point_to_segment_distance(*seg2.end, *seg1.start, *seg1.end),
    )


def _polygon_edges(
    polygon: list[tuple[float, float]],
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    if len(polygon) < 2:
        return []
    return list(zip(polygon, polygon[1:] + polygon[:1]))


def _segment_to_polygon_boundary_distance(
    start: tuple[float, float],
    end: tuple[float, float],
    polygon: list[tuple[float, float]],
) -> float:
    if len(polygon) < 3:
        return math.inf

    probe = TraceSegment("_probe", start, end, "F.Cu", 0.01)
    distances: list[float] = []
    for edge_start, edge_end in _polygon_edges(polygon):
        edge = TraceSegment("_probe", edge_start, edge_end, "F.Cu", 0.01)
        if _segments_intersect(probe, edge):
            return 0.0
        distances.append(_segment_distance(probe, edge))

    return min(distances, default=math.inf)


def _point_to_polygon_boundary_distance(
    point: tuple[float, float],
    polygon: list[tuple[float, float]],
) -> float:
    if len(polygon) < 3:
        return math.inf
    return min(
        (
            _point_to_segment_distance(*point, *edge_start, *edge_end)
            for edge_start, edge_end in _polygon_edges(polygon)
        ),
        default=math.inf,
    )


def _via_layers_overlap(via: Via, segment: TraceSegment) -> bool:
    return segment.layer in via.layers


def _via_spans_layer(board: Board, via: Via, layer: str) -> bool:
    if layer in via.layers:
        return True
    try:
        layer_index = board.layers.index(layer)
        via_indices = [board.layers.index(via_layer) for via_layer in via.layers]
    except ValueError:
        return False
    return min(via_indices) <= layer_index <= max(via_indices)


def _pad_net_map(board: Board) -> dict[tuple[str, str], str]:
    result = {}
    for net_name, net in board.nets.items():
        for ref, pin in net.connections:
            result[(ref, str(pin))] = net_name
    return result


def _clearance(board: Board, net_a: str, net_b: str | None = None) -> float:
    clearance = board.get_net_clearance(net_a)
    if net_b:
        clearance = max(clearance, board.get_net_clearance(net_b))
    return clearance


def _zone_clearance(board: Board, candidate_net: str, zone: CopperZone) -> float:
    return max(zone.clearance, _clearance(board, candidate_net, zone.net_name))


def _check_zones(board: Board, candidate: RouteCandidate) -> list[CommitViolation]:
    violations: list[CommitViolation] = []
    for segment in candidate.segments:
        half_width = segment.width / 2.0
        for zone in board.zones:
            if zone.layer != segment.layer or zone.net_name == candidate.net:
                continue
            dist = _segment_to_polygon_boundary_distance(
                segment.start,
                segment.end,
                zone.outline,
            )
            actual = dist - half_width
            required = _zone_clearance(board, candidate.net, zone)
            if actual < required - GEOMETRY_EPSILON:
                violations.append(
                    CommitViolation(
                        code="track_to_zone_clearance",
                        message=(
                            f"{candidate.net} segment on {segment.layer} is {actual:.3f}mm "
                            f"from {zone.net_name} zone; requires {required:.3f}mm"
                        ),
                        net=candidate.net,
                        layer=segment.layer,
                        source=zone.net_name,
                        distance=actual,
                    )
                )

    for via in candidate.vias:
        via_radius = via.size / 2.0
        for zone in board.zones:
            if zone.net_name == candidate.net or not _via_spans_layer(board, via, zone.layer):
                continue
            dist = _point_to_polygon_boundary_distance(via.position, zone.outline)
            actual = dist - via_radius
            required = _zone_clearance(board, candidate.net, zone)
            if actual < required - GEOMETRY_EPSILON:
                violations.append(
                    CommitViolation(
                        code="via_to_zone_clearance",
                        message=(
                            f"{candidate.net} via is {actual:.3f}mm from {zone.net_name} "
                            f"zone on {zone.layer}; requires {required:.3f}mm"
                        ),
                        net=candidate.net,
                        layer=zone.layer,
                        source=zone.net_name,
                        distance=actual,
                    )
                )
    return violations


def _check_keepouts(
    candidate: RouteCandidate,
    keepouts: list[KeepoutConstraint],
) -> list[CommitViolation]:
    violations: list[CommitViolation] = []
    for segment in candidate.segments:
        half_width = segment.width / 2.0
        for keepout in keepouts:
            if keepout.layer != segment.layer or keepout.kind not in {"route", "copper"}:
                continue
            if keepout.allowed_nets and candidate.net in keepout.allowed_nets:
                continue
            dist = _segment_to_rect_distance(
                segment.start,
                segment.end,
                keepout.at,
                keepout.size,
            )
            actual = dist - half_width
            if actual < 0:
                source = f" @ {keepout.source}" if keepout.source else ""
                violations.append(
                    CommitViolation(
                        code="route_keepout_violation",
                        message=(
                            f"{candidate.net} segment on {segment.layer} intersects "
                            f"keepout {keepout.name}{source}"
                        ),
                        net=candidate.net,
                        layer=segment.layer,
                        source=keepout.source,
                        distance=actual,
                    )
                )

    for via in candidate.vias:
        via_radius = via.size / 2.0
        for keepout in keepouts:
            if keepout.kind not in {"via", "copper"}:
                continue
            if keepout.allowed_nets and candidate.net in keepout.allowed_nets:
                continue
            if keepout.layer not in via.layers:
                continue
            dist = _point_to_rect_distance(via.position, keepout.at, keepout.size)
            actual = dist - via_radius
            if actual < 0:
                source = f" @ {keepout.source}" if keepout.source else ""
                violations.append(
                    CommitViolation(
                        code="via_keepout_violation",
                        message=(
                            f"{candidate.net} via on {keepout.layer} intersects "
                            f"keepout {keepout.name}{source}"
                        ),
                        net=candidate.net,
                        layer=keepout.layer,
                        source=keepout.source,
                        distance=actual,
                    )
                )
    return violations


def validate_route_candidate(
    board: Board,
    candidate: RouteCandidate,
    *,
    keepouts: list[KeepoutConstraint] | None = None,
) -> list[CommitViolation]:
    violations: list[CommitViolation] = []
    if candidate.net not in board.nets:
        return [
            CommitViolation(
                code="unknown_net",
                message=f"Route candidate references unknown net {candidate.net}",
                net=candidate.net,
            )
        ]

    pad_nets = _pad_net_map(board)

    for segment in candidate.segments:
        if segment.layer not in board.layers:
            violations.append(
                CommitViolation(
                    code="invalid_layer",
                    message=f"Segment for {candidate.net} uses layer {segment.layer}, not in {board.layers}",
                    net=candidate.net,
                    layer=segment.layer,
                )
            )
            continue

        half_width = segment.width / 2.0
        for label, point in (("start", segment.start), ("end", segment.end)):
            x, y = point
            if (
                x < half_width
                or y < half_width
                or x > board.width - half_width
                or y > board.height - half_width
            ):
                violations.append(
                    CommitViolation(
                        code="outside_board",
                        message=f"{candidate.net} segment {label} {point} is outside board outline",
                        net=candidate.net,
                        layer=segment.layer,
                    )
                )

        for comp_ref, component in board.components.items():
            for pad in component.pads:
                pad_net = pad_nets.get((comp_ref, str(pad.number)))
                if pad_net == candidate.net:
                    continue
                if not pad.is_tht and component.layer != segment.layer:
                    continue
                if pad.is_smd:
                    local_start = _local_point(component, segment.start)
                    local_end = _local_point(component, segment.end)
                    dist = _segment_to_rect_distance(
                        local_start,
                        local_end,
                        pad.position_offset,
                        pad.size,
                    )
                    actual = dist - half_width
                else:
                    pad_x, pad_y = component.get_pad_position(pad.number)
                    pad_radius = max(pad.size[0], pad.size[1]) / 2.0
                    dist = _point_to_segment_distance(
                        pad_x, pad_y, *segment.start, *segment.end
                    )
                    actual = dist - half_width - pad_radius
                required = _clearance(board, candidate.net, pad_net)
                if actual < required:
                    violations.append(
                        CommitViolation(
                            code="track_to_pad_clearance",
                            message=(
                                f"{candidate.net} segment on {segment.layer} is {actual:.3f}mm "
                                f"from {comp_ref}.{pad.number}; requires {required:.3f}mm"
                            ),
                            net=candidate.net,
                            layer=segment.layer,
                            distance=actual,
                        )
                    )

    for via in candidate.vias:
        via_radius = via.size / 2.0
        for layer in via.layers:
            if layer not in board.layers:
                violations.append(
                    CommitViolation(
                        code="invalid_layer",
                        message=f"Via for {candidate.net} uses layer {layer}, not in {board.layers}",
                        net=candidate.net,
                        layer=layer,
                    )
                )

        x, y = via.position
        if (
            x < via_radius
            or y < via_radius
            or x > board.width - via_radius
            or y > board.height - via_radius
        ):
            violations.append(
                CommitViolation(
                    code="outside_board",
                    message=f"{candidate.net} via at {via.position} is outside board outline",
                    net=candidate.net,
                )
            )

        for comp_ref, component in board.components.items():
            for pad in component.pads:
                pad_net = pad_nets.get((comp_ref, str(pad.number)))
                if pad_net == candidate.net:
                    continue
                if pad.is_smd and component.layer not in via.layers:
                    continue
                required = _clearance(board, candidate.net, pad_net)
                if pad.is_smd:
                    local_position = _local_point(component, via.position)
                    dist = _point_to_rect_distance(local_position, pad.position_offset, pad.size)
                    actual = dist - via_radius
                else:
                    pad_x, pad_y = component.get_pad_position(pad.number)
                    pad_radius = max(pad.size[0], pad.size[1]) / 2.0
                    dist = math.hypot(x - pad_x, y - pad_y)
                    actual = dist - via_radius - pad_radius
                if actual < required:
                    violations.append(
                        CommitViolation(
                            code="via_to_pad_clearance",
                            message=(
                                f"{candidate.net} via is {actual:.3f}mm from "
                                f"{comp_ref}.{pad.number}; requires {required:.3f}mm"
                            ),
                            net=candidate.net,
                            distance=actual,
                        )
                    )

    existing_segments = []
    existing_vias = []
    for net_name, net in board.nets.items():
        for segment in net.segments:
            existing_segments.append((net_name, segment))
        for via in net.vias:
            existing_vias.append((net_name, via))
    for via in candidate.vias:
        for other_net, segment in existing_segments:
            if other_net == candidate.net or not _via_layers_overlap(via, segment):
                continue
            dist = _point_to_segment_distance(*via.position, *segment.start, *segment.end)
            actual = dist - via.size / 2.0 - segment.width / 2.0
            required = _clearance(board, candidate.net, other_net)
            if actual < required:
                violations.append(
                    CommitViolation(
                        code="via_to_track_clearance",
                        message=(
                            f"{candidate.net} via is {actual:.3f}mm from {other_net} "
                            f"segment on {segment.layer}; requires {required:.3f}mm"
                        ),
                        net=candidate.net,
                        layer=segment.layer,
                        distance=actual,
                    )
                )
    for idx, seg1 in enumerate(candidate.segments):
        peer_segments = existing_segments + [
            (candidate.net, seg2)
            for j, seg2 in enumerate(candidate.segments)
            if j > idx
        ]
        for other_net, seg2 in peer_segments:
            if other_net == candidate.net or seg1.layer != seg2.layer:
                continue
            dist = _segment_distance(seg1, seg2)
            actual = dist - seg1.width / 2.0 - seg2.width / 2.0
            required = _clearance(board, candidate.net, other_net)
            if actual < required:
                violations.append(
                    CommitViolation(
                        code="track_to_track_clearance",
                        message=(
                            f"{candidate.net} segment on {seg1.layer} is {actual:.3f}mm "
                            f"from {other_net}; requires {required:.3f}mm"
                            ),
                            net=candidate.net,
                            layer=seg1.layer,
                            distance=actual,
                        )
                    )

        via_peers = existing_vias + [(candidate.net, via) for via in candidate.vias]
        for other_net, via in via_peers:
            if other_net == candidate.net or not _via_layers_overlap(via, seg1):
                continue
            dist = _point_to_segment_distance(*via.position, *seg1.start, *seg1.end)
            actual = dist - seg1.width / 2.0 - via.size / 2.0
            required = _clearance(board, candidate.net, other_net)
            if actual < required:
                violations.append(
                    CommitViolation(
                        code="track_to_via_clearance",
                        message=(
                            f"{candidate.net} segment on {seg1.layer} is {actual:.3f}mm "
                            f"from {other_net} via; requires {required:.3f}mm"
                            ),
                            net=candidate.net,
                            layer=seg1.layer,
                            distance=actual,
                        )
                    )

    for idx, via1 in enumerate(candidate.vias):
        via_peers = existing_vias + [
            (candidate.net, via2)
            for j, via2 in enumerate(candidate.vias)
            if j > idx
        ]
        for other_net, via2 in via_peers:
            if other_net == candidate.net or set(via1.layers).isdisjoint(via2.layers):
                continue
            dist = math.hypot(
                via1.position[0] - via2.position[0],
                via1.position[1] - via2.position[1],
            )
            actual = dist - via1.size / 2.0 - via2.size / 2.0
            required = _clearance(board, candidate.net, other_net)
            if actual < required:
                violations.append(
                    CommitViolation(
                        code="via_to_via_clearance",
                        message=(
                            f"{candidate.net} via is {actual:.3f}mm from {other_net} via; "
                            f"requires {required:.3f}mm"
                            ),
                            net=candidate.net,
                            distance=actual,
                        )
                    )
    if keepouts:
        violations.extend(_check_keepouts(candidate, keepouts))
    violations.extend(_check_zones(board, candidate))
    return violations


def commit_route_candidate(
    board: Board,
    candidate: RouteCandidate,
    *,
    keepouts: list[KeepoutConstraint] | None = None,
) -> None:
    violations = validate_route_candidate(board, candidate, keepouts=keepouts)
    if violations:
        raise RouteCommitError(violations)
    board.nets[candidate.net].segments.extend(candidate.segments)
    board.nets[candidate.net].vias.extend(candidate.vias)
