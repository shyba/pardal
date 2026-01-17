use pardal_router_core::board_nm::BoundaryNm;
use pardal_router_core::drc_nm::{drc_check_boundary_nm, DrcViolationKind, ItemKind, KeepoutNm, TrackNm, ViaNm};
use pardal_router_core::geom_nm::{CircleNm, Nm, PointNm, SegmentNm};

#[test]
fn boundary_drc_flags_copper_near_or_outside_outline() {
    let boundary = BoundaryNm::new(vec![
        PointNm::new(0, 0),
        PointNm::new(100, 0),
        PointNm::new(100, 100),
        PointNm::new(0, 100),
    ])
    .expect("boundary");

    let ok_track = TrackNm {
        net_id: 1,
        clearance_class: 0,
        layer: 0,
        seg: SegmentNm {
            a: PointNm::new(10, 10),
            b: PointNm::new(90, 10),
        },
        r: Nm(1),
    };

    let near_edge_track = TrackNm {
        net_id: 1,
        clearance_class: 0,
        layer: 0,
        seg: SegmentNm {
            a: PointNm::new(10, 2),
            b: PointNm::new(90, 2),
        },
        r: Nm(3),
    };

    let outside_via = ViaNm {
        net_id: 2,
        clearance_class: 0,
        layers: (0, 0),
        padstack: None,
        circle: CircleNm {
            center: PointNm::new(120, 50),
            r: Nm(2),
        },
        shapes: Vec::new(),
    };

    let keepouts: Vec<KeepoutNm> = Vec::new();

    let v0 = drc_check_boundary_nm(&[ok_track.clone()], &[], &[], &keepouts, &boundary, Nm(0));
    assert!(v0.is_empty());

    let v1 = drc_check_boundary_nm(&[near_edge_track], &[], &[], &keepouts, &boundary, Nm(0));
    assert_eq!(v1.len(), 1);
    assert_eq!(v1[0].kind, DrcViolationKind::Boundary);
    assert_eq!(v1[0].a.kind, ItemKind::Track);
    assert_eq!(v1[0].b.kind, ItemKind::Boundary);

    let v2 = drc_check_boundary_nm(&[ok_track], &[outside_via], &[], &keepouts, &boundary, Nm(0));
    assert_eq!(v2.len(), 1);
    assert_eq!(v2[0].kind, DrcViolationKind::Boundary);
    assert_eq!(v2[0].a.kind, ItemKind::Via);
    assert_eq!(v2[0].b.kind, ItemKind::Boundary);
}

#[test]
fn boundary_drc_flags_copper_inside_cutout_hole() {
    let boundary = BoundaryNm::new(vec![
        PointNm::new(0, 0),
        PointNm::new(100, 0),
        PointNm::new(100, 100),
        PointNm::new(0, 100),
    ])
    .expect("boundary")
    .with_holes(vec![vec![
        PointNm::new(30, 30),
        PointNm::new(70, 30),
        PointNm::new(70, 70),
        PointNm::new(30, 70),
    ]]);

    let ok_track = TrackNm {
        net_id: 1,
        clearance_class: 0,
        layer: 0,
        seg: SegmentNm {
            a: PointNm::new(10, 10),
            b: PointNm::new(90, 10),
        },
        r: Nm(1),
    };

    let inside_hole_track = TrackNm {
        net_id: 1,
        clearance_class: 0,
        layer: 0,
        seg: SegmentNm {
            a: PointNm::new(40, 50),
            b: PointNm::new(60, 50),
        },
        r: Nm(1),
    };

    let near_hole_edge_track = TrackNm {
        net_id: 1,
        clearance_class: 0,
        layer: 0,
        seg: SegmentNm {
            a: PointNm::new(20, 28),
            b: PointNm::new(80, 28),
        },
        r: Nm(1),
    };

    let keepouts: Vec<KeepoutNm> = Vec::new();

    let v0 = drc_check_boundary_nm(&[ok_track], &[], &[], &keepouts, &boundary, Nm(0));
    assert!(v0.is_empty());

    let v1 = drc_check_boundary_nm(&[inside_hole_track], &[], &[], &keepouts, &boundary, Nm(0));
    assert_eq!(v1.len(), 1);
    assert_eq!(v1[0].kind, DrcViolationKind::Boundary);
    assert_eq!(v1[0].a.kind, ItemKind::Track);

    let v2 = drc_check_boundary_nm(&[near_hole_edge_track], &[], &[], &keepouts, &boundary, Nm(2));
    assert_eq!(v2.len(), 1);
    assert_eq!(v2[0].kind, DrcViolationKind::Boundary);
    assert_eq!(v2[0].a.kind, ItemKind::Track);
}
