use std::collections::HashMap;

use crate::geom_nm::{CircleNm, Nm, PointNm, SegmentNm};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AabbNm {
    pub min_x: i64,
    pub min_y: i64,
    pub max_x: i64,
    pub max_y: i64,
}

impl AabbNm {
    pub fn inflate(self, r: Nm) -> Self {
        let d = r.0;
        Self {
            min_x: self.min_x.saturating_sub(d),
            min_y: self.min_y.saturating_sub(d),
            max_x: self.max_x.saturating_add(d),
            max_y: self.max_y.saturating_add(d),
        }
    }

    pub fn overlaps(&self, other: &AabbNm) -> bool {
        !(self.max_x < other.min_x
            || other.max_x < self.min_x
            || self.max_y < other.min_y
            || other.max_y < self.min_y)
    }
}

pub fn aabb_point_nm(p: PointNm) -> AabbNm {
    AabbNm {
        min_x: p.x.0,
        min_y: p.y.0,
        max_x: p.x.0,
        max_y: p.y.0,
    }
}

pub fn aabb_circle_nm(c: CircleNm) -> AabbNm {
    let r = c.r.0;
    AabbNm {
        min_x: c.center.x.0.saturating_sub(r),
        min_y: c.center.y.0.saturating_sub(r),
        max_x: c.center.x.0.saturating_add(r),
        max_y: c.center.y.0.saturating_add(r),
    }
}

pub fn aabb_segment_nm(s: SegmentNm) -> AabbNm {
    let min_x = s.a.x.0.min(s.b.x.0);
    let max_x = s.a.x.0.max(s.b.x.0);
    let min_y = s.a.y.0.min(s.b.y.0);
    let max_y = s.a.y.0.max(s.b.y.0);
    AabbNm {
        min_x,
        min_y,
        max_x,
        max_y,
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
struct Key {
    layer: usize,
    cx: i64,
    cy: i64,
}

#[derive(Debug)]
pub struct SpatialHashNm {
    cell: i64,
    buckets: HashMap<Key, Vec<usize>>,
}

impl SpatialHashNm {
    pub fn new(cell: i64) -> Self {
        Self {
            cell: cell.max(1),
            buckets: HashMap::new(),
        }
    }

    fn cell_of(&self, v: i64) -> i64 {
        // floor division for negatives.
        if v >= 0 {
            v / self.cell
        } else {
            -((-v + self.cell - 1) / self.cell)
        }
    }

    pub fn insert_aabb(&mut self, layer: usize, aabb: AabbNm, idx: usize) {
        let x0 = self.cell_of(aabb.min_x);
        let x1 = self.cell_of(aabb.max_x);
        let y0 = self.cell_of(aabb.min_y);
        let y1 = self.cell_of(aabb.max_y);

        for cx in x0..=x1 {
            for cy in y0..=y1 {
                self.buckets.entry(Key { layer, cx, cy }).or_default().push(idx);
            }
        }
    }

    pub fn query_aabb(&self, layer: usize, aabb: AabbNm, out: &mut Vec<usize>) {
        out.clear();
        let x0 = self.cell_of(aabb.min_x);
        let x1 = self.cell_of(aabb.max_x);
        let y0 = self.cell_of(aabb.min_y);
        let y1 = self.cell_of(aabb.max_y);

        for cx in x0..=x1 {
            for cy in y0..=y1 {
                if let Some(v) = self.buckets.get(&Key { layer, cx, cy }) {
                    out.extend_from_slice(v);
                }
            }
        }
    }
}

