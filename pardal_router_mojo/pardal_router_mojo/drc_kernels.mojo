from collections import List

from .geometry import AABB, Circle, Segment, Vec2, dist_segment_segment2, dist_point_segment2, dist_segment_polygon2
from .spatial_index import SpatialSegmentIndex


@fieldwise_init
struct Violation(Copyable, Movable):
    var kind: Int  # 0=clearance, 1=short
    var a: Int
    var b: Int
    var dist2: Float64


fn _expand_aabb(bb: AABB, r: Float64) -> AABB:
    return AABB(bb.min_x - r, bb.min_y - r, bb.max_x + r, bb.max_y + r)


fn check_segment_clearance(
    *,
    index: SpatialSegmentIndex,
    seg: Segment,
    clearance: Float64,
    self_id: Int,
) -> List[Violation]:
    var out = List[Violation]()
    var bb = _expand_aabb(seg.aabb(), clearance)
    var cand = index.query_aabb(bb)
    var clr2 = clearance * clearance
    for sid in cand:
        if sid == self_id:
            continue
        var other = index.segs[sid].copy()
        var d2 = dist_segment_segment2(seg.a, seg.b, other.a, other.b)
        if d2 <= clr2:
            out.append(Violation(0, self_id, sid, d2))
    return out^


fn check_circle_segment_clearance(
    *,
    seg: Segment,
    circle: Circle,
    clearance: Float64,
) -> Bool:
    # True if violation exists.
    var r = circle.r + clearance
    return dist_point_segment2(circle.c, seg.a, seg.b) <= r * r


fn check_polygon_segment_clearance(
    *,
    seg: Segment,
    poly: List[Vec2],
    clearance: Float64,
) -> Bool:
    # True if violation exists.
    var d2 = dist_segment_polygon2(seg.a, seg.b, poly)
    return d2 <= clearance * clearance
