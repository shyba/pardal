use std::path::PathBuf;

use pardal_router_core::dsn::{
    extract_boundary_polygon_from_str, extract_model_from_str, extract_wiring_from_str, summarize_dsn,
};
use pardal_router_core::router::route_bfs_2d;

use pardal_router_core::dsn_to_ir::{
    apply_boundary_mask_from_world_polygon, build_empty_ir_from_summary,
    build_net_name_to_id_sorted,
    apply_boundary_mask_from_world_polygon_with_holes,
    stamp_pins_as_occ_by_net,
    stamp_keepouts_as_occ_and_via_forbidden,
    stamp_pins_as_keepouts_from_shapes,
    stamp_pins_as_circular_keepouts_by_padstack_layers,
    stamp_wiring_as_occ_by_padstack_layers,
};

fn ee_root() -> PathBuf {
    // pardal-pcb/pardal_router_core/tests -> pardal-pcb -> ee root
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|p| p.parent())
        .expect("expected pardal-pcb/pardal_router_core structure")
        .to_path_buf()
}

#[test]
fn dsn_issue313_boundary_mask_blocks_bbox_corners() {
    let dsn = std::fs::read_to_string(ee_root().join("freerouting/tests/Issue313-FastTest.dsn"))
        .expect("read Issue313-FastTest.dsn");
    let summary = summarize_dsn(&dsn).expect("summarize");
    let boundary = extract_boundary_polygon_from_str(&dsn).expect("boundary poly");

    let pitch = 2.0;
    let (mut ir, tx) = build_empty_ir_from_summary(&summary, pitch).expect("build ir");
    assert!(apply_boundary_mask_from_world_polygon(&mut ir, tx, 0, 1, &boundary));

    // A point clearly inside the outline should be free.
    let inside = tx.world_to_grid(10.0, -10.0).expect("inside point");
    assert!(inside.x < ir.width && inside.y < ir.height);
    assert_eq!(ir.get_occ(0, inside.x, inside.y), 0);

    // A point at the top-right bbox corner is outside the slanted top edge of the outline.
    let outside = tx.world_to_grid(83.6, 0.0).expect("outside point");
    assert!(outside.x < ir.width && outside.y < ir.height);
    assert_eq!(ir.get_occ(0, outside.x, outside.y), 1);
}

#[test]
fn dsn_issue313_can_build_ir_stamp_pins_and_route_between_two_pins() {
    let dsn = std::fs::read_to_string(ee_root().join("freerouting/tests/Issue313-FastTest.dsn"))
        .expect("read Issue313-FastTest.dsn");
    let summary = summarize_dsn(&dsn).expect("summarize");
    let model = extract_model_from_str(&dsn).expect("extract model");

    let vcc = model.nets.get("VCC").expect("VCC net");
    assert!(vcc.pins.len() >= 2);
    let start_ref = vcc.pins[0].as_str();
    let goal_ref = vcc.pins[1].as_str();

    // A coarse grid makes this fixture small enough while still exercising stamping + routing.
    let pitch = 2.0;
    let (mut ir, tx) = build_empty_ir_from_summary(&summary, pitch).expect("build ir");
    assert!(ir.width > 10 && ir.height > 10);

    stamp_pins_as_circular_keepouts_by_padstack_layers(&mut ir, tx, &model, 1, &[start_ref, goal_ref]);

    let sp = tx
        .world_to_grid(model.pins[start_ref].x, model.pins[start_ref].y)
        .expect("start point");
    let gp = tx
        .world_to_grid(model.pins[goal_ref].x, model.pins[goal_ref].y)
        .expect("goal point");
    assert!(sp != gp);
    assert!(sp.x < ir.width && sp.y < ir.height);
    assert!(gp.x < ir.width && gp.y < ir.height);
    assert_ne!(ir.get_occ(0, sp.x, sp.y), 1);
    assert_ne!(ir.get_occ(0, gp.x, gp.y), 1);

    let path = route_bfs_2d(&ir, 0, sp, gp, 1).expect("route path");
    assert_eq!(path.layer, 0);
    assert_eq!(path.points.first().copied(), Some(sp));
    assert_eq!(path.points.last().copied(), Some(gp));
    assert!(path.points.iter().all(|p| ir.get_occ(0, p.x, p.y) != 1));
}

