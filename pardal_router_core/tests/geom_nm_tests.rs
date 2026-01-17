use pardal_router_core::geom_nm::{
    dist2_point_point_nm, dist2_point_segment_nm_rational, point_within_segment_radius_nm, Nm, PointNm, SegmentNm,
};

#[test]
fn point_point_dist2_is_symmetric() {
    let a = PointNm::new(0, 0);
    let b = PointNm::new(3, 4);
    assert_eq!(dist2_point_point_nm(a, b), 25);
    assert_eq!(dist2_point_point_nm(b, a), 25);
}

#[test]
fn point_segment_dist2_hits_endpoints() {
    let seg = SegmentNm {
        a: PointNm::new(0, 0),
        b: PointNm::new(10, 0),
    };
    let p = PointNm::new(-5, 0);
    let (n, d) = dist2_point_segment_nm_rational(p, seg);
    assert_eq!((n, d), (25, 1));
}

#[test]
fn point_segment_dist2_hits_projection() {
    let seg = SegmentNm {
        a: PointNm::new(0, 0),
        b: PointNm::new(10, 0),
    };
    let p = PointNm::new(5, 3);
    let (n, d) = dist2_point_segment_nm_rational(p, seg);
    // exact: 9
    assert_eq!(n, 9 * d);
}

#[test]
fn within_radius_uses_rational_comparison() {
    let seg = SegmentNm {
        a: PointNm::new(0, 0),
        b: PointNm::new(10, 0),
    };
    let p = PointNm::new(5, 3);
    assert!(point_within_segment_radius_nm(p, seg, Nm(3)));
    assert!(!point_within_segment_radius_nm(p, seg, Nm(2)));
}

