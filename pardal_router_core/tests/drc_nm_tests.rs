use pardal_router_core::drc_nm::{
    drc_check_basic, drc_check_keepouts_indexed, drc_check_var_clearance, drc_check_var_clearance_indexed,
    DrcViolationKind, KeepoutAppliesTo, KeepoutNm, KeepoutShapeNm, TerminalNm, TrackNm, ViaNm,
};
use pardal_router_core::geom_nm::{CircleNm, Nm, PointNm, SegmentNm};

#[test]
fn drc_detects_track_track_short() {
    let tracks = vec![
        TrackNm {
            net_id: 1,
            clearance_class: 0,
            layer: 0,
            seg: SegmentNm {
                a: PointNm::new(-10, 0),
                b: PointNm::new(10, 0),
            },
            r: Nm(1),
        },
        TrackNm {
            net_id: 2,
            clearance_class: 0,
            layer: 0,
            seg: SegmentNm {
                a: PointNm::new(0, -10),
                b: PointNm::new(0, 10),
            },
            r: Nm(1),
        },
    ];
    let vias: Vec<ViaNm> = Vec::new();
    let v = drc_check_basic(&tracks, &vias, Nm(2));
    assert_eq!(v.len(), 1);
    assert_eq!(v[0].kind, DrcViolationKind::Short);
}

#[test]
fn drc_detects_track_track_clearance_not_short() {
    let tracks = vec![
        TrackNm {
            net_id: 1,
            clearance_class: 0,
            layer: 0,
            seg: SegmentNm {
                a: PointNm::new(0, 0),
                b: PointNm::new(10, 0),
            },
            r: Nm(1),
        },
        TrackNm {
            net_id: 2,
            clearance_class: 0,
            layer: 0,
            seg: SegmentNm {
                a: PointNm::new(0, 5),
                b: PointNm::new(10, 5),
            },
            r: Nm(1),
        },
    ];
    let vias: Vec<ViaNm> = Vec::new();
    let v = drc_check_basic(&tracks, &vias, Nm(4));
    assert_eq!(v.len(), 1);
    assert_eq!(v[0].kind, DrcViolationKind::Clearance);
}

#[test]
fn drc_detects_via_track_short_on_spanned_layer() {
    let tracks = vec![TrackNm {
        net_id: 1,
        clearance_class: 0,
        layer: 0,
        seg: SegmentNm {
            a: PointNm::new(-10, 0),
            b: PointNm::new(10, 0),
        },
        r: Nm(1),
    }];
    let vias = vec![ViaNm {
        net_id: 2,
        clearance_class: 0,
        layers: (0, 1),
        padstack: None,
        circle: CircleNm {
            center: PointNm::new(0, 0),
            r: Nm(2),
        },
        shapes: Vec::new(),
    }];
    let v = drc_check_basic(&tracks, &vias, Nm(1));
    assert_eq!(v.len(), 1);
    assert_eq!(v[0].kind, DrcViolationKind::Short);
}

#[test]
fn drc_ignores_same_net_overlap() {
    let tracks = vec![
        TrackNm {
            net_id: 1,
            clearance_class: 0,
            layer: 0,
            seg: SegmentNm {
                a: PointNm::new(0, 0),
                b: PointNm::new(10, 0),
            },
            r: Nm(1),
        },
        TrackNm {
            net_id: 1,
            clearance_class: 0,
            layer: 0,
            seg: SegmentNm {
                a: PointNm::new(5, 0),
                b: PointNm::new(15, 0),
            },
            r: Nm(1),
        },
    ];
    let vias: Vec<ViaNm> = Vec::new();
    let v = drc_check_basic(&tracks, &vias, Nm(100));
    assert!(v.is_empty());
}

