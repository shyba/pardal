use pardal_router_core::drc_nm::{drc_check_areas_var_clearance_indexed, AreaNm, DrcViolationKind, TrackNm, ViaNm};
use pardal_router_core::geom_nm::{Nm, PointNm, SegmentNm};

#[test]
fn area_drc_flags_short_on_overlap() {
    let areas = vec![AreaNm {
        net_id: 2,
        clearance_class: 0,
        layer: 0,
        polygon: vec![PointNm::new(0, 0), PointNm::new(10, 0), PointNm::new(10, 10), PointNm::new(0, 10)],
        holes: Vec::new(),
    }];

    let tracks = vec![TrackNm {
        net_id: 1,
        clearance_class: 0,
        layer: 0,
        seg: SegmentNm {
            a: PointNm::new(-5, 5),
            b: PointNm::new(15, 5),
        },
        r: Nm(1),
    }];

    let vias: Vec<ViaNm> = Vec::new();
    let terminals = Vec::new();

    let v = drc_check_areas_var_clearance_indexed(
        &tracks,
        &vias,
        &terminals,
        &areas,
        |_, _, _, _, _, _| Nm(0),
        Nm(0),
    );
    assert_eq!(v.len(), 1);
    assert_eq!(v[0].kind, DrcViolationKind::Short);
}

#[test]
fn area_drc_flags_clearance_when_close_but_not_overlapping() {
    let areas = vec![AreaNm {
        net_id: 2,
        clearance_class: 0,
        layer: 0,
        polygon: vec![PointNm::new(0, 0), PointNm::new(10, 0), PointNm::new(10, 10), PointNm::new(0, 10)],
        holes: Vec::new(),
    }];

    let tracks = vec![TrackNm {
        net_id: 1,
        clearance_class: 0,
        layer: 0,
        seg: SegmentNm {
            a: PointNm::new(-5, 12),
            b: PointNm::new(15, 12),
        },
        r: Nm(1),
    }];

    let vias: Vec<ViaNm> = Vec::new();
    let terminals = Vec::new();

    let v = drc_check_areas_var_clearance_indexed(
        &tracks,
        &vias,
        &terminals,
        &areas,
        |_, _, _, _, _, _| Nm(2),
        Nm(2),
    );
    assert_eq!(v.len(), 1);
    assert_eq!(v[0].kind, DrcViolationKind::Clearance);
}

#[test]
fn area_drc_ignores_same_net() {
    let areas = vec![AreaNm {
        net_id: 1,
        clearance_class: 0,
        layer: 0,
        polygon: vec![PointNm::new(0, 0), PointNm::new(10, 0), PointNm::new(10, 10), PointNm::new(0, 10)],
        holes: Vec::new(),
    }];

    let tracks = vec![TrackNm {
        net_id: 1,
        clearance_class: 0,
        layer: 0,
        seg: SegmentNm {
            a: PointNm::new(-5, 5),
            b: PointNm::new(15, 5),
        },
        r: Nm(1),
    }];

    let vias: Vec<ViaNm> = Vec::new();
    let terminals = Vec::new();

    let v = drc_check_areas_var_clearance_indexed(
        &tracks,
        &vias,
        &terminals,
        &areas,
        |_, _, _, _, _, _| Nm(0),
        Nm(0),
    );
    assert!(v.is_empty());
}

#[test]
fn area_drc_hole_allows_copper_inside_window() {
    let areas = vec![AreaNm {
        net_id: 2,
        clearance_class: 0,
        layer: 0,
        polygon: vec![PointNm::new(0, 0), PointNm::new(10, 0), PointNm::new(10, 10), PointNm::new(0, 10)],
        holes: vec![vec![
            PointNm::new(2, 2),
            PointNm::new(8, 2),
            PointNm::new(8, 8),
            PointNm::new(2, 8),
        ]],
    }];

    let tracks = vec![TrackNm {
        net_id: 1,
        clearance_class: 0,
        layer: 0,
        seg: SegmentNm {
            a: PointNm::new(4, 5),
            b: PointNm::new(6, 5),
        },
        r: Nm(1),
    }];

    let vias: Vec<ViaNm> = Vec::new();
    let terminals = Vec::new();

    let v = drc_check_areas_var_clearance_indexed(
        &tracks,
        &vias,
        &terminals,
        &areas,
        |_, _, _, _, _, _| Nm(0),
        Nm(0),
    );
    assert!(v.is_empty());
}
