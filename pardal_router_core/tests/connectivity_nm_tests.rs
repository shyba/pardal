use pardal_router_core::connectivity_nm::{
    nets_with_disconnected_terminals, nets_with_disconnected_terminals_with_areas,
    terminal_component_count_for_net, terminal_component_count_for_net_with_areas,
};
use pardal_router_core::drc_nm::{AreaNm, TerminalNm, TerminalShapeNm, TrackNm, ViaNm};
use pardal_router_core::geom_nm::{CircleNm, Nm, PointNm, SegmentNm};

#[test]
fn connectivity_single_track_connects_two_terminals() {
    let net_id = 1;
    let tracks = vec![TrackNm {
        net_id,
        clearance_class: 0,
        layer: 0,
        seg: SegmentNm {
            a: PointNm::new(0, 0),
            b: PointNm::new(10, 0),
        },
        r: Nm(1),
    }];
    let vias: Vec<ViaNm> = Vec::new();
    let t0_circle = CircleNm {
        center: PointNm::new(0, 0),
        r: Nm(2),
    };
    let t1_circle = CircleNm {
        center: PointNm::new(10, 0),
        r: Nm(2),
    };
    let terminals = vec![
        TerminalNm {
            net_id,
            pin_ref: None,
            clearance_class: 0,
            layers: vec![0],
            circle: t0_circle,
            shapes: vec![TerminalShapeNm::Circle { layer: 0, circle: t0_circle }],
        },
        TerminalNm {
            net_id,
            pin_ref: None,
            clearance_class: 0,
            layers: vec![0],
            circle: t1_circle,
            shapes: vec![TerminalShapeNm::Circle { layer: 0, circle: t1_circle }],
        },
    ];

    assert_eq!(
        terminal_component_count_for_net(net_id, &tracks, &vias, &terminals, 2),
        1
    );
    assert!(nets_with_disconnected_terminals(&tracks, &vias, &terminals, 2).is_empty());
}

#[test]
fn connectivity_detects_disconnected_terminals_without_join() {
    let net_id = 7;
    let tracks: Vec<TrackNm> = Vec::new();
    let vias: Vec<ViaNm> = Vec::new();
    let t0_circle = CircleNm {
        center: PointNm::new(0, 0),
        r: Nm(2),
    };
    let t1_circle = CircleNm {
        center: PointNm::new(10, 0),
        r: Nm(2),
    };
    let terminals = vec![
        TerminalNm {
            net_id,
            pin_ref: None,
            clearance_class: 0,
            layers: vec![0],
            circle: t0_circle,
            shapes: vec![TerminalShapeNm::Circle { layer: 0, circle: t0_circle }],
        },
        TerminalNm {
            net_id,
            pin_ref: None,
            clearance_class: 0,
            layers: vec![0],
            circle: t1_circle,
            shapes: vec![TerminalShapeNm::Circle { layer: 0, circle: t1_circle }],
        },
    ];

    assert_eq!(
        terminal_component_count_for_net(net_id, &tracks, &vias, &terminals, 2),
        2
    );
    assert_eq!(
        nets_with_disconnected_terminals(&tracks, &vias, &terminals, 2),
        vec![net_id]
    );
}

#[test]
fn connectivity_plane_area_connects_terminals() {
    let net_id = 9;
    let tracks: Vec<TrackNm> = Vec::new();
    let vias: Vec<ViaNm> = Vec::new();
    let t0_circle = CircleNm {
        center: PointNm::new(1, 1),
        r: Nm(2),
    };
    let t1_circle = CircleNm {
        center: PointNm::new(9, 9),
        r: Nm(2),
    };
    let terminals = vec![
        TerminalNm {
            net_id,
            pin_ref: None,
            clearance_class: 0,
            layers: vec![0],
            circle: t0_circle,
            shapes: vec![TerminalShapeNm::Circle { layer: 0, circle: t0_circle }],
        },
        TerminalNm {
            net_id,
            pin_ref: None,
            clearance_class: 0,
            layers: vec![0],
            circle: t1_circle,
            shapes: vec![TerminalShapeNm::Circle { layer: 0, circle: t1_circle }],
        },
    ];
    let areas = vec![AreaNm {
        net_id,
        clearance_class: 0,
        layer: 0,
        polygon: vec![
            PointNm::new(0, 0),
            PointNm::new(10, 0),
            PointNm::new(10, 10),
            PointNm::new(0, 10),
        ],
        holes: Vec::new(),
    }];

    assert_eq!(
        terminal_component_count_for_net(net_id, &tracks, &vias, &terminals, 1),
        2
    );
    assert_eq!(
        terminal_component_count_for_net_with_areas(net_id, &tracks, &vias, &terminals, &areas, 1),
        1
    );
    assert_eq!(
        nets_with_disconnected_terminals_with_areas(&tracks, &vias, &terminals, &areas, 1),
        Vec::<u32>::new()
    );
}

#[test]
fn connectivity_plane_window_does_not_connect_terminals_inside_hole() {
    let net_id = 10;
    let tracks: Vec<TrackNm> = Vec::new();
    let vias: Vec<ViaNm> = Vec::new();
    let t0_circle = CircleNm {
        center: PointNm::new(5, 5),
        r: Nm(1),
    };
    let t1_circle = CircleNm {
        center: PointNm::new(6, 6),
        r: Nm(1),
    };
    let terminals = vec![
        TerminalNm {
            net_id,
            pin_ref: None,
            clearance_class: 0,
            layers: vec![0],
            circle: t0_circle,
            shapes: vec![TerminalShapeNm::Circle { layer: 0, circle: t0_circle }],
        },
        TerminalNm {
            net_id,
            pin_ref: None,
            clearance_class: 0,
            layers: vec![0],
            circle: t1_circle,
            shapes: vec![TerminalShapeNm::Circle { layer: 0, circle: t1_circle }],
        },
    ];
    let areas = vec![AreaNm {
        net_id,
        clearance_class: 0,
        layer: 0,
        polygon: vec![
            PointNm::new(0, 0),
            PointNm::new(10, 0),
            PointNm::new(10, 10),
            PointNm::new(0, 10),
        ],
        holes: vec![vec![
            PointNm::new(2, 2),
            PointNm::new(8, 2),
            PointNm::new(8, 8),
            PointNm::new(2, 8),
        ]],
    }];

    // The terminals are inside the window, so the plane copper should not bridge them.
    assert_eq!(
        terminal_component_count_for_net_with_areas(net_id, &tracks, &vias, &terminals, &areas, 1),
        2
    );
    assert_eq!(
        nets_with_disconnected_terminals_with_areas(&tracks, &vias, &terminals, &areas, 1),
        vec![net_id]
    );
}