#[test]
fn stamp_wiring_sets_net_occupancy_for_wires_and_vias() {
    let dsn = r#"
(pcb demo
  (resolution um 10)
  (unit um)
  (structure
    (layer F.Cu)
    (layer B.Cu)
    (boundary (polygon signal 0  0 0  100 0  100 100  0 100  0 0))
  )
  (padstack via0
    (shape (circle F.Cu 10))
    (shape (circle B.Cu 10))
  )
  (network (net N1 (pins)))
  (wiring
    (wire (path 1 0.5  10 10  50 10) (net N1))
    (via via0 50 10 (net N1))
  )
)
"#;
    let summary = summarize_dsn(dsn).expect("summarize");
    let boundary = extract_boundary_polygon_from_str(dsn).expect("boundary poly");
    let model = extract_model_from_str(dsn).expect("extract model");
    let wiring = extract_wiring_from_str(dsn).expect("extract wiring");

    let (mut ir, tx) = build_empty_ir_from_summary(&summary, 1.0).expect("build ir");
    assert!(apply_boundary_mask_from_world_polygon(&mut ir, tx, 0, 999, &boundary));
    assert!(apply_boundary_mask_from_world_polygon(&mut ir, tx, 1, 999, &boundary));

    let net_map = build_net_name_to_id_sorted(&model);
    let n1 = *net_map.get("N1").expect("N1 id");
    stamp_wiring_as_occ_by_padstack_layers(&mut ir, tx, &model, &wiring, 999, 0.0, &net_map);

    let p10 = tx.world_to_grid(10.0, 10.0).expect("p10");
    assert_eq!(ir.get_occ(0, p10.x, p10.y), n1, "wire should stamp on layer 1->0");

    let pv = tx.world_to_grid(50.0, 10.0).expect("pv");
    assert_eq!(ir.get_occ(0, pv.x, pv.y), n1, "via should stamp on F.Cu");
    assert_eq!(ir.get_occ(1, pv.x, pv.y), n1, "via should stamp on B.Cu");
}

#[test]
fn build_net_name_to_id_sorted_includes_plane_nets() {
    let dsn = r#"
(pcb demo
  (resolution mm 1)
  (structure
    (layer F.Cu)
    (boundary (polygon signal 0  0 0  10 0  10 10  0 10  0 0))
    (plane GND (polygon F.Cu 0  0 0  10 0  10 10  0 10  0 0))
  )
  (network (net N1 (pins)))
)
"#;
    let model = extract_model_from_str(dsn).expect("extract model");
    assert_eq!(model.planes.len(), 1);
    assert_eq!(model.planes[0].net, "GND");

    let net_map = build_net_name_to_id_sorted(&model);
    assert!(net_map.contains_key("N1"));
    assert!(net_map.contains_key("GND"));
    assert_ne!(net_map["N1"], 0);
    assert_ne!(net_map["GND"], 0);
    assert_ne!(net_map["N1"], net_map["GND"]);
}

