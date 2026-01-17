use pardal_router_core::drc_nm::{drc_check_basic_with_terminals, DrcViolationKind};
use pardal_router_core::dsn::{extract_model_from_str, extract_wiring_from_str, summarize_dsn};
use pardal_router_core::dsn_to_nm::dsn_to_board_nm;
use pardal_router_core::geom_nm::Nm;
use pardal_router_core::board_nm::BoundaryNm;
use pardal_router_core::geom_nm::PointNm;

#[test]
fn dsn_to_board_nm_builds_tracks_vias_terminals() {
    let dsn = r#"
(pcb demo
  (resolution mm 1)
  (structure (layer F.Cu) (layer B.Cu) (boundary (rect pcb 0 0 20 20)))
  (library (image U (pin ppad 1 0 0) (pin ppad 2 10 0)))
  (placement (component U (place U1 0 0 front 0)))
  (padstack ppad (shape (circle F.Cu 2)) (shape (circle B.Cu 2)))
  (network (net N1 (pins U1-1 U1-2)))
  (wiring (wire (path F.Cu 1.0  0 0  10 0) (net N1)))
)
"#;
    let summary = summarize_dsn(dsn).expect("summarize");
    let model = extract_model_from_str(dsn).expect("model");
    let wiring = extract_wiring_from_str(dsn).expect("wiring");
    let board = dsn_to_board_nm(&summary, &model, &wiring).expect("board");

    assert_eq!(board.layers, 2);
    assert!(board.net_id("N1").is_some());
    assert_eq!(board.tracks.len(), 1);
    assert_eq!(board.vias.len(), 0);
    assert_eq!(board.terminals.len(), 2);

    let v = drc_check_basic_with_terminals(&board.tracks, &board.vias, &board.terminals, Nm(0));
    assert!(v.is_empty(), "same-net wire/pads should not violate DRC");
}

#[test]
fn board_drc_finds_crossing_short_between_two_nets() {
    let dsn = r#"
(pcb demo
  (resolution mm 1)
  (structure (layer F.Cu) (layer B.Cu) (boundary (rect pcb 0 0 20 20)))
  (library (image U (pin ppad 1 0 0) (pin ppad 2 10 0)))
  (placement (component U (place U1 0 0 front 0)))
  (padstack ppad (shape (circle F.Cu 2)) (shape (circle B.Cu 2)))
  (network
    (net N1 (pins U1-1 U1-2))
    (net N2 (pins))
  )
  (wiring
    (wire (path F.Cu 1.0  0 0  10 0) (net N1))
    (wire (path F.Cu 1.0  5 -5  5 5) (net N2))
  )
)
"#;
    let summary = summarize_dsn(dsn).expect("summarize");
    let model = extract_model_from_str(dsn).expect("model");
    let wiring = extract_wiring_from_str(dsn).expect("wiring");
    let board = dsn_to_board_nm(&summary, &model, &wiring).expect("board");

    let v = drc_check_basic_with_terminals(&board.tracks, &board.vias, &board.terminals, Nm(0));
    assert_eq!(v.len(), 1);
    assert_eq!(v[0].kind, DrcViolationKind::Short);
}

#[test]
fn boundary_nm_from_polygons_selects_outer_and_holes() {
    let outer = vec![
        PointNm::new(0, 0),
        PointNm::new(100, 0),
        PointNm::new(100, 100),
        PointNm::new(0, 100),
    ];
    let hole = vec![
        PointNm::new(30, 30),
        PointNm::new(70, 30),
        PointNm::new(70, 70),
        PointNm::new(30, 70),
    ];
    let b = BoundaryNm::from_polygons(vec![hole.clone(), outer.clone()]).expect("boundary");
    assert_eq!(b.outer, outer);
    assert_eq!(b.holes.len(), 1);
    assert_eq!(b.holes[0], hole);
}
