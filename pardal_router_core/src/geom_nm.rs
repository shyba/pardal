#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Nm(pub i64);

impl Nm {
    pub const fn zero() -> Self {
        Nm(0)
    }

    pub const fn abs(self) -> Self {
        Nm(self.0.abs())
    }

    pub const fn as_i64(self) -> i64 {
        self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct PointNm {
    pub x: Nm,
    pub y: Nm,
}

impl PointNm {
    pub const fn new(x: i64, y: i64) -> Self {
        Self { x: Nm(x), y: Nm(y) }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct CircleNm {
    pub center: PointNm,
    pub r: Nm,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct SegmentNm {
    pub a: PointNm,
    pub b: PointNm,
}

fn sq_i128(v: i64) -> i128 {
    let v = v as i128;
    v * v
}

pub fn dist2_point_point_nm(a: PointNm, b: PointNm) -> i128 {
    sq_i128(a.x.0 - b.x.0) + sq_i128(a.y.0 - b.y.0)
}

pub fn dist2_circle_circle_nm(a: CircleNm, b: CircleNm) -> i128 {
    dist2_point_point_nm(a.center, b.center)
}

/// Returns the squared distance between a point and a line segment as a rational number.
///
/// Output is `(numerator, denominator)` representing `numerator / denominator` in `nm^2`.
/// - If the closest point is an endpoint, denominator is `1`.
/// - Otherwise, denominator is `|ab|^2` (in `nm^2`).
pub fn dist2_point_segment_nm_rational(p: PointNm, s: SegmentNm) -> (i128, i128) {
    let ax = s.a.x.0;
    let ay = s.a.y.0;
    let bx = s.b.x.0;
    let by = s.b.y.0;
    let px = p.x.0;
    let py = p.y.0;

    let abx = bx - ax;
    let aby = by - ay;
    let apx = px - ax;
    let apy = py - ay;

    let ab_len2 = sq_i128(abx) + sq_i128(aby); // nm^2
    if ab_len2 == 0 {
        return (sq_i128(apx) + sq_i128(apy), 1);
    }

    let dot = (apx as i128) * (abx as i128) + (apy as i128) * (aby as i128); // nm^2
    if dot <= 0 {
        return (sq_i128(apx) + sq_i128(apy), 1);
    }
    if dot >= ab_len2 {
        let bpx = px - bx;
        let bpy = py - by;
        return (sq_i128(bpx) + sq_i128(bpy), 1);
    }

    // dist^2 = |ap|^2 - dot^2/|ab|^2
    // => dist^2 = (|ap|^2*|ab|^2 - dot^2) / |ab|^2
    let ap_len2 = sq_i128(apx) + sq_i128(apy);
    let numer = ap_len2 * ab_len2 - dot * dot;
    (numer, ab_len2)
}

/// Returns true if the point is within `r` (inclusive) of the segment.
pub fn point_within_segment_radius_nm(p: PointNm, s: SegmentNm, r: Nm) -> bool {
    let (numer, denom) = dist2_point_segment_nm_rational(p, s);
    let r2 = sq_i128(r.0);
    numer <= r2 * denom
}