#[test]
fn stamp_keepouts_blocks_wires_and_forbids_vias_separately() {
    let dsn = r#"
(pcb demo
  (resolution um 10)
  (unit um)
  (structure
    (layer F.Cu)
    (layer B.Cu)
    (boundary (polygon signal 0  0 0  100 0  100 100  0 100  0 0))
    (wire_keepout "" (circle F.Cu 20 50 50))
    (via_keepout "" (circle F.Cu 20 60 60))
    (keepout "" (circle F.Cu 20 70 70))
  )
  (network (net N1 (pins)))
)
"#;
    let summary = summarize_dsn(dsn).expect("summarize");
    let boundary = extract_boundary_polygon_from_str(dsn).expect("boundary poly");
    let model = extract_model_from_str(dsn).expect("extract model");

    let (mut ir, tx) = build_empty_ir_from_summary(&summary, 1.0).expect("build ir");
    assert!(apply_boundary_mask_from_world_polygon(&mut ir, tx, 0, 999, &boundary));
    assert!(apply_boundary_mask_from_world_polygon(&mut ir, tx, 1, 999, &boundary));

    stamp_keepouts_as_occ_and_via_forbidden(&mut ir, tx, &model, 999);

    let p_wire = tx.world_to_grid(50.0, 50.0).expect("p_wire");
    assert_eq!(ir.get_occ(0, p_wire.x, p_wire.y), 999);
    assert_eq!(ir.get_via_forbidden(0, p_wire.x, p_wire.y), 0);

    let p_via = tx.world_to_grid(60.0, 60.0).expect("p_via");
    assert_eq!(ir.get_occ(0, p_via.x, p_via.y), 0);
    assert_eq!(ir.get_via_forbidden(0, p_via.x, p_via.y), 1);

    let p_all = tx.world_to_grid(70.0, 70.0).expect("p_all");
    assert_eq!(ir.get_occ(0, p_all.x, p_all.y), 999);
    assert_eq!(ir.get_via_forbidden(0, p_all.x, p_all.y), 1);
}

#[test]
fn stamp_keepouts_does_not_overwrite_existing_net_occupancy() {
    let dsn = r#"
(pcb demo
  (resolution um 10)
  (unit um)
  (structure
    (layer F.Cu)
    (boundary (polygon signal 0  0 0  100 0  100 100  0 100  0 0))
    (keepout "" (circle F.Cu 20 50 50))
  )
  (network (net N1 (pins)))
)
"#;
    let summary = summarize_dsn(dsn).expect("summarize");
    let boundary = extract_boundary_polygon_from_str(dsn).expect("boundary poly");
    let model = extract_model_from_str(dsn).expect("extract model");

    let (mut ir, tx) = build_empty_ir_from_summary(&summary, 1.0).expect("build ir");
    assert!(apply_boundary_mask_from_world_polygon(&mut ir, tx, 0, 999, &boundary));

    let p = tx.world_to_grid(50.0, 50.0).expect("p");
    ir.set_occ(0, p.x, p.y, 123);
    stamp_keepouts_as_occ_and_via_forbidden(&mut ir, tx, &model, 999);
    assert_eq!(ir.get_occ(0, p.x, p.y), 123);
}

#[test]
fn stamp_pins_from_shapes_handles_rectangular_pad() {
    let dsn = r#"
(pcb demo
  (resolution um 10)
  (unit um)
  (structure
    (layer F.Cu)
    (boundary (polygon signal 0  0 0  100 0  100 100  0 100  0 0))
  )
  (library (image U (pin ppad 1 0 0)))
  (placement (component U (place U1 50 50 front 0)))
  (padstack ppad (shape (rect F.Cu -10 -5 10 5)))
  (network (net N1 (pins U1-1)))
)
"#;
    let summary = summarize_dsn(dsn).expect("summarize");
    let boundary = extract_boundary_polygon_from_str(dsn).expect("boundary poly");
    let model = extract_model_from_str(dsn).expect("extract model");

    let (mut ir, tx) = build_empty_ir_from_summary(&summary, 1.0).expect("build ir");
    assert!(apply_boundary_mask_from_world_polygon(&mut ir, tx, 0, 999, &boundary));

    stamp_pins_as_keepouts_from_shapes(&mut ir, tx, &model, 999, &[]);

    let p = tx.world_to_grid(50.0, 50.0).expect("p");
    assert_eq!(ir.get_occ(0, p.x, p.y), 999);
}