#[test]
fn drc_var_clearance_changes_classification() {
    let tracks = vec![
        TrackNm {
            net_id: 1,
            clearance_class: 0,
            layer: 0,
            seg: SegmentNm {
                a: PointNm::new(0, 0),
                b: PointNm::new(10, 0),
            },
            r: Nm(1),
        },
        TrackNm {
            net_id: 2,
            clearance_class: 0,
            layer: 0,
            seg: SegmentNm {
                a: PointNm::new(0, 5),
                b: PointNm::new(10, 5),
            },
            r: Nm(1),
        },
    ];
    let vias: Vec<ViaNm> = Vec::new();
    let terminals: Vec<TerminalNm> = Vec::new();

    let none = drc_check_var_clearance(&tracks, &vias, &terminals, |_, _, _, _, _, _| Nm(0));
    assert!(none.is_empty());

    let some = drc_check_var_clearance(&tracks, &vias, &terminals, |_, _, _, _, _, _| Nm(4));
    assert_eq!(some.len(), 1);
    assert_eq!(some[0].kind, DrcViolationKind::Clearance);
}

#[test]
fn drc_indexed_matches_unindexed_for_simple_case() {
    let tracks = vec![
        TrackNm {
            net_id: 1,
            clearance_class: 0,
            layer: 0,
            seg: SegmentNm {
                a: PointNm::new(0, 0),
                b: PointNm::new(10, 0),
            },
            r: Nm(1),
        },
        TrackNm {
            net_id: 2,
            clearance_class: 0,
            layer: 0,
            seg: SegmentNm {
                a: PointNm::new(0, 5),
                b: PointNm::new(10, 5),
            },
            r: Nm(1),
        },
    ];
    let vias = vec![ViaNm {
        net_id: 3,
        clearance_class: 0,
        layers: (0, 1),
        padstack: None,
        circle: CircleNm {
            center: PointNm::new(5, 2),
            r: Nm(1),
        },
        shapes: Vec::new(),
    }];
    let terminals: Vec<TerminalNm> = Vec::new();

    let un = drc_check_var_clearance(&tracks, &vias, &terminals, |_, _, _, _, _, _| Nm(2));
    let ix = drc_check_var_clearance_indexed(
        &tracks,
        &vias,
        &terminals,
        |_, _, _, _, _, _| Nm(2),
        Nm(2),
    );
    assert_eq!(un, ix);
}

#[test]
fn drc_keepout_circle_flags_track_overlap() {
    let tracks = vec![TrackNm {
        net_id: 1,
        clearance_class: 0,
        layer: 0,
        seg: SegmentNm {
            a: PointNm::new(-10, 0),
            b: PointNm::new(10, 0),
        },
        r: Nm(1),
    }];
    let vias: Vec<ViaNm> = Vec::new();
    let terminals: Vec<TerminalNm> = Vec::new();
    let keepouts = vec![KeepoutNm {
        layers: vec![0],
        applies_to: KeepoutAppliesTo::All,
        shape: KeepoutShapeNm::Circle {
            circle: CircleNm {
                center: PointNm::new(0, 0),
                r: Nm(2),
            },
        },
    }];

    let v = drc_check_keepouts_indexed(&tracks, &vias, &terminals, &keepouts);
    assert_eq!(v.len(), 1);
    assert_eq!(v[0].kind, DrcViolationKind::Keepout);
}

#[test]
fn drc_keepout_polygon_flags_via_inside() {
    let tracks: Vec<TrackNm> = Vec::new();
    let vias = vec![ViaNm {
        net_id: 1,
        clearance_class: 0,
        layers: (0, 0),
        padstack: None,
        circle: CircleNm {
            center: PointNm::new(5, 5),
            r: Nm(1),
        },
        shapes: Vec::new(),
    }];
    let terminals: Vec<TerminalNm> = Vec::new();
    let keepouts = vec![KeepoutNm {
        layers: vec![0],
        applies_to: KeepoutAppliesTo::All,
        shape: KeepoutShapeNm::Polygon {
            points: vec![
                PointNm::new(0, 0),
                PointNm::new(10, 0),
                PointNm::new(10, 10),
                PointNm::new(0, 10),
            ],
        },
    }];

    let v = drc_check_keepouts_indexed(&tracks, &vias, &terminals, &keepouts);
    assert_eq!(v.len(), 1);
    assert_eq!(v[0].kind, DrcViolationKind::Keepout);
}

