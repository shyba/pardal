use crate::geom_nm::{
    dist2_circle_circle_nm, dist2_point_segment_nm_rational, point_within_segment_radius_nm, CircleNm, Nm, PointNm,
    SegmentNm,
};
use crate::board_nm::BoundaryNm;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DrcViolationKind {
    /// Copper from different nets overlaps (distance <= 0 after radii).
    Short,
    /// Copper from different nets is closer than required clearance.
    Clearance,
    /// Copper overlaps a keepout/restricted area.
    Keepout,
    /// Copper is outside the board outline or too close to it.
    Boundary,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ItemKind {
    Track,
    Via,
    Terminal,
    Keepout,
    Boundary,
    Area,
}

/// Clearance classification used by Specctra/Freerouting typed clearances, e.g. `wire_via`, `pin_pin`, `default_smd`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ClearanceKind {
    Wire,
    Via,
    /// Through-hole / multi-layer terminal.
    Pin,
    /// Single-layer terminal.
    Smd,
    /// Filled copper area (e.g., plane polygon).
    Area,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ItemRef {
    pub kind: ItemKind,
    pub index: usize,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DrcViolation {
    pub kind: DrcViolationKind,
    pub a: ItemRef,
    pub b: ItemRef,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TrackNm {
    pub net_id: u32,
    /// Clearance class id (0 = default/unknown).
    pub clearance_class: u32,
    pub layer: usize,
    pub seg: SegmentNm,
    /// Half-width (radius) of the copper shape around the centerline.
    pub r: Nm,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ViaNm {
    pub net_id: u32,
    /// Clearance class id (0 = default/unknown).
    pub clearance_class: u32,
    pub layers: (usize, usize),
    pub padstack: Option<String>,
    pub circle: CircleNm,
    /// Exact copper geometry for the via (per layer).
    ///
    /// This reuses `TerminalShapeNm` because DSN padstack primitives are identical for pads and vias.
    pub shapes: Vec<TerminalShapeNm>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TerminalNm {
    pub net_id: u32,
    /// Optional pin reference, e.g. `U1-1`, for applying per-pin rules.
    pub pin_ref: Option<String>,
    /// Clearance class id (0 = default/unknown).
    pub clearance_class: u32,
    pub layers: Vec<usize>,
    pub circle: CircleNm,
    /// Exact copper geometry for the terminal (per layer).
    pub shapes: Vec<TerminalShapeNm>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TerminalShapeNm {
    Circle { layer: usize, circle: CircleNm },
    Polygon { layer: usize, points: Vec<PointNm> },
    /// Polyline stroke with round caps; radius = width/2.
    Path { layer: usize, r: Nm, points: Vec<PointNm> },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum KeepoutShapeNm {
    Circle { circle: CircleNm },
    Polygon { points: Vec<PointNm> },
    /// Stroked polyline keepout with round caps; radius = width/2.
    Path { r: Nm, points: Vec<PointNm> },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum KeepoutAppliesTo {
    /// Applies to wires, vias, and terminals.
    All,
    /// Applies only to wires/tracks.
    Wire,
    /// Applies only to vias.
    Via,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct KeepoutNm {
    pub layers: Vec<usize>,
    pub applies_to: KeepoutAppliesTo,
    pub shape: KeepoutShapeNm,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AreaNm {
    pub net_id: u32,
    /// Clearance class id (0 = default/unknown).
    pub clearance_class: u32,
    pub layer: usize,
    pub polygon: Vec<PointNm>,
    /// Window polygons (holes) where the copper is absent.
    pub holes: Vec<Vec<PointNm>>,
}

fn sq_i128(v: i64) -> i128 {
    let v = v as i128;
    v * v
}

fn segments_intersect(a: PointNm, b: PointNm, c: PointNm, d: PointNm) -> bool {
    fn orient(a: PointNm, b: PointNm, c: PointNm) -> i128 {
        let abx = (b.x.0 - a.x.0) as i128;
        let aby = (b.y.0 - a.y.0) as i128;
        let acx = (c.x.0 - a.x.0) as i128;
        let acy = (c.y.0 - a.y.0) as i128;
        abx * acy - aby * acx
    }
    fn on_segment(a: PointNm, b: PointNm, p: PointNm) -> bool {
        let minx = a.x.0.min(b.x.0);
        let maxx = a.x.0.max(b.x.0);
        let miny = a.y.0.min(b.y.0);
        let maxy = a.y.0.max(b.y.0);
        p.x.0 >= minx && p.x.0 <= maxx && p.y.0 >= miny && p.y.0 <= maxy
    }

    let o1 = orient(a, b, c);
    let o2 = orient(a, b, d);
    let o3 = orient(c, d, a);
    let o4 = orient(c, d, b);

    if (o1 > 0 && o2 < 0 || o1 < 0 && o2 > 0) && (o3 > 0 && o4 < 0 || o3 < 0 && o4 > 0) {
        return true;
    }

    if o1 == 0 && on_segment(a, b, c) {
        return true;
    }
    if o2 == 0 && on_segment(a, b, d) {
        return true;
    }
    if o3 == 0 && on_segment(c, d, a) {
        return true;
    }
    if o4 == 0 && on_segment(c, d, b) {
        return true;
    }
    false
}

pub(crate) fn segments_within_radius_nm(s1: SegmentNm, s2: SegmentNm, r: Nm) -> bool {
    if segments_intersect(s1.a, s1.b, s2.a, s2.b) {
        return true;
    }
    point_within_segment_radius_nm(s1.a, s2, r)
        || point_within_segment_radius_nm(s1.b, s2, r)
        || point_within_segment_radius_nm(s2.a, s1, r)
        || point_within_segment_radius_nm(s2.b, s1, r)
}

pub(crate) fn circle_within_segment_radius_nm(c: CircleNm, s: SegmentNm, r: Nm) -> bool {
    let (numer, denom) = dist2_point_segment_nm_rational(c.center, s);
    let rr = (c.r.0 + r.0) as i64;
    let rr2 = sq_i128(rr);
    numer <= rr2 * denom
}

fn circles_within_radius_nm(a: CircleNm, b: CircleNm, r: Nm) -> bool {
    let rr = (a.r.0 + b.r.0 + r.0) as i64;
    dist2_circle_circle_nm(a, b) <= sq_i128(rr)
}

fn point_in_polygon_nm(p: PointNm, poly: &[PointNm]) -> bool {
    if poly.len() < 3 {
        return false;
    }
    let mut inside = false;
    let (px, py) = (p.x.0 as i128, p.y.0 as i128);
    let mut j = poly.len() - 1;
    for i in 0..poly.len() {
        let (ix, iy) = (poly[i].x.0 as i128, poly[i].y.0 as i128);
        let (jx, jy) = (poly[j].x.0 as i128, poly[j].y.0 as i128);
        let intersects = if (iy > py) != (jy > py) {
            // Compare `px < ix + (py - iy) * (jx - ix) / (jy - iy)` without division.
            // The denominator is non-zero due to the straddle check above.
            let dy = jy - iy;
            let lhs = (px - ix) * dy;
            let rhs = (py - iy) * (jx - ix);
            if dy > 0 {
                lhs < rhs
            } else {
                lhs > rhs
            }
        } else {
            false
        };
        if intersects {
            inside = !inside;
        }
        j = i;
    }
    inside
}

fn point_on_segment_nm(p: PointNm, a: PointNm, b: PointNm) -> bool {
    // Check colinearity and bounding box inclusion.
    let (px, py) = (p.x.0 as i128, p.y.0 as i128);
    let (ax, ay) = (a.x.0 as i128, a.y.0 as i128);
    let (bx, by) = (b.x.0 as i128, b.y.0 as i128);
    let cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax);
    if cross != 0 {
        return false;
    }
    let minx = ax.min(bx);
    let maxx = ax.max(bx);
    let miny = ay.min(by);
    let maxy = ay.max(by);
    px >= minx && px <= maxx && py >= miny && py <= maxy
}

fn point_in_polygon_or_on_edge_nm(p: PointNm, poly: &[PointNm]) -> bool {
    if point_in_polygon_nm(p, poly) {
        return true;
    }
    for e in polygon_edges(poly) {
        if point_on_segment_nm(p, e.a, e.b) {
            return true;
        }
    }
    false
}

fn polygon_edges(poly: &[PointNm]) -> impl Iterator<Item = SegmentNm> + '_ {
    poly.iter().copied().zip(poly.iter().copied().cycle().skip(1)).take(poly.len()).map(|(a, b)| SegmentNm { a, b })
}

fn terminal_shape_layer(s: &TerminalShapeNm) -> usize {
    match s {
        TerminalShapeNm::Circle { layer, .. } => *layer,
        TerminalShapeNm::Polygon { layer, .. } => *layer,
        TerminalShapeNm::Path { layer, .. } => *layer,
    }
}

pub(crate) fn terminal_shapes_on_layer<'a>(
    t: &'a TerminalNm,
    layer: usize,
) -> impl Iterator<Item = &'a TerminalShapeNm> + 'a {
    t.shapes.iter().filter(move |s| terminal_shape_layer(s) == layer)
}

fn via_shapes_on_layer<'a>(v: &'a ViaNm, layer: usize) -> impl Iterator<Item = &'a TerminalShapeNm> + 'a {
    v.shapes.iter().filter(move |s| terminal_shape_layer(s) == layer)
}

fn via_shapes_overlap_segment_extra_nm(v: &ViaNm, layer: usize, seg: SegmentNm, extra: Nm) -> bool {
    let mut any = false;
    for s in via_shapes_on_layer(v, layer) {
        any = true;
        if terminal_shape_within_segment_extra_nm(s, seg, extra) {
            return true;
        }
    }
    if any {
        return false;
    }
    // Fallback to bounding circle if no layer-specific shape exists.
    circle_within_segment_radius_nm(v.circle, seg, extra)
}

fn via_shapes_overlap_terminal_extra_nm(v: &ViaNm, t: &TerminalNm, layer: usize, extra: Nm) -> bool {
    let mut any_v = false;
    for sv in via_shapes_on_layer(v, layer) {
        any_v = true;
        for st in terminal_shapes_on_layer(t, layer) {
            if terminal_shapes_within_extra_nm(sv, st, extra) {
                return true;
            }
        }
    }
    if any_v {
        return false;
    }
    // Fallback: treat the via as its bounding circle.
    terminal_shapes_on_layer(t, layer).any(|st| terminal_shape_within_circle_extra_nm(st, v.circle, extra))
}

fn via_shapes_overlap_via_extra_nm(a: &ViaNm, b: &ViaNm, layer: usize, extra: Nm) -> bool {
    let mut any_a = false;
    for sa in via_shapes_on_layer(a, layer) {
        any_a = true;
        for sb in via_shapes_on_layer(b, layer) {
            if terminal_shapes_within_extra_nm(sa, sb, extra) {
                return true;
            }
        }
    }
    if any_a {
        return false;
    }
    circles_within_radius_nm(a.circle, b.circle, extra)
}

pub(crate) fn segment_within_polygon_radius_nm(seg: SegmentNm, poly: &[PointNm], r: Nm) -> bool {
    if point_in_polygon_nm(seg.a, poly) || point_in_polygon_nm(seg.b, poly) {
        return true;
    }
    for e in polygon_edges(poly) {
        if segments_within_radius_nm(seg, e, r) {
            return true;
        }
    }
    false
}

pub(crate) fn circle_within_polygon_extra_nm(circle: CircleNm, poly: &[PointNm], extra: Nm) -> bool {
    if point_in_polygon_nm(circle.center, poly) {
        return true;
    }
    let r = Nm(circle.r.0 + extra.0);
    for e in polygon_edges(poly) {
        if point_within_segment_radius_nm(circle.center, e, r) {
            return true;
        }
    }
    false
}

pub(crate) fn polygons_overlap_nm(a: &[PointNm], b: &[PointNm]) -> bool {
    if a.len() < 3 || b.len() < 3 {
        return false;
    }
    for ea in polygon_edges(a) {
        for eb in polygon_edges(b) {
            if segments_intersect(ea.a, ea.b, eb.a, eb.b) {
                return true;
            }
        }
    }
    point_in_polygon_nm(a[0], b) || point_in_polygon_nm(b[0], a)
}

pub(crate) fn polygons_within_radius_nm(a: &[PointNm], b: &[PointNm], r: Nm) -> bool {
    if polygons_overlap_nm(a, b) {
        return true;
    }
    if r.0 <= 0 {
        return false;
    }
    for ea in polygon_edges(a) {
        for eb in polygon_edges(b) {
            if segments_within_radius_nm(ea, eb, r) {
                return true;
            }
        }
    }
    false
}

pub(crate) fn segment_fully_inside_hole_nm(seg: SegmentNm, hole: &[PointNm], r_total: Nm) -> bool {
    if hole.len() < 3 {
        return false;
    }
    if !point_in_polygon_nm(seg.a, hole) || !point_in_polygon_nm(seg.b, hole) {
        return false;
    }
    if r_total.0 <= 0 {
        return true;
    }
    for e in polygon_edges(hole) {
        if segments_within_radius_nm(seg, e, r_total) {
            return false;
        }
    }
    true
}

pub(crate) fn circle_fully_inside_hole_nm(circle: CircleNm, hole: &[PointNm], extra: Nm) -> bool {
    if hole.len() < 3 {
        return false;
    }
    if !point_in_polygon_nm(circle.center, hole) {
        return false;
    }
    let r = Nm(circle.r.0.saturating_add(extra.0));
    if r.0 <= 0 {
        return true;
    }
    for e in polygon_edges(hole) {
        if point_within_segment_radius_nm(circle.center, e, r) {
            return false;
        }
    }
    true
}

pub(crate) fn terminal_shape_fully_inside_hole_nm(shape: &TerminalShapeNm, hole: &[PointNm], extra: Nm) -> bool {
    if hole.len() < 3 {
        return false;
    }
    match shape {
        TerminalShapeNm::Circle { circle, .. } => circle_fully_inside_hole_nm(*circle, hole, extra),
        TerminalShapeNm::Polygon { points, .. } => {
            if points.len() < 3 {
                return false;
            }
            if points.iter().any(|&p| !point_in_polygon_nm(p, hole)) {
                return false;
            }
            if extra.0 <= 0 {
                return true;
            }
            for ep in polygon_edges(points) {
                for eh in polygon_edges(hole) {
                    if segments_within_radius_nm(ep, eh, extra) {
                        return false;
                    }
                }
            }
            true
        }
        TerminalShapeNm::Path { r, points, .. } => {
            if points.len() < 2 {
                return false;
            }
            if points.iter().any(|&p| !point_in_polygon_nm(p, hole)) {
                return false;
            }
            let rr = Nm(r.0.saturating_add(extra.0));
            if rr.0 <= 0 {
                return true;
            }
            for w in points.windows(2) {
                let seg = SegmentNm { a: w[0], b: w[1] };
                for eh in polygon_edges(hole) {
                    if segments_within_radius_nm(seg, eh, rr) {
                        return false;
                    }
                }
            }
            true
        }
    }
}

pub(crate) fn terminal_shape_within_segment_extra_nm(
    shape: &TerminalShapeNm,
    seg: SegmentNm,
    extra: Nm,
) -> bool {
    match shape {
        TerminalShapeNm::Circle { circle, .. } => circle_within_segment_radius_nm(*circle, seg, extra),
        TerminalShapeNm::Polygon { points, .. } => segment_within_polygon_radius_nm(seg, points, extra),
        TerminalShapeNm::Path { r, points, .. } => {
            if points.len() < 2 {
                return false;
            }
            let rr = Nm(r.0 + extra.0);
            for w in points.windows(2) {
                let s2 = SegmentNm { a: w[0], b: w[1] };
                if segments_within_radius_nm(seg, s2, rr) {
                    return true;
                }
            }
            false
        }
    }
}

pub(crate) fn terminal_shape_within_circle_extra_nm(
    shape: &TerminalShapeNm,
    circle: CircleNm,
    extra: Nm,
) -> bool {
    match shape {
        TerminalShapeNm::Circle { circle: c, .. } => circles_within_radius_nm(circle, *c, extra),
        TerminalShapeNm::Polygon { points, .. } => circle_within_polygon_extra_nm(circle, points, extra),
        TerminalShapeNm::Path { r, points, .. } => {
            if points.len() < 2 {
                return false;
            }
            let rr = Nm(r.0 + extra.0);
            for w in points.windows(2) {
                let s2 = SegmentNm { a: w[0], b: w[1] };
                if circle_within_segment_radius_nm(circle, s2, rr) {
                    return true;
                }
            }
            false
        }
    }
}

fn terminal_shapes_within_extra_nm(a: &TerminalShapeNm, b: &TerminalShapeNm, extra: Nm) -> bool {
    match (a, b) {
        (TerminalShapeNm::Circle { circle: ca, .. }, TerminalShapeNm::Circle { circle: cb, .. }) => {
            circles_within_radius_nm(*ca, *cb, extra)
        }
        (TerminalShapeNm::Circle { circle, .. }, TerminalShapeNm::Polygon { points, .. })
        | (TerminalShapeNm::Polygon { points, .. }, TerminalShapeNm::Circle { circle, .. }) => {
            circle_within_polygon_extra_nm(*circle, points, extra)
        }
        (TerminalShapeNm::Circle { circle, .. }, TerminalShapeNm::Path { r, points, .. })
        | (TerminalShapeNm::Path { r, points, .. }, TerminalShapeNm::Circle { circle, .. }) => {
            if points.len() < 2 {
                return false;
            }
            let rr = Nm(r.0 + extra.0);
            for w in points.windows(2) {
                let s = SegmentNm { a: w[0], b: w[1] };
                if circle_within_segment_radius_nm(*circle, s, rr) {
                    return true;
                }
            }
            false
        }
        (TerminalShapeNm::Path { r: ra, points: pa, .. }, TerminalShapeNm::Path { r: rb, points: pb, .. }) => {
            if pa.len() < 2 || pb.len() < 2 {
                return false;
            }
            let rr = Nm(ra.0 + rb.0 + extra.0);
            for wa in pa.windows(2) {
                let sa = SegmentNm { a: wa[0], b: wa[1] };
                for wb in pb.windows(2) {
                    let sb = SegmentNm { a: wb[0], b: wb[1] };
                    if segments_within_radius_nm(sa, sb, rr) {
                        return true;
                    }
                }
            }
            false
        }
        (TerminalShapeNm::Path { r, points, .. }, TerminalShapeNm::Polygon { points: poly, .. })
        | (TerminalShapeNm::Polygon { points: poly, .. }, TerminalShapeNm::Path { r, points, .. }) => {
            if points.is_empty() {
                return false;
            }
            for p in points {
                if point_in_polygon_nm(*p, poly) {
                    return true;
                }
            }
            if points.len() < 2 {
                return false;
            }
            let rr = Nm(r.0 + extra.0);
            for w in points.windows(2) {
                let s = SegmentNm { a: w[0], b: w[1] };
                if segment_within_polygon_radius_nm(s, poly, rr) {
                    return true;
                }
            }
            false
        }
        (TerminalShapeNm::Polygon { points: pa, .. }, TerminalShapeNm::Polygon { points: pb, .. }) => {
            polygons_within_radius_nm(pa, pb, extra)
        }
    }
}

fn circle_violates_boundary_nm(circle: CircleNm, boundary: &[PointNm], clearance: Nm) -> bool {
    if boundary.len() < 3 {
        return false;
    }
    if !point_in_polygon_or_on_edge_nm(circle.center, boundary) {
        return true;
    }
    let required = Nm(circle.r.0.saturating_add(clearance.0));
    if required.0 <= 0 {
        return false;
    }
    polygon_edges(boundary).any(|e| point_within_segment_radius_nm(circle.center, e, required))
}

fn segment_violates_boundary_nm(seg: SegmentNm, boundary: &[PointNm], r_total: Nm) -> bool {
    if boundary.len() < 3 {
        return false;
    }
    if !point_in_polygon_or_on_edge_nm(seg.a, boundary) || !point_in_polygon_or_on_edge_nm(seg.b, boundary) {
        return true;
    }
    polygon_edges(boundary).any(|e| segments_within_radius_nm(seg, e, r_total))
}

fn polygon_violates_boundary_nm(poly: &[PointNm], boundary: &[PointNm], clearance: Nm) -> bool {
    if boundary.len() < 3 || poly.len() < 3 {
        return false;
    }
    if poly.iter().any(|&p| !point_in_polygon_or_on_edge_nm(p, boundary)) {
        return true;
    }
    if clearance.0 <= 0 {
        return false;
    }
    polygons_within_radius_nm(poly, boundary, clearance)
}

fn path_violates_boundary_nm(points: &[PointNm], boundary: &[PointNm], r: Nm, clearance: Nm) -> bool {
    if boundary.len() < 3 || points.len() < 2 {
        return false;
    }
    if points.iter().any(|&p| !point_in_polygon_or_on_edge_nm(p, boundary)) {
        return true;
    }
    let r_total = Nm(r.0.saturating_add(clearance.0));
    for w in points.windows(2) {
        let seg = SegmentNm { a: w[0], b: w[1] };
        if segment_violates_boundary_nm(seg, boundary, r_total) {
            return true;
        }
    }
    false
}

fn terminal_shape_violates_boundary_nm(shape: &TerminalShapeNm, boundary: &[PointNm], clearance: Nm) -> bool {
    match shape {
        TerminalShapeNm::Circle { circle, .. } => circle_violates_boundary_nm(*circle, boundary, clearance),
        TerminalShapeNm::Polygon { points, .. } => polygon_violates_boundary_nm(points, boundary, clearance),
        TerminalShapeNm::Path { r, points, .. } => path_violates_boundary_nm(points, boundary, *r, clearance),
    }
}

fn keepout_shape_violates_boundary_nm(shape: &KeepoutShapeNm, boundary: &[PointNm]) -> bool {
    match shape {
        KeepoutShapeNm::Circle { circle } => circle_violates_boundary_nm(*circle, boundary, Nm::zero()),
        KeepoutShapeNm::Polygon { points } => polygon_violates_boundary_nm(points, boundary, Nm::zero()),
        KeepoutShapeNm::Path { r, points } => path_violates_boundary_nm(points, boundary, *r, Nm::zero()),
    }
}

fn circle_violates_hole_nm(circle: CircleNm, hole: &[PointNm], clearance: Nm) -> bool {
    if hole.len() < 3 {
        return false;
    }
    if point_in_polygon_or_on_edge_nm(circle.center, hole) {
        return true;
    }
    let required = Nm(circle.r.0.saturating_add(clearance.0));
    if required.0 <= 0 {
        return false;
    }
    polygon_edges(hole).any(|e| point_within_segment_radius_nm(circle.center, e, required))
}

fn segment_violates_hole_nm(seg: SegmentNm, hole: &[PointNm], r_total: Nm) -> bool {
    if hole.len() < 3 {
        return false;
    }
    if point_in_polygon_or_on_edge_nm(seg.a, hole) || point_in_polygon_or_on_edge_nm(seg.b, hole) {
        return true;
    }
    polygon_edges(hole).any(|e| segments_within_radius_nm(seg, e, r_total))
}

fn polygon_violates_hole_nm(poly: &[PointNm], hole: &[PointNm], clearance: Nm) -> bool {
    if hole.len() < 3 || poly.len() < 3 {
        return false;
    }
    if poly.iter().any(|&p| point_in_polygon_or_on_edge_nm(p, hole)) {
        return true;
    }
    polygons_within_radius_nm(poly, hole, clearance)
}

fn path_violates_hole_nm(points: &[PointNm], hole: &[PointNm], r: Nm, clearance: Nm) -> bool {
    if hole.len() < 3 || points.len() < 2 {
        return false;
    }
    if points.iter().any(|&p| point_in_polygon_or_on_edge_nm(p, hole)) {
        return true;
    }
    let r_total = Nm(r.0.saturating_add(clearance.0));
    for w in points.windows(2) {
        let seg = SegmentNm { a: w[0], b: w[1] };
        if segment_violates_hole_nm(seg, hole, r_total) {
            return true;
        }
    }
    false
}

fn terminal_shape_violates_hole_nm(shape: &TerminalShapeNm, hole: &[PointNm], clearance: Nm) -> bool {
    match shape {
        TerminalShapeNm::Circle { circle, .. } => circle_violates_hole_nm(*circle, hole, clearance),
        TerminalShapeNm::Polygon { points, .. } => polygon_violates_hole_nm(points, hole, clearance),
        TerminalShapeNm::Path { r, points, .. } => path_violates_hole_nm(points, hole, *r, clearance),
    }
}

fn keepout_shape_violates_hole_nm(shape: &KeepoutShapeNm, hole: &[PointNm]) -> bool {
    match shape {
        KeepoutShapeNm::Circle { circle } => circle_violates_hole_nm(*circle, hole, Nm::zero()),
        KeepoutShapeNm::Polygon { points } => polygon_violates_hole_nm(points, hole, Nm::zero()),
        KeepoutShapeNm::Path { r, points } => path_violates_hole_nm(points, hole, *r, Nm::zero()),
    }
}

pub fn drc_check_boundary_nm(
    tracks: &[TrackNm],
    vias: &[ViaNm],
    terminals: &[TerminalNm],
    keepouts: &[KeepoutNm],
    boundary: &BoundaryNm,
    clearance_to_boundary: Nm,
) -> Vec<DrcViolation> {
    let mut out: Vec<DrcViolation> = Vec::new();
    let boundary_ref = ItemRef {
        kind: ItemKind::Boundary,
        index: 0,
    };

    let outer = boundary.outer.as_slice();
    for (i, t) in tracks.iter().enumerate() {
        let r_total = Nm(t.r.0.saturating_add(clearance_to_boundary.0));
        let mut violates = segment_violates_boundary_nm(t.seg, outer, r_total);
        if !violates {
            for hole in &boundary.holes {
                if segment_violates_hole_nm(t.seg, hole, r_total) {
                    violates = true;
                    break;
                }
            }
        }
        if violates {
            out.push(DrcViolation {
                kind: DrcViolationKind::Boundary,
                a: ItemRef {
                    kind: ItemKind::Track,
                    index: i,
                },
                b: boundary_ref,
            });
        }
    }

    for (i, v) in vias.iter().enumerate() {
        let mut violates = if v.shapes.is_empty() {
            circle_violates_boundary_nm(v.circle, outer, clearance_to_boundary)
        } else {
            v.shapes
                .iter()
                .any(|s| terminal_shape_violates_boundary_nm(s, outer, clearance_to_boundary))
        };
        if !violates {
            for hole in &boundary.holes {
                let hit = if v.shapes.is_empty() {
                    circle_violates_hole_nm(v.circle, hole, clearance_to_boundary)
                } else {
                    v.shapes
                        .iter()
                        .any(|s| terminal_shape_violates_hole_nm(s, hole, clearance_to_boundary))
                };
                if hit {
                    violates = true;
                    break;
                }
            }
        }
        if violates {
            out.push(DrcViolation {
                kind: DrcViolationKind::Boundary,
                a: ItemRef {
                    kind: ItemKind::Via,
                    index: i,
                },
                b: boundary_ref,
            });
        }
    }

    for (i, t) in terminals.iter().enumerate() {
        let mut violates = if t.shapes.is_empty() {
            circle_violates_boundary_nm(t.circle, outer, clearance_to_boundary)
        } else {
            t.shapes
                .iter()
                .any(|s| terminal_shape_violates_boundary_nm(s, outer, clearance_to_boundary))
        };
        if !violates {
            for hole in &boundary.holes {
                let hit = if t.shapes.is_empty() {
                    circle_violates_hole_nm(t.circle, hole, clearance_to_boundary)
                } else {
                    t.shapes
                        .iter()
                        .any(|s| terminal_shape_violates_hole_nm(s, hole, clearance_to_boundary))
                };
                if hit {
                    violates = true;
                    break;
                }
            }
        }
        if violates {
            out.push(DrcViolation {
                kind: DrcViolationKind::Boundary,
                a: ItemRef {
                    kind: ItemKind::Terminal,
                    index: i,
                },
                b: boundary_ref,
            });
        }
    }

    // Keepouts are stored as shapes too; ensure they don't lie outside the boundary.
    for (i, k) in keepouts.iter().enumerate() {
        let mut violates = keepout_shape_violates_boundary_nm(&k.shape, outer);
        if !violates {
            for hole in &boundary.holes {
                if keepout_shape_violates_hole_nm(&k.shape, hole) {
                    violates = true;
                    break;
                }
            }
        }
        if violates {
            out.push(DrcViolation {
                kind: DrcViolationKind::Boundary,
                a: ItemRef {
                    kind: ItemKind::Keepout,
                    index: i,
                },
                b: boundary_ref,
            });
        }
    }

    out
}

pub(crate) fn terminal_shape_within_polygon_extra_nm(shape: &TerminalShapeNm, poly: &[PointNm], extra: Nm) -> bool {
    match shape {
        TerminalShapeNm::Circle { circle, .. } => circle_within_polygon_extra_nm(*circle, poly, extra),
        TerminalShapeNm::Polygon { points, .. } => polygons_within_radius_nm(points, poly, extra),
        TerminalShapeNm::Path { r, points, .. } => {
            if points.len() < 2 {
                return false;
            }
            let rr = Nm(r.0 + extra.0);
            for w in points.windows(2) {
                let seg = SegmentNm { a: w[0], b: w[1] };
                if segment_within_polygon_radius_nm(seg, poly, rr) {
                    return true;
                }
            }
            false
        }
    }
}

pub fn drc_check_keepouts_indexed(
    tracks: &[TrackNm],
    vias: &[ViaNm],
    terminals: &[TerminalNm],
    keepouts: &[KeepoutNm],
) -> Vec<DrcViolation> {
    use crate::spatial_nm::{aabb_circle_nm, aabb_segment_nm, SpatialHashNm};

    let mut max_item_r = 0i64;
    for t in tracks {
        max_item_r = max_item_r.max(t.r.0);
    }
    for v in vias {
        max_item_r = max_item_r.max(v.circle.r.0);
    }
    for p in terminals {
        max_item_r = max_item_r.max(p.circle.r.0);
    }
    let mut keepout_aabb: Vec<(usize, crate::spatial_nm::AabbNm)> = Vec::new();

    let mut max_keepout_r = 0i64;
    for (ki, k) in keepouts.iter().enumerate() {
        let aabb = match &k.shape {
            KeepoutShapeNm::Circle { circle } => aabb_circle_nm(*circle),
            KeepoutShapeNm::Polygon { points } => {
                let mut min_x = i64::MAX;
                let mut min_y = i64::MAX;
                let mut max_x = i64::MIN;
                let mut max_y = i64::MIN;
                for p in points {
                    min_x = min_x.min(p.x.0);
                    min_y = min_y.min(p.y.0);
                    max_x = max_x.max(p.x.0);
                    max_y = max_y.max(p.y.0);
                }
                crate::spatial_nm::AabbNm {
                    min_x,
                    min_y,
                    max_x,
                    max_y,
                }
            }
            KeepoutShapeNm::Path { r, points } => {
                let mut min_x = i64::MAX;
                let mut min_y = i64::MAX;
                let mut max_x = i64::MIN;
                let mut max_y = i64::MIN;
                for p in points {
                    min_x = min_x.min(p.x.0);
                    min_y = min_y.min(p.y.0);
                    max_x = max_x.max(p.x.0);
                    max_y = max_y.max(p.y.0);
                }
                crate::spatial_nm::AabbNm {
                    min_x: min_x.saturating_sub(r.0),
                    min_y: min_y.saturating_sub(r.0),
                    max_x: max_x.saturating_add(r.0),
                    max_y: max_y.saturating_add(r.0),
                }
            }
        };
        let span_x = aabb.max_x.saturating_sub(aabb.min_x);
        let span_y = aabb.max_y.saturating_sub(aabb.min_y);
        let r_est = (span_x.max(span_y) / 2).max(0);
        max_keepout_r = max_keepout_r.max(r_est);
        keepout_aabb.push((ki, aabb));
    }

    // Cell size heuristic:
    // - must be large enough that inserting large keepouts doesn't explode bucket counts,
    // - must still be conservative for query coverage.
    let cell_r = max_item_r.max(max_keepout_r).max(1);
    let cell = cell_r.saturating_mul(4).max(1);
    let mut sh = SpatialHashNm::new(cell);
    for (ki, aabb) in &keepout_aabb {
        let k = &keepouts[*ki];
        for &layer in &k.layers {
            sh.insert_aabb(layer, aabb.inflate(Nm(max_item_r.max(1))), *ki);
        }
    }

    let mut out: Vec<DrcViolation> = Vec::new();
    let mut scratch: Vec<usize> = Vec::new();

    // Track vs keepouts (by layer).
    for (ti, t) in tracks.iter().enumerate() {
        let aabb = aabb_segment_nm(t.seg).inflate(t.r);
        sh.query_aabb(t.layer, aabb, &mut scratch);
        scratch.sort_unstable();
        scratch.dedup();
        for &ki in &scratch {
            let k = &keepouts[ki];
            if !matches!(k.applies_to, KeepoutAppliesTo::All | KeepoutAppliesTo::Wire) {
                continue;
            }
            match &k.shape {
                KeepoutShapeNm::Circle { circle } => {
                    if circle_within_segment_radius_nm(*circle, t.seg, t.r) {
                        out.push(DrcViolation {
                            kind: DrcViolationKind::Keepout,
                            a: ItemRef { kind: ItemKind::Track, index: ti },
                            b: ItemRef { kind: ItemKind::Keepout, index: ki },
                        });
                    }
                }
                KeepoutShapeNm::Polygon { points } => {
                    if point_in_polygon_nm(t.seg.a, points) || point_in_polygon_nm(t.seg.b, points) {
                        out.push(DrcViolation {
                            kind: DrcViolationKind::Keepout,
                            a: ItemRef { kind: ItemKind::Track, index: ti },
                            b: ItemRef { kind: ItemKind::Keepout, index: ki },
                        });
                        continue;
                    }
                    let mut hit = false;
                    for e in polygon_edges(points) {
                        if segments_within_radius_nm(t.seg, e, t.r) {
                            hit = true;
                            break;
                        }
                    }
                    if hit {
                        out.push(DrcViolation {
                            kind: DrcViolationKind::Keepout,
                            a: ItemRef { kind: ItemKind::Track, index: ti },
                            b: ItemRef { kind: ItemKind::Keepout, index: ki },
                        });
                    }
                }
                KeepoutShapeNm::Path { r, points } => {
                    if points.len() < 2 {
                        continue;
                    }
                    let mut hit = false;
                    let rr = Nm(t.r.0 + r.0);
                    for w in points.windows(2) {
                        let s2 = SegmentNm { a: w[0], b: w[1] };
                        if segments_within_radius_nm(t.seg, s2, rr) {
                            hit = true;
                            break;
                        }
                    }
                    if hit {
                        out.push(DrcViolation {
                            kind: DrcViolationKind::Keepout,
                            a: ItemRef { kind: ItemKind::Track, index: ti },
                            b: ItemRef { kind: ItemKind::Keepout, index: ki },
                        });
                    }
                }
            }
        }
    }

    for (vi, v) in vias.iter().enumerate() {
        let aabb = aabb_circle_nm(v.circle);
        for layer in v.layers.0..=v.layers.1 {
            sh.query_aabb(layer, aabb.inflate(Nm(v.circle.r.0)), &mut scratch);
            scratch.sort_unstable();
            scratch.dedup();
            for &ki in &scratch {
                let k = &keepouts[ki];
                if !matches!(k.applies_to, KeepoutAppliesTo::All | KeepoutAppliesTo::Via) {
                    continue;
                }
                let mut hit = false;
                let mut any_shape = false;
                for s in via_shapes_on_layer(v, layer) {
                    any_shape = true;
                    match &k.shape {
                        KeepoutShapeNm::Circle { circle: kc } => match s {
                            TerminalShapeNm::Circle { circle, .. } => {
                                if circles_within_radius_nm(*circle, *kc, Nm::zero()) {
                                    hit = true;
                                }
                            }
                            TerminalShapeNm::Polygon { points, .. } => {
                                if circle_within_polygon_extra_nm(*kc, points, Nm::zero()) {
                                    hit = true;
                                }
                            }
                            TerminalShapeNm::Path { r, points, .. } => {
                                if points.len() >= 2 {
                                    for w in points.windows(2) {
                                        let seg = SegmentNm { a: w[0], b: w[1] };
                                        if circle_within_segment_radius_nm(*kc, seg, *r) {
                                            hit = true;
                                            break;
                                        }
                                    }
                                }
                            }
                        },
                        KeepoutShapeNm::Polygon { points } => match s {
                            TerminalShapeNm::Circle { circle, .. } => {
                                if circle_within_polygon_extra_nm(*circle, points, Nm::zero()) {
                                    hit = true;
                                }
                            }
                            TerminalShapeNm::Polygon { points: vp, .. } => {
                                if polygons_overlap_nm(vp, points) {
                                    hit = true;
                                }
                            }
                            TerminalShapeNm::Path { r, points: vp, .. } => {
                                if vp.len() >= 2 {
                                    for w in vp.windows(2) {
                                        let seg = SegmentNm { a: w[0], b: w[1] };
                                        if segment_within_polygon_radius_nm(seg, points, *r) {
                                            hit = true;
                                            break;
                                        }
                                    }
                                }
                            }
                        },
                        KeepoutShapeNm::Path { r: kr, points: kp } => match s {
                            TerminalShapeNm::Circle { circle, .. } => {
                                if kp.len() >= 2 {
                                    for w in kp.windows(2) {
                                        let seg = SegmentNm { a: w[0], b: w[1] };
                                        if circle_within_segment_radius_nm(*circle, seg, *kr) {
                                            hit = true;
                                            break;
                                        }
                                    }
                                }
                            }
                            TerminalShapeNm::Polygon { points: poly, .. } => {
                                if kp.len() >= 2 && poly.len() >= 3 {
                                    for w in kp.windows(2) {
                                        let seg = SegmentNm { a: w[0], b: w[1] };
                                        if point_in_polygon_nm(seg.a, poly) || point_in_polygon_nm(seg.b, poly) {
                                            hit = true;
                                            break;
                                        }
                                        for e in polygon_edges(poly) {
                                            if segments_within_radius_nm(e, seg, *kr) {
                                                hit = true;
                                                break;
                                            }
                                        }
                                        if hit {
                                            break;
                                        }
                                    }
                                }
                            }
                            TerminalShapeNm::Path { r: vr, points: vp, .. } => {
                                if kp.len() >= 2 && vp.len() >= 2 {
                                    let rr = Nm(vr.0 + kr.0);
                                    for wa in vp.windows(2) {
                                        let sa = SegmentNm { a: wa[0], b: wa[1] };
                                        for wb in kp.windows(2) {
                                            let sb = SegmentNm { a: wb[0], b: wb[1] };
                                            if segments_within_radius_nm(sa, sb, rr) {
                                                hit = true;
                                                break;
                                            }
                                        }
                                        if hit {
                                            break;
                                        }
                                    }
                                }
                            }
                        },
                    }
                    if hit {
                        break;
                    }
                }
                if !any_shape {
                    // Fallback to the bounding circle when no layer-specific shape exists.
                    match &k.shape {
                        KeepoutShapeNm::Circle { circle: kc } => {
                            hit = circles_within_radius_nm(v.circle, *kc, Nm::zero());
                        }
                        KeepoutShapeNm::Polygon { points } => {
                            if point_in_polygon_nm(v.circle.center, points) {
                                hit = true;
                            } else {
                                for e in polygon_edges(points) {
                                    if point_within_segment_radius_nm(v.circle.center, e, v.circle.r) {
                                        hit = true;
                                        break;
                                    }
                                }
                            }
                        }
                        KeepoutShapeNm::Path { r, points } => {
                            if points.len() >= 2 {
                                for w in points.windows(2) {
                                    let seg = SegmentNm { a: w[0], b: w[1] };
                                    if circle_within_segment_radius_nm(v.circle, seg, *r) {
                                        hit = true;
                                        break;
                                    }
                                }
                            }
                        }
                    }
                }
                if hit {
                    out.push(DrcViolation {
                        kind: DrcViolationKind::Keepout,
                        a: ItemRef { kind: ItemKind::Via, index: vi },
                        b: ItemRef { kind: ItemKind::Keepout, index: ki },
                    });
                }
            }
        }
    }
    for (pi, p) in terminals.iter().enumerate() {
        let aabb = aabb_circle_nm(p.circle);
        for &layer in &p.layers {
            sh.query_aabb(layer, aabb.inflate(Nm(p.circle.r.0)), &mut scratch);
            scratch.sort_unstable();
            scratch.dedup();
            for &ki in &scratch {
                let k = &keepouts[ki];
                if !matches!(k.applies_to, KeepoutAppliesTo::All) {
                    continue;
                }
                let mut hit = false;
                for s in terminal_shapes_on_layer(p, layer) {
                    match &k.shape {
                        KeepoutShapeNm::Circle { circle: kc } => match s {
                            TerminalShapeNm::Circle { circle, .. } => {
                                if circles_within_radius_nm(*circle, *kc, Nm::zero()) {
                                    hit = true;
                                }
                            }
                            TerminalShapeNm::Polygon { points, .. } => {
                                if circle_within_polygon_extra_nm(*kc, points, Nm::zero()) {
                                    hit = true;
                                }
                            }
                            TerminalShapeNm::Path { r, points, .. } => {
                                if points.len() >= 2 {
                                    for w in points.windows(2) {
                                        let seg = SegmentNm { a: w[0], b: w[1] };
                                        if circle_within_segment_radius_nm(*kc, seg, *r) {
                                            hit = true;
                                            break;
                                        }
                                    }
                                }
                            }
                        },
                        KeepoutShapeNm::Polygon { points } => match s {
                            TerminalShapeNm::Circle { circle, .. } => {
                                if circle_within_polygon_extra_nm(*circle, points, Nm::zero()) {
                                    hit = true;
                                }
                            }
                            TerminalShapeNm::Polygon { points: tp, .. } => {
                                if polygons_overlap_nm(tp, points) {
                                    hit = true;
                                }
                            }
                            TerminalShapeNm::Path { r, points: tp, .. } => {
                                if tp.len() >= 2 {
                                    for w in tp.windows(2) {
                                        let seg = SegmentNm { a: w[0], b: w[1] };
                                        if segment_within_polygon_radius_nm(seg, points, *r) {
                                            hit = true;
                                            break;
                                        }
                                    }
                                }
                            }
                        },
                        KeepoutShapeNm::Path { r: kr, points: kp } => match s {
                            TerminalShapeNm::Circle { circle, .. } => {
                                if kp.len() >= 2 {
                                    for w in kp.windows(2) {
                                        let seg = SegmentNm { a: w[0], b: w[1] };
                                        if circle_within_segment_radius_nm(*circle, seg, *kr) {
                                            hit = true;
                                            break;
                                        }
                                    }
                                }
                            }
                            TerminalShapeNm::Polygon { points: poly, .. } => {
                                if kp.len() >= 2 && poly.len() >= 3 {
                                    for w in kp.windows(2) {
                                        let seg = SegmentNm { a: w[0], b: w[1] };
                                        if point_in_polygon_nm(seg.a, poly) || point_in_polygon_nm(seg.b, poly) {
                                            hit = true;
                                            break;
                                        }
                                        for e in polygon_edges(poly) {
                                            if segments_within_radius_nm(e, seg, *kr) {
                                                hit = true;
                                                break;
                                            }
                                        }
                                        if hit {
                                            break;
                                        }
                                    }
                                }
                            }
                            TerminalShapeNm::Path { r: tr, points: tp, .. } => {
                                if kp.len() >= 2 && tp.len() >= 2 {
                                    let rr = Nm(tr.0 + kr.0);
                                    for wa in tp.windows(2) {
                                        let sa = SegmentNm { a: wa[0], b: wa[1] };
                                        for wb in kp.windows(2) {
                                            let sb = SegmentNm { a: wb[0], b: wb[1] };
                                            if segments_within_radius_nm(sa, sb, rr) {
                                                hit = true;
                                                break;
                                            }
                                        }
                                        if hit {
                                            break;
                                        }
                                    }
                                }
                            }
                        },
                    }
                    if hit {
                        break;
                    }
                }
                if hit {
                    out.push(DrcViolation {
                        kind: DrcViolationKind::Keepout,
                        a: ItemRef { kind: ItemKind::Terminal, index: pi },
                        b: ItemRef { kind: ItemKind::Keepout, index: ki },
                    });
                }
            }
        }
    }

    out
}

pub fn drc_check_areas_var_clearance_indexed<F>(
    tracks: &[TrackNm],
    vias: &[ViaNm],
    terminals: &[TerminalNm],
    areas: &[AreaNm],
    clearance_for_pair: F,
    max_clearance: Nm,
) -> Vec<DrcViolation>
where
    F: Fn(ClearanceKind, u32, u32, ClearanceKind, u32, u32) -> Nm,
{
    use crate::spatial_nm::{aabb_circle_nm, aabb_segment_nm, SpatialHashNm};

    if areas.is_empty() {
        return Vec::new();
    }

    let cell = (max_clearance.0.max(1) * 4).max(1);
    let mut sh = SpatialHashNm::new(cell);
    let mut area_aabb: Vec<crate::spatial_nm::AabbNm> = Vec::with_capacity(areas.len());

    for (ai, a) in areas.iter().enumerate() {
        let mut min_x = i64::MAX;
        let mut min_y = i64::MAX;
        let mut max_x = i64::MIN;
        let mut max_y = i64::MIN;
        for p in &a.polygon {
            min_x = min_x.min(p.x.0);
            min_y = min_y.min(p.y.0);
            max_x = max_x.max(p.x.0);
            max_y = max_y.max(p.y.0);
        }
        let aabb = crate::spatial_nm::AabbNm {
            min_x,
            min_y,
            max_x,
            max_y,
        };
        sh.insert_aabb(a.layer, aabb.inflate(max_clearance), ai);
        area_aabb.push(aabb);
    }

    let mut out: Vec<DrcViolation> = Vec::new();
    let mut scratch: Vec<usize> = Vec::new();

    // Track ↔ Area on same layer.
    for (ti, t) in tracks.iter().enumerate() {
        let aabb = aabb_segment_nm(t.seg).inflate(Nm(t.r.0 + max_clearance.0));
        sh.query_aabb(t.layer, aabb, &mut scratch);
        scratch.sort_unstable();
        scratch.dedup();
        for &ai in &scratch {
            let a = &areas[ai];
            if a.layer != t.layer {
                continue;
            }
            if a.net_id == t.net_id {
                continue;
            }
            let req = clearance_for_pair(
                ClearanceKind::Wire,
                t.net_id,
                t.clearance_class,
                ClearanceKind::Area,
                a.net_id,
                a.clearance_class,
            );
            let r_total = Nm(t.r.0 + req.0);
            if segment_within_polygon_radius_nm(t.seg, &a.polygon, r_total)
                && !a.holes.iter().any(|h| segment_fully_inside_hole_nm(t.seg, h, r_total))
            {
                let short = segment_within_polygon_radius_nm(t.seg, &a.polygon, t.r)
                    && !a.holes.iter().any(|h| segment_fully_inside_hole_nm(t.seg, h, t.r));
                out.push(DrcViolation {
                    kind: if short { DrcViolationKind::Short } else { DrcViolationKind::Clearance },
                    a: ItemRef {
                        kind: ItemKind::Track,
                        index: ti,
                    },
                    b: ItemRef {
                        kind: ItemKind::Area,
                        index: ai,
                    },
                });
            }
        }
    }

    // Via ↔ Area.
    for (vi, v) in vias.iter().enumerate() {
        let aabb = aabb_circle_nm(v.circle).inflate(max_clearance);
        for layer in v.layers.0..=v.layers.1 {
            sh.query_aabb(layer, aabb, &mut scratch);
            scratch.sort_unstable();
            scratch.dedup();
            for &ai in &scratch {
                let a = &areas[ai];
                if a.layer != layer {
                    continue;
                }
                if a.net_id == v.net_id {
                    continue;
                }
                let req = clearance_for_pair(
                    ClearanceKind::Via,
                    v.net_id,
                    v.clearance_class,
                    ClearanceKind::Area,
                    a.net_id,
                    a.clearance_class,
                );

                let mut any_shape = false;
                let mut hit = false;
                for s in via_shapes_on_layer(v, layer) {
                    any_shape = true;
                    if terminal_shape_within_polygon_extra_nm(s, &a.polygon, req)
                        && !a.holes.iter().any(|h| terminal_shape_fully_inside_hole_nm(s, h, req))
                    {
                        hit = true;
                        break;
                    }
                }
                if !any_shape {
                    hit = circle_within_polygon_extra_nm(v.circle, &a.polygon, req)
                        && !a.holes.iter().any(|h| circle_fully_inside_hole_nm(v.circle, h, req));
                }
                if !hit {
                    continue;
                }

                let mut short = false;
                if any_shape {
                    for s in via_shapes_on_layer(v, layer) {
                        if terminal_shape_within_polygon_extra_nm(s, &a.polygon, Nm::zero())
                            && !a.holes.iter().any(|h| terminal_shape_fully_inside_hole_nm(s, h, Nm::zero()))
                        {
                            short = true;
                            break;
                        }
                    }
                } else {
                    short = circle_within_polygon_extra_nm(v.circle, &a.polygon, Nm::zero())
                        && !a.holes.iter().any(|h| circle_fully_inside_hole_nm(v.circle, h, Nm::zero()));
                }

                out.push(DrcViolation {
                    kind: if short { DrcViolationKind::Short } else { DrcViolationKind::Clearance },
                    a: ItemRef {
                        kind: ItemKind::Via,
                        index: vi,
                    },
                    b: ItemRef {
                        kind: ItemKind::Area,
                        index: ai,
                    },
                });
            }
        }
    }

    // Terminal ↔ Area.
    for (pi, p) in terminals.iter().enumerate() {
        let aabb = aabb_circle_nm(p.circle).inflate(max_clearance);
        for &layer in &p.layers {
            sh.query_aabb(layer, aabb, &mut scratch);
            scratch.sort_unstable();
            scratch.dedup();
            for &ai in &scratch {
                let a = &areas[ai];
                if a.layer != layer {
                    continue;
                }
                if a.net_id == p.net_id {
                    continue;
                }
                let req = clearance_for_pair(
                    terminal_clearance_kind(p),
                    p.net_id,
                    p.clearance_class,
                    ClearanceKind::Area,
                    a.net_id,
                    a.clearance_class,
                );

                let mut hit = false;
                for s in terminal_shapes_on_layer(p, layer) {
                    if terminal_shape_within_polygon_extra_nm(s, &a.polygon, req)
                        && !a.holes.iter().any(|h| terminal_shape_fully_inside_hole_nm(s, h, req))
                    {
                        hit = true;
                        break;
                    }
                }
                if !hit {
                    continue;
                }

                let short = terminal_shapes_on_layer(p, layer).any(|s| {
                    terminal_shape_within_polygon_extra_nm(s, &a.polygon, Nm::zero())
                        && !a.holes.iter().any(|h| terminal_shape_fully_inside_hole_nm(s, h, Nm::zero()))
                });
                out.push(DrcViolation {
                    kind: if short { DrcViolationKind::Short } else { DrcViolationKind::Clearance },
                    a: ItemRef {
                        kind: ItemKind::Terminal,
                        index: pi,
                    },
                    b: ItemRef {
                        kind: ItemKind::Area,
                        index: ai,
                    },
                });
            }
        }
    }

    // Area ↔ Area (same layer) for different nets.
    for (i, a) in areas.iter().enumerate() {
        sh.query_aabb(a.layer, area_aabb[i].inflate(max_clearance), &mut scratch);
        scratch.sort_unstable();
        scratch.dedup();
        for &j in &scratch {
            if j <= i {
                continue;
            }
            let b = &areas[j];
            if b.layer != a.layer {
                continue;
            }
            if b.net_id == a.net_id {
                continue;
            }
            let req = clearance_for_pair(
                ClearanceKind::Area,
                a.net_id,
                a.clearance_class,
                ClearanceKind::Area,
                b.net_id,
                b.clearance_class,
            );
            if polygons_within_radius_nm(&a.polygon, &b.polygon, req) {
                let short = polygons_overlap_nm(&a.polygon, &b.polygon);
                out.push(DrcViolation {
                    kind: if short { DrcViolationKind::Short } else { DrcViolationKind::Clearance },
                    a: ItemRef {
                        kind: ItemKind::Area,
                        index: i,
                    },
                    b: ItemRef {
                        kind: ItemKind::Area,
                        index: j,
                    },
                });
            }
        }
    }

    out
}

pub fn drc_check_basic(
    tracks: &[TrackNm],
    vias: &[ViaNm],
    required_clearance: Nm,
) -> Vec<DrcViolation> {
    let mut out: Vec<DrcViolation> = Vec::new();

    // Track ↔ Track (same layer only).
    for i in 0..tracks.len() {
        for j in (i + 1)..tracks.len() {
            let a = &tracks[i];
            let b = &tracks[j];
            if a.layer != b.layer {
                continue;
            }
            if a.net_id == b.net_id {
                continue;
            }
            let r = Nm(a.r.0 + b.r.0 + required_clearance.0);
            if segments_within_radius_nm(a.seg, b.seg, r) {
                // classify as short if copper overlaps (clearance radius without required_clearance).
                let overlap_r = Nm(a.r.0 + b.r.0);
                let kind = if segments_within_radius_nm(a.seg, b.seg, overlap_r) {
                    DrcViolationKind::Short
                } else {
                    DrcViolationKind::Clearance
                };
                out.push(DrcViolation {
                    kind,
                    a: ItemRef {
                        kind: ItemKind::Track,
                        index: i,
                    },
                    b: ItemRef {
                        kind: ItemKind::Track,
                        index: j,
                    },
                });
            }
        }
    }

    // Via ↔ Via (if layer ranges overlap).
    for i in 0..vias.len() {
        for j in (i + 1)..vias.len() {
            let a = &vias[i];
            let b = &vias[j];
            let overlap = !(a.layers.1 < b.layers.0 || b.layers.1 < a.layers.0);
            if !overlap {
                continue;
            }
            if a.net_id == b.net_id {
                continue;
            }
            if circles_within_radius_nm(a.circle, b.circle, required_clearance) {
                let kind = if circles_within_radius_nm(a.circle, b.circle, Nm::zero()) {
                    DrcViolationKind::Short
                } else {
                    DrcViolationKind::Clearance
                };
                out.push(DrcViolation {
                    kind,
                    a: ItemRef {
                        kind: ItemKind::Via,
                        index: i,
                    },
                    b: ItemRef {
                        kind: ItemKind::Via,
                        index: j,
                    },
                });
            }
        }
    }

    // Track ↔ Via (if via spans the track layer).
    for (ti, t) in tracks.iter().enumerate() {
        for (vi, v) in vias.iter().enumerate() {
            if v.layers.0 > t.layer || v.layers.1 < t.layer {
                continue;
            }
            if t.net_id == v.net_id {
                continue;
            }
            let r = Nm(t.r.0 + required_clearance.0);
            if circle_within_segment_radius_nm(v.circle, t.seg, r) {
                let kind = if circle_within_segment_radius_nm(v.circle, t.seg, Nm(t.r.0)) {
                    DrcViolationKind::Short
                } else {
                    DrcViolationKind::Clearance
                };
                out.push(DrcViolation {
                    kind,
                    a: ItemRef {
                        kind: ItemKind::Track,
                        index: ti,
                    },
                    b: ItemRef {
                        kind: ItemKind::Via,
                        index: vi,
                    },
                });
            }
        }
    }

    out
}

pub fn drc_check_basic_with_terminals(
    tracks: &[TrackNm],
    vias: &[ViaNm],
    terminals: &[TerminalNm],
    required_clearance: Nm,
) -> Vec<DrcViolation> {
    drc_check_var_clearance(tracks, vias, terminals, |_, _, _, _, _, _| required_clearance)
}

fn terminal_clearance_kind(t: &TerminalNm) -> ClearanceKind {
    if t.layers.len() <= 1 {
        ClearanceKind::Smd
    } else {
        ClearanceKind::Pin
    }
}

pub fn drc_check_var_clearance<F>(
    tracks: &[TrackNm],
    vias: &[ViaNm],
    terminals: &[TerminalNm],
    clearance_for_pair: F,
) -> Vec<DrcViolation>
where
    F: Fn(ClearanceKind, u32, u32, ClearanceKind, u32, u32) -> Nm,
{
    let mut out: Vec<DrcViolation> = Vec::new();

    // Track ↔ Track (same layer only).
    for i in 0..tracks.len() {
        for j in (i + 1)..tracks.len() {
            let a = &tracks[i];
            let b = &tracks[j];
            if a.layer != b.layer {
                continue;
            }
            if a.net_id == b.net_id {
                continue;
            }
            let req = clearance_for_pair(
                ClearanceKind::Wire,
                a.net_id,
                a.clearance_class,
                ClearanceKind::Wire,
                b.net_id,
                b.clearance_class,
            );
            let r = Nm(a.r.0 + b.r.0 + req.0);
            if segments_within_radius_nm(a.seg, b.seg, r) {
                let overlap_r = Nm(a.r.0 + b.r.0);
                let kind = if segments_within_radius_nm(a.seg, b.seg, overlap_r) {
                    DrcViolationKind::Short
                } else {
                    DrcViolationKind::Clearance
                };
                out.push(DrcViolation {
                    kind,
                    a: ItemRef {
                        kind: ItemKind::Track,
                        index: i,
                    },
                    b: ItemRef {
                        kind: ItemKind::Track,
                        index: j,
                    },
                });
            }
        }
    }

    // Via ↔ Via (if layer ranges overlap).
    for i in 0..vias.len() {
        for j in (i + 1)..vias.len() {
            let a = &vias[i];
            let b = &vias[j];
            let overlap = !(a.layers.1 < b.layers.0 || b.layers.1 < a.layers.0);
            if !overlap {
                continue;
            }
            if a.net_id == b.net_id {
                continue;
            }
            let req = clearance_for_pair(
                ClearanceKind::Via,
                a.net_id,
                a.clearance_class,
                ClearanceKind::Via,
                b.net_id,
                b.clearance_class,
            );
            if !circles_within_radius_nm(a.circle, b.circle, req) {
                continue;
            }
            let start = a.layers.0.max(b.layers.0);
            let end = a.layers.1.min(b.layers.1);
            let mut hit = false;
            for layer in start..=end {
                if via_shapes_overlap_via_extra_nm(a, b, layer, req) {
                    hit = true;
                    break;
                }
            }
            if !hit {
                continue;
            }
            let mut short = false;
            for layer in start..=end {
                if via_shapes_overlap_via_extra_nm(a, b, layer, Nm::zero()) {
                    short = true;
                    break;
                }
            }
            out.push(DrcViolation {
                kind: if short { DrcViolationKind::Short } else { DrcViolationKind::Clearance },
                a: ItemRef {
                    kind: ItemKind::Via,
                    index: i,
                },
                b: ItemRef {
                    kind: ItemKind::Via,
                    index: j,
                },
            });
        }
    }

    // Track ↔ Via (if via spans the track layer).
    for (ti, t) in tracks.iter().enumerate() {
        for (vi, v) in vias.iter().enumerate() {
            if v.layers.0 > t.layer || v.layers.1 < t.layer {
                continue;
            }
            if t.net_id == v.net_id {
                continue;
            }
            let req = clearance_for_pair(
                ClearanceKind::Wire,
                t.net_id,
                t.clearance_class,
                ClearanceKind::Via,
                v.net_id,
                v.clearance_class,
            );
            let r = Nm(t.r.0 + req.0);
            if via_shapes_overlap_segment_extra_nm(v, t.layer, t.seg, r) {
                let kind = if via_shapes_overlap_segment_extra_nm(v, t.layer, t.seg, t.r) {
                    DrcViolationKind::Short
                } else {
                    DrcViolationKind::Clearance
                };
                out.push(DrcViolation {
                    kind,
                    a: ItemRef {
                        kind: ItemKind::Track,
                        index: ti,
                    },
                    b: ItemRef {
                        kind: ItemKind::Via,
                        index: vi,
                    },
                });
            }
        }
    }

    // Track ↔ Terminal (if terminal on track layer).
    for (ti, t) in tracks.iter().enumerate() {
        for (pi, p) in terminals.iter().enumerate() {
            if t.net_id == p.net_id {
                continue;
            }
            if !p.layers.iter().any(|&l| l == t.layer) {
                continue;
            }
            let req = clearance_for_pair(
                ClearanceKind::Wire,
                t.net_id,
                t.clearance_class,
                terminal_clearance_kind(p),
                p.net_id,
                p.clearance_class,
            );
            let extra = Nm(t.r.0 + req.0);
            if circle_within_segment_radius_nm(p.circle, t.seg, extra)
                && terminal_shapes_on_layer(p, t.layer).any(|s| terminal_shape_within_segment_extra_nm(s, t.seg, extra))
            {
                let short_extra = t.r;
                let kind = if circle_within_segment_radius_nm(p.circle, t.seg, short_extra)
                    && terminal_shapes_on_layer(p, t.layer)
                        .any(|s| terminal_shape_within_segment_extra_nm(s, t.seg, short_extra))
                {
                    DrcViolationKind::Short
                } else {
                    DrcViolationKind::Clearance
                };
                out.push(DrcViolation {
                    kind,
                    a: ItemRef { kind: ItemKind::Track, index: ti },
                    b: ItemRef { kind: ItemKind::Terminal, index: pi },
                });
            }
        }
    }

    // Via ↔ Terminal (if layer ranges overlap).
    for (vi, v) in vias.iter().enumerate() {
        for (pi, p) in terminals.iter().enumerate() {
            if v.net_id == p.net_id {
                continue;
            }
            let overlap = p.layers.iter().any(|&l| l >= v.layers.0 && l <= v.layers.1);
            if !overlap {
                continue;
            }
            let req = clearance_for_pair(
                ClearanceKind::Via,
                v.net_id,
                v.clearance_class,
                terminal_clearance_kind(p),
                p.net_id,
                p.clearance_class,
            );
            if !circles_within_radius_nm(v.circle, p.circle, req) {
                continue;
            }
            let mut hit = false;
            let mut short = false;
            for layer in v.layers.0..=v.layers.1 {
                if layer >= v.layers.0 && layer <= v.layers.1 && p.layers.contains(&layer) {
                    if via_shapes_overlap_terminal_extra_nm(v, p, layer, req) {
                        hit = true;
                    }
                    if via_shapes_overlap_terminal_extra_nm(v, p, layer, Nm::zero()) {
                        short = true;
                    }
                }
            }
            if !hit {
                continue;
            }
                out.push(DrcViolation {
                    kind: if short { DrcViolationKind::Short } else { DrcViolationKind::Clearance },
                    a: ItemRef { kind: ItemKind::Via, index: vi },
                    b: ItemRef { kind: ItemKind::Terminal, index: pi },
                });
        }
    }

    // Terminal ↔ Terminal (if they share at least one layer).
    for i in 0..terminals.len() {
        for j in (i + 1)..terminals.len() {
            let a = &terminals[i];
            let b = &terminals[j];
            if a.net_id == b.net_id {
                continue;
            }
            let overlap = a.layers.iter().any(|l| b.layers.contains(l));
            if !overlap {
                continue;
            }
            let req = clearance_for_pair(
                terminal_clearance_kind(a),
                a.net_id,
                a.clearance_class,
                terminal_clearance_kind(b),
                b.net_id,
                b.clearance_class,
            );
            if circles_within_radius_nm(a.circle, b.circle, req)
                && a.shapes.iter().any(|sa| {
                    b.shapes.iter().any(|sb| terminal_shape_layer(sa) == terminal_shape_layer(sb) && terminal_shapes_within_extra_nm(sa, sb, req))
                })
            {
                let kind = if circles_within_radius_nm(a.circle, b.circle, Nm::zero())
                    && a.shapes.iter().any(|sa| {
                        b.shapes.iter().any(|sb| terminal_shape_layer(sa) == terminal_shape_layer(sb) && terminal_shapes_within_extra_nm(sa, sb, Nm::zero()))
                    })
                {
                    DrcViolationKind::Short
                } else {
                    DrcViolationKind::Clearance
                };
                out.push(DrcViolation {
                    kind,
                    a: ItemRef { kind: ItemKind::Terminal, index: i },
                    b: ItemRef { kind: ItemKind::Terminal, index: j },
                });
            }
        }
    }

    out
}

pub fn drc_check_var_clearance_indexed<F>(
    tracks: &[TrackNm],
    vias: &[ViaNm],
    terminals: &[TerminalNm],
    clearance_for_pair: F,
    max_clearance: Nm,
) -> Vec<DrcViolation>
where
    F: Fn(ClearanceKind, u32, u32, ClearanceKind, u32, u32) -> Nm,
{
    use crate::spatial_nm::{aabb_circle_nm, aabb_segment_nm, SpatialHashNm};

    // Cell size heuristic: choose a reasonably large bin size so we don't explode buckets.
    // This is conservative (may include more candidates) but must not miss any.
    let cell = (max_clearance.0.max(1) * 4).max(1);
    let mut track_index: Vec<(usize, crate::spatial_nm::AabbNm)> = Vec::new();
    let mut circle_index: Vec<(ItemKind, usize, usize, crate::spatial_nm::AabbNm)> = Vec::new();

    let mut sh_tracks = SpatialHashNm::new(cell);
    for (i, t) in tracks.iter().enumerate() {
        let aabb = aabb_segment_nm(t.seg).inflate(Nm(t.r.0 + max_clearance.0));
        sh_tracks.insert_aabb(t.layer, aabb, i);
        track_index.push((i, aabb));
    }

    let mut sh_circles = SpatialHashNm::new(cell);
    for (i, v) in vias.iter().enumerate() {
        let aabb = aabb_circle_nm(v.circle).inflate(max_clearance);
        // Index each via on all layers it spans so track queries by layer can find it.
        for layer in v.layers.0..=v.layers.1 {
            sh_circles.insert_aabb(layer, aabb, circle_index.len());
        }
        circle_index.push((ItemKind::Via, i, 0, aabb));
    }
    for (i, p) in terminals.iter().enumerate() {
        let aabb = aabb_circle_nm(p.circle).inflate(max_clearance);
        for &layer in &p.layers {
            sh_circles.insert_aabb(layer, aabb, circle_index.len());
        }
        circle_index.push((ItemKind::Terminal, i, 0, aabb));
    }

    let mut out: Vec<DrcViolation> = Vec::new();
    let mut scratch: Vec<usize> = Vec::new();

    // Track ↔ Track: query candidates by layer.
    for (i, t) in tracks.iter().enumerate() {
        let aabb = track_index[i].1;
        sh_tracks.query_aabb(t.layer, aabb, &mut scratch);
        scratch.sort_unstable();
        scratch.dedup();
        for &j in &scratch {
            if j <= i {
                continue;
            }
            let a = t;
            let b = &tracks[j];
            if a.layer != b.layer || a.net_id == b.net_id {
                continue;
            }
            let req = clearance_for_pair(
                ClearanceKind::Wire,
                a.net_id,
                a.clearance_class,
                ClearanceKind::Wire,
                b.net_id,
                b.clearance_class,
            );
            let r = Nm(a.r.0 + b.r.0 + req.0);
            if segments_within_radius_nm(a.seg, b.seg, r) {
                let overlap_r = Nm(a.r.0 + b.r.0);
                let kind = if segments_within_radius_nm(a.seg, b.seg, overlap_r) {
                    DrcViolationKind::Short
                } else {
                    DrcViolationKind::Clearance
                };
                out.push(DrcViolation {
                    kind,
                    a: ItemRef { kind: ItemKind::Track, index: i },
                    b: ItemRef { kind: ItemKind::Track, index: j },
                });
            }
        }
    }

    // Track ↔ Circle (vias+terminals) by layer.
    for (ti, t) in tracks.iter().enumerate() {
        let aabb = track_index[ti].1;
        sh_circles.query_aabb(t.layer, aabb, &mut scratch);
        scratch.sort_unstable();
        scratch.dedup();
        for &ci in &scratch {
            let (kind, idx, _unused, _) = circle_index[ci];
            match kind {
                ItemKind::Via => {
                    let v = &vias[idx];
                    if v.net_id == t.net_id {
                        continue;
                    }
                    if v.layers.0 > t.layer || v.layers.1 < t.layer {
                        continue;
                    }
                    let req = clearance_for_pair(
                        ClearanceKind::Wire,
                        t.net_id,
                        t.clearance_class,
                        ClearanceKind::Via,
                        v.net_id,
                        v.clearance_class,
                    );
                    let r = Nm(t.r.0 + req.0);
                    if via_shapes_overlap_segment_extra_nm(v, t.layer, t.seg, r) {
                        let kind = if via_shapes_overlap_segment_extra_nm(v, t.layer, t.seg, t.r) {
                            DrcViolationKind::Short
                        } else {
                            DrcViolationKind::Clearance
                        };
                        out.push(DrcViolation {
                            kind,
                            a: ItemRef { kind: ItemKind::Track, index: ti },
                            b: ItemRef { kind: ItemKind::Via, index: idx },
                        });
                    }
                }
                ItemKind::Terminal => {
                    let p = &terminals[idx];
                    if p.net_id == t.net_id {
                        continue;
                    }
                    if !p.layers.iter().any(|&l| l == t.layer) {
                        continue;
                    }
                    let req = clearance_for_pair(
                        ClearanceKind::Wire,
                        t.net_id,
                        t.clearance_class,
                        terminal_clearance_kind(p),
                        p.net_id,
                        p.clearance_class,
                    );
                    let extra = Nm(t.r.0 + req.0);
                    if circle_within_segment_radius_nm(p.circle, t.seg, extra)
                        && terminal_shapes_on_layer(p, t.layer).any(|s| terminal_shape_within_segment_extra_nm(s, t.seg, extra))
                    {
                        let short_extra = t.r;
                        let kind = if circle_within_segment_radius_nm(p.circle, t.seg, short_extra)
                            && terminal_shapes_on_layer(p, t.layer)
                                .any(|s| terminal_shape_within_segment_extra_nm(s, t.seg, short_extra))
                        {
                            DrcViolationKind::Short
                        } else {
                            DrcViolationKind::Clearance
                        };
                        out.push(DrcViolation {
                            kind,
                            a: ItemRef { kind: ItemKind::Track, index: ti },
                            b: ItemRef { kind: ItemKind::Terminal, index: idx },
                        });
                    }
                }
                ItemKind::Track => {}
                ItemKind::Keepout => {}
                ItemKind::Boundary => {}
                ItemKind::Area => {}
            }
        }
    }

    // Circle ↔ Circle (vias/terminals): use the spatial hash to avoid O(N^2).
    //
    // Iterate circle items in a stable order and query candidates per occupied layer,
    // emitting at most one violation per item pair (even if they overlap on multiple layers).
    let mut emitted_pairs: std::collections::HashSet<u128> = std::collections::HashSet::new();
    let uid = |k: ItemKind, idx: usize| -> u64 { ((k as u64) << 56) | (idx as u64) };
    let pair_key = |a: u64, b: u64| -> u128 {
        let (lo, hi) = if a <= b { (a, b) } else { (b, a) };
        ((lo as u128) << 64) | (hi as u128)
    };

    for (ci, (kind_a, idx_a, _unused, aabb_a)) in circle_index.iter().copied().enumerate() {
        let (net_a, circle_a, layers_a): (u32, CircleNm, Vec<usize>) = match kind_a {
            ItemKind::Via => {
                let v = &vias[idx_a];
                let layers: Vec<usize> = (v.layers.0..=v.layers.1).collect();
                (v.net_id, v.circle, layers)
            }
            ItemKind::Terminal => {
                let t = &terminals[idx_a];
                (t.net_id, t.circle, t.layers.clone())
            }
            _ => continue,
        };

        for layer in layers_a {
            sh_circles.query_aabb(layer, aabb_a, &mut scratch);
            scratch.sort_unstable();
            scratch.dedup();
            for &cj in &scratch {
                if cj <= ci {
                    continue;
                }
                let (kind_b, idx_b, _unused, _aabb_b) = circle_index[cj];
                let (net_b, circle_b) = match kind_b {
                    ItemKind::Via => {
                        let v = &vias[idx_b];
                        if layer < v.layers.0 || layer > v.layers.1 {
                            continue;
                        }
                        (v.net_id, v.circle)
                    }
                    ItemKind::Terminal => {
                        let t = &terminals[idx_b];
                        if !t.layers.contains(&layer) {
                            continue;
                        }
                        (t.net_id, t.circle)
                    }
                    _ => continue,
                };
                if net_a == net_b {
                    continue;
                }

                match (kind_a, kind_b) {
                    (ItemKind::Via, ItemKind::Via) => {
                        let va = &vias[idx_a];
                        let vb = &vias[idx_b];
                        let req = clearance_for_pair(
                            ClearanceKind::Via,
                            net_a,
                            va.clearance_class,
                            ClearanceKind::Via,
                            net_b,
                            vb.clearance_class,
                        );
                        if !circles_within_radius_nm(circle_a, circle_b, req) {
                            continue;
                        }
                        if !via_shapes_overlap_via_extra_nm(va, vb, layer, req) {
                            continue;
                        }
                        let k = pair_key(uid(ItemKind::Via, idx_a), uid(ItemKind::Via, idx_b));
                        if emitted_pairs.contains(&k) {
                            continue;
                        }
                        let kind = if via_shapes_overlap_via_extra_nm(va, vb, layer, Nm::zero()) {
                            DrcViolationKind::Short
                        } else {
                            DrcViolationKind::Clearance
                        };
                        out.push(DrcViolation {
                            kind,
                            a: ItemRef { kind: ItemKind::Via, index: idx_a },
                            b: ItemRef { kind: ItemKind::Via, index: idx_b },
                        });
                        emitted_pairs.insert(k);
                    }
                    (ItemKind::Via, ItemKind::Terminal) => {
                        let va = &vias[idx_a];
                        let tb = &terminals[idx_b];
                        let req = clearance_for_pair(
                            ClearanceKind::Via,
                            net_a,
                            va.clearance_class,
                            terminal_clearance_kind(tb),
                            net_b,
                            tb.clearance_class,
                        );
                        if !circles_within_radius_nm(circle_a, circle_b, req) {
                            continue;
                        }
                        if !via_shapes_overlap_terminal_extra_nm(va, tb, layer, req) {
                            continue;
                        }
                        let k = pair_key(uid(ItemKind::Via, idx_a), uid(ItemKind::Terminal, idx_b));
                        if emitted_pairs.contains(&k) {
                            continue;
                        }
                        let kind = if via_shapes_overlap_terminal_extra_nm(va, tb, layer, Nm::zero()) {
                            DrcViolationKind::Short
                        } else {
                            DrcViolationKind::Clearance
                        };
                        out.push(DrcViolation {
                            kind,
                            a: ItemRef { kind: ItemKind::Via, index: idx_a },
                            b: ItemRef { kind: ItemKind::Terminal, index: idx_b },
                        });
                        emitted_pairs.insert(k);
                    }
                    (ItemKind::Terminal, ItemKind::Via) => {
                        let ta = &terminals[idx_a];
                        let vb = &vias[idx_b];
                        let req = clearance_for_pair(
                            terminal_clearance_kind(ta),
                            net_a,
                            ta.clearance_class,
                            ClearanceKind::Via,
                            net_b,
                            vb.clearance_class,
                        );
                        if !circles_within_radius_nm(circle_a, circle_b, req) {
                            continue;
                        }
                        if !via_shapes_overlap_terminal_extra_nm(vb, ta, layer, req) {
                            continue;
                        }
                        let k = pair_key(uid(ItemKind::Terminal, idx_a), uid(ItemKind::Via, idx_b));
                        if emitted_pairs.contains(&k) {
                            continue;
                        }
                        let kind = if via_shapes_overlap_terminal_extra_nm(vb, ta, layer, Nm::zero()) {
                            DrcViolationKind::Short
                        } else {
                            DrcViolationKind::Clearance
                        };
                        out.push(DrcViolation {
                            kind,
                            a: ItemRef { kind: ItemKind::Terminal, index: idx_a },
                            b: ItemRef { kind: ItemKind::Via, index: idx_b },
                        });
                        emitted_pairs.insert(k);
                    }
                    (ItemKind::Terminal, ItemKind::Terminal) => {
                        let ta = &terminals[idx_a];
                        let tb = &terminals[idx_b];
                        let req = clearance_for_pair(
                            terminal_clearance_kind(ta),
                            net_a,
                            ta.clearance_class,
                            terminal_clearance_kind(tb),
                            net_b,
                            tb.clearance_class,
                        );
                        if !circles_within_radius_nm(circle_a, circle_b, req) {
                            continue;
                        }
                        let ta = &terminals[idx_a];
                        let tb = &terminals[idx_b];
                        if !terminal_shapes_on_layer(ta, layer).any(|sa| {
                            terminal_shapes_on_layer(tb, layer)
                                .any(|sb| terminal_shapes_within_extra_nm(sa, sb, req))
                        }) {
                            continue;
                        }
                        let k = pair_key(uid(ItemKind::Terminal, idx_a), uid(ItemKind::Terminal, idx_b));
                        if emitted_pairs.contains(&k) {
                            continue;
                        }
                        let kind = if circles_within_radius_nm(circle_a, circle_b, Nm::zero())
                            && terminal_shapes_on_layer(ta, layer).any(|sa| {
                                terminal_shapes_on_layer(tb, layer)
                                    .any(|sb| terminal_shapes_within_extra_nm(sa, sb, Nm::zero()))
                            })
                        {
                            DrcViolationKind::Short
                        } else {
                            DrcViolationKind::Clearance
                        };
                        out.push(DrcViolation {
                            kind,
                            a: ItemRef { kind: ItemKind::Terminal, index: idx_a },
                            b: ItemRef { kind: ItemKind::Terminal, index: idx_b },
                        });
                        emitted_pairs.insert(k);
                    }
                    _ => {}
                }
            }
        }
    }

    out
}