#[test]
fn stamp_pins_from_shapes_preserves_existing_occupancy() {
    let dsn = r#"
(pcb demo
  (resolution mm 1)
  (structure
    (layer F.Cu)
    (boundary (polygon signal 0  0 0  10 0  10 10  0 10  0 0))
  )
  (library (image U (pin ppad 1 0 0)))
  (placement (component U (place U1 5 5 front 0)))
  (padstack ppad (shape (rect F.Cu -1 -1 1 1)))
  (network (net N1 (pins U1-1)))
  (wiring (wire (path F.Cu 0.2  5 5  9 5) (net N1)))
)
"#;
    let summary = summarize_dsn(dsn).expect("summarize");
    let boundary = extract_boundary_polygon_from_str(dsn).expect("boundary poly");
    let model = extract_model_from_str(dsn).expect("extract model");
    let wiring = extract_wiring_from_str(dsn).expect("extract wiring");

    let (mut ir, tx) = build_empty_ir_from_summary(&summary, 1.0).expect("build ir");
    assert!(apply_boundary_mask_from_world_polygon(&mut ir, tx, 0, 1, &boundary));

    let net_map = build_net_name_to_id_sorted(&model);
    stamp_wiring_as_occ_by_padstack_layers(&mut ir, tx, &model, &wiring, 1, 0.0, &net_map);
    let n1 = net_map["N1"];
    let p = tx.world_to_grid(5.0, 5.0).expect("p");
    assert_eq!(ir.get_occ(0, p.x, p.y), n1);

    // Stamping pins as keepouts should not overwrite the already-stamped wiring occupancy.
    stamp_pins_as_keepouts_from_shapes(&mut ir, tx, &model, 1, &[]);
    assert_eq!(ir.get_occ(0, p.x, p.y), n1);
}

#[test]
fn stamp_pins_as_occ_by_net_sets_pad_cells_to_net_id() {
    let dsn = r#"
(pcb demo
  (resolution um 10)
  (unit um)
  (structure
    (layer F.Cu)
    (boundary (polygon signal 0  0 0  100 0  100 100  0 100  0 0))
  )
  (library
    (image U
      (pin ppad 1 0 0)
      (pin ppad 2 50 0)
    )
  )
  (placement (component U (place U1 10 10 front 0)))
  (padstack ppad (shape (rect F.Cu -10 -5 10 5)))
  (network
    (net N1 (pins U1-1))
    (net N2 (pins U1-2))
  )
)
"#;
    let summary = summarize_dsn(dsn).expect("summarize");
    let boundary = extract_boundary_polygon_from_str(dsn).expect("boundary poly");
    let model = extract_model_from_str(dsn).expect("extract model");
    let net_map = build_net_name_to_id_sorted(&model);

    let (mut ir, tx) = build_empty_ir_from_summary(&summary, 1.0).expect("build ir");
    assert!(apply_boundary_mask_from_world_polygon(&mut ir, tx, 0, 1, &boundary));

    stamp_pins_as_occ_by_net(&mut ir, tx, &model, 1, 0.0, &net_map);

    let n1 = net_map["N1"];
    let n2 = net_map["N2"];
    let p1 = tx.world_to_grid(10.0, 10.0).expect("p1");
    let p2 = tx.world_to_grid(60.0, 10.0).expect("p2");
    assert_eq!(ir.get_pad_owner(0, p1.x, p1.y), n1);
    assert_eq!(ir.get_pad_owner(0, p2.x, p2.y), n2);
}

#[test]
fn boundary_mask_with_holes_blocks_cutouts() {
    let dsn = r#"
(pcb demo
  (resolution mm 1)
  (structure
    (layer F.Cu)
    (boundary (polygon signal 0  0 0  100 0  100 100  0 100  0 0))
  )
)
"#;
    let summary = summarize_dsn(dsn).expect("summarize");
    let outer = extract_boundary_polygon_from_str(dsn).expect("boundary poly");
    let holes = vec![vec![(40.0, 40.0), (60.0, 40.0), (60.0, 60.0), (40.0, 60.0)]];

    let (mut ir, tx) = build_empty_ir_from_summary(&summary, 1.0).expect("build ir");
    assert!(apply_boundary_mask_from_world_polygon_with_holes(&mut ir, tx, 0, 7, &outer, &holes));

    let inside = tx.world_to_grid(10.0, 10.0).expect("inside");
    assert_eq!(ir.get_occ(0, inside.x, inside.y), 0);

    let in_hole = tx.world_to_grid(50.0, 50.0).expect("in_hole");
    assert_eq!(ir.get_occ(0, in_hole.x, in_hole.y), 7);
}