#[test]
fn drc_keepout_path_flags_track_overlap() {
    let tracks = vec![TrackNm {
        net_id: 1,
        clearance_class: 0,
        layer: 0,
        seg: SegmentNm {
            a: PointNm::new(-10, 3),
            b: PointNm::new(10, 3),
        },
        r: Nm(1),
    }];
    let vias: Vec<ViaNm> = Vec::new();
    let terminals: Vec<TerminalNm> = Vec::new();
    let keepouts = vec![KeepoutNm {
        layers: vec![0],
        applies_to: KeepoutAppliesTo::All,
        shape: KeepoutShapeNm::Path {
            r: Nm(2),
            points: vec![PointNm::new(-10, 0), PointNm::new(10, 0)],
        },
    }];

    let v = drc_check_keepouts_indexed(&tracks, &vias, &terminals, &keepouts);
    assert_eq!(v.len(), 1);
    assert_eq!(v[0].kind, DrcViolationKind::Keepout);
}

#[test]
fn drc_via_keepout_does_not_flag_track() {
    let tracks = vec![TrackNm {
        net_id: 1,
        clearance_class: 0,
        layer: 0,
        seg: SegmentNm {
            a: PointNm::new(-10, 0),
            b: PointNm::new(10, 0),
        },
        r: Nm(1),
    }];
    let vias: Vec<ViaNm> = Vec::new();
    let terminals: Vec<TerminalNm> = Vec::new();
    let keepouts = vec![KeepoutNm {
        layers: vec![0],
        applies_to: KeepoutAppliesTo::Via,
        shape: KeepoutShapeNm::Circle {
            circle: CircleNm {
                center: PointNm::new(0, 0),
                r: Nm(2),
            },
        },
    }];

    let v = drc_check_keepouts_indexed(&tracks, &vias, &terminals, &keepouts);
    assert!(v.is_empty());
}

#[test]
fn drc_wire_keepout_does_not_flag_via() {
    let tracks: Vec<TrackNm> = Vec::new();
    let vias = vec![ViaNm {
        net_id: 1,
        clearance_class: 0,
        layers: (0, 0),
        padstack: None,
        circle: CircleNm {
            center: PointNm::new(5, 5),
            r: Nm(1),
        },
        shapes: Vec::new(),
    }];
    let terminals: Vec<TerminalNm> = Vec::new();
    let keepouts = vec![KeepoutNm {
        layers: vec![0],
        applies_to: KeepoutAppliesTo::Wire,
        shape: KeepoutShapeNm::Polygon {
            points: vec![
                PointNm::new(0, 0),
                PointNm::new(10, 0),
                PointNm::new(10, 10),
                PointNm::new(0, 10),
            ],
        },
    }];

    let v = drc_check_keepouts_indexed(&tracks, &vias, &terminals, &keepouts);
    assert!(v.is_empty());
}

#[test]
fn keepout_indexing_does_not_explode_for_large_coordinate_ranges() {
    // Regression: previously, `drc_check_keepouts_indexed` could take extremely long when there were
    // large keepouts but no (or tiny) copper items, because the spatial hash cell size was too small.
    let tracks: Vec<TrackNm> = Vec::new();
    let vias: Vec<ViaNm> = Vec::new();
    let terminals: Vec<TerminalNm> = Vec::new();
    let keepouts = vec![KeepoutNm {
        layers: vec![0],
        applies_to: KeepoutAppliesTo::All,
        shape: KeepoutShapeNm::Circle {
            circle: CircleNm {
                center: PointNm::new(42_000_000, 10_000_000),
                r: Nm(3_000_000),
            },
        },
    }];

    let v = drc_check_keepouts_indexed(&tracks, &vias, &terminals, &keepouts);
    assert!(v.is_empty());
}
