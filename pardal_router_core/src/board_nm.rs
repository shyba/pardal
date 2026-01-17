use std::collections::HashMap;

use crate::drc_nm::{AreaNm, KeepoutNm, TerminalNm, TrackNm, ViaNm};
use crate::geom_nm::PointNm;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BoundaryNm {
    /// Outer board outline as a closed polygon in nm coordinates.
    ///
    /// The polygon may or may not repeat the first point at the end.
    pub outer: Vec<PointNm>,
    /// Cutouts inside the board outline, represented as closed polygons in nm coordinates.
    ///
    /// Each polygon may or may not repeat the first point at the end.
    pub holes: Vec<Vec<PointNm>>,
}

impl BoundaryNm {
    pub fn new(outer: Vec<PointNm>) -> Option<Self> {
        let outer = normalize_polygon(outer)?;
        Some(Self {
            outer,
            holes: Vec::new(),
        })
    }

    pub fn with_holes(mut self, holes: Vec<Vec<PointNm>>) -> Self {
        self.holes = holes
            .into_iter()
            .filter_map(|p| normalize_polygon(p))
            .collect();
        self
    }

    /// Build a boundary from multiple polygons.
    ///
    /// The largest polygon by absolute area is treated as the outer outline.
    /// Remaining polygons fully contained within the outer outline are treated as holes/cutouts.
    pub fn from_polygons(polygons: Vec<Vec<PointNm>>) -> Option<Self> {
        let mut polys: Vec<Vec<PointNm>> = polygons
            .into_iter()
            .filter_map(|p| normalize_polygon(p))
            .collect();
        if polys.is_empty() {
            return None;
        }

        let mut best_i = 0usize;
        let mut best_area = polygon_area_abs_i128(&polys[0]);
        for (i, p) in polys.iter().enumerate().skip(1) {
            let a = polygon_area_abs_i128(p);
            if a > best_area {
                best_area = a;
                best_i = i;
            }
        }

        let outer = polys.swap_remove(best_i);
        let outer_bbox = polygon_bbox(&outer);
        let outer_area = polygon_area_abs_i128(&outer).max(1);

        // Drop polygons that are effectively duplicates of the outer boundary (common rect+path case).
        polys.retain(|p| {
            let bb = polygon_bbox(p);
            if bb != outer_bbox {
                return true;
            }
            let a = polygon_area_abs_i128(p);
            let diff = (a - outer_area).abs();
            // 0.01% relative tolerance.
            diff > (outer_area / 10_000)
        });

        let mut holes: Vec<Vec<PointNm>> = Vec::new();
        for p in polys {
            if point_in_polygon_or_on_edge_nm(p[0], &outer) {
                holes.push(p);
            }
        }

        Some(Self { outer, holes })
    }
}

fn normalize_polygon(mut points: Vec<PointNm>) -> Option<Vec<PointNm>> {
    if points.len() < 3 {
        return None;
    }
    points.dedup();
    if points.len() >= 2 && points.first().copied() == points.last().copied() {
        points.pop();
    }
    (points.len() >= 3).then_some(points)
}

fn polygon_bbox(points: &[PointNm]) -> (i64, i64, i64, i64) {
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
    (min_x, min_y, max_x, max_y)
}

fn polygon_area_abs_i128(points: &[PointNm]) -> i128 {
    if points.len() < 3 {
        return 0;
    }
    let mut s: i128 = 0;
    for i in 0..points.len() {
        let a = points[i];
        let b = points[(i + 1) % points.len()];
        s += (a.x.0 as i128) * (b.y.0 as i128) - (b.x.0 as i128) * (a.y.0 as i128);
    }
    (s / 2).abs()
}

fn point_on_segment_nm(p: PointNm, a: PointNm, b: PointNm) -> bool {
    let ax = a.x.0 as i128;
    let ay = a.y.0 as i128;
    let bx = b.x.0 as i128;
    let by = b.y.0 as i128;
    let px = p.x.0 as i128;
    let py = p.y.0 as i128;

    let cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax);
    if cross != 0 {
        return false;
    }
    let min_x = ax.min(bx);
    let max_x = ax.max(bx);
    let min_y = ay.min(by);
    let max_y = ay.max(by);
    px >= min_x && px <= max_x && py >= min_y && py <= max_y
}

fn point_in_polygon_or_on_edge_nm(p: PointNm, poly: &[PointNm]) -> bool {
    if poly.len() < 3 {
        return false;
    }
    for i in 0..poly.len() {
        let a = poly[i];
        let b = poly[(i + 1) % poly.len()];
        if point_on_segment_nm(p, a, b) {
            return true;
        }
    }

    // Even/odd rule ray casting (f64 is fine here; this is only used for boundary classification).
    let px = p.x.0 as f64;
    let py = p.y.0 as f64;
    let mut inside = false;
    let mut j = poly.len() - 1;
    for i in 0..poly.len() {
        let xi = poly[i].x.0 as f64;
        let yi = poly[i].y.0 as f64;
        let xj = poly[j].x.0 as f64;
        let yj = poly[j].y.0 as f64;

        let intersects = (yi > py) != (yj > py)
            && px < (xj - xi) * (py - yi) / (yj - yi + 0.0) + xi;
        if intersects {
            inside = !inside;
        }
        j = i;
    }
    inside
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BoardNm {
    pub layers: usize,
    pub net_name_to_id: HashMap<String, u32>,
    /// Board outline as a closed polygon in nm coordinates (if available).
    ///
    /// The polygon may or may not repeat the first point at the end.
    pub boundary: Option<BoundaryNm>,
    /// Maps clearance class ids to names. Id 0 is always `"default"`.
    pub clearance_class_id_to_name: Vec<String>,
    pub tracks: Vec<TrackNm>,
    pub vias: Vec<ViaNm>,
    pub terminals: Vec<TerminalNm>,
    pub areas: Vec<AreaNm>,
    pub keepouts: Vec<KeepoutNm>,
}

impl BoardNm {
    pub fn new(layers: usize) -> Self {
        Self {
            layers: layers.max(1),
            net_name_to_id: HashMap::new(),
            boundary: None,
            clearance_class_id_to_name: vec!["default".to_string()],
            tracks: Vec::new(),
            vias: Vec::new(),
            terminals: Vec::new(),
            areas: Vec::new(),
            keepouts: Vec::new(),
        }
    }

    pub fn net_id(&self, name: &str) -> Option<u32> {
        self.net_name_to_id.get(name).copied()
    }
}
