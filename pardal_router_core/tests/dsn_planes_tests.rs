use pardal_router_core::dsn::{extract_model_from_str, PlaneShapeDef};
use pardal_router_core::dsn::{extract_net_rules_from_str, extract_wiring_from_str, summarize_dsn};
use pardal_router_core::dsn_to_nm::dsn_to_board_nm_with_net_rules;

#[test]
fn plane_polygon_is_parsed() {
    let dsn = r#"
(pcb demo
  (resolution um 10)
  (unit um)
  (structure
    (layer F.Cu (type signal))
    (boundary (rect pcb 0 0 100 100))
    (plane GND (polygon F.Cu 0  0 0  10 0  10 10  0 10))
  )
)
"#;
    let m = extract_model_from_str(dsn).expect("extract model");
    assert_eq!(m.planes.len(), 1);
    assert_eq!(m.planes[0].net, "GND");
    assert_eq!(m.planes[0].shapes.len(), 1);
    match &m.planes[0].shapes[0] {
        PlaneShapeDef::Polygon { layer, points } => {
            assert_eq!(layer, "F.Cu");
            assert_eq!(points.len(), 4);
        }
    }
}

#[test]
fn plane_polygon_is_converted_to_nm_area() {
    let dsn = r#"
(pcb demo
  (resolution um 10)
  (unit um)
  (structure
    (layer F.Cu (type signal))
    (boundary (rect pcb 0 0 100 100))
    (plane GND (polygon F.Cu 0  0 0  10 0  10 10  0 10))
    (rule (width 1) (clearance 1))
  )
  (network (net GND (pins)))
  (wiring)
)
"#;
    let summary = summarize_dsn(dsn).expect("summary");
    let model = extract_model_from_str(dsn).expect("model");
    let wiring = extract_wiring_from_str(dsn).expect("wiring");
    let rules = extract_net_rules_from_str(dsn).expect("rules");
    let board = dsn_to_board_nm_with_net_rules(&summary, &model, &wiring, Some(&rules)).expect("board");
    assert_eq!(board.areas.len(), 1);
    assert_eq!(board.areas[0].layer, 0);
}

#[test]
fn plane_window_is_converted_to_nm_hole() {
    let dsn = r#"
(pcb demo
  (resolution um 10)
  (unit um)
  (structure
    (layer F.Cu (type signal))
    (boundary (rect pcb 0 0 100 100))
    (plane GND
      (polygon F.Cu 0  0 0  10 0  10 10  0 10)
      (window (polygon F.Cu 0  3 3  7 3  7 7  3 7))
    )
    (rule (width 1) (clearance 1))
  )
  (network (net GND (pins)))
  (wiring)
)
"#;
    let summary = summarize_dsn(dsn).expect("summary");
    let model = extract_model_from_str(dsn).expect("model");
    let wiring = extract_wiring_from_str(dsn).expect("wiring");
    let rules = extract_net_rules_from_str(dsn).expect("rules");
    let board = dsn_to_board_nm_with_net_rules(&summary, &model, &wiring, Some(&rules)).expect("board");
    assert_eq!(board.areas.len(), 1);
    assert_eq!(board.areas[0].holes.len(), 1);
    assert_eq!(board.areas[0].holes[0].len(), 4);
}
