use std::path::PathBuf;

use pardal_router_core::dsn::summarize_dsn;
use pardal_router_core::dsn::extract_boundary_polygon_from_str;
use pardal_router_core::dsn::extract_model_from_str;
use pardal_router_core::dsn::PadShapeDef;

fn ee_root() -> PathBuf {
    // pardal-pcb/pardal_router_core/tests -> pardal-pcb -> ee root
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|p| p.parent())
        .expect("expected pardal-pcb/pardal_router_core structure")
        .to_path_buf()
}

#[test]
fn parse_empty_board_dsn_summary() {
    let dsn = std::fs::read_to_string(ee_root().join("freerouting/tests/empty_board.dsn"))
        .expect("read empty_board.dsn");
    let s = summarize_dsn(&dsn).expect("summarize");

    assert_eq!(s.pcb_name, "freerouting-empty.dsn");
    assert_eq!(s.unit.as_deref(), Some("um"));
    assert_eq!(s.resolution_unit.as_deref(), Some("um"));
    assert_eq!(s.resolution_value, Some(10));
    assert_eq!(s.layer_count, 2);
    let bbox = s.boundary_bbox.expect("boundary bbox");
    assert_eq!(bbox.min_x, 129540.0);
    assert_eq!(bbox.max_x, 186690.0);
    assert_eq!(bbox.min_y, -107950.0);
    assert_eq!(bbox.max_y, -57150.0);
}

#[test]
fn parse_issue313_fasttest_has_two_layers() {
    let dsn = std::fs::read_to_string(ee_root().join("freerouting/tests/Issue313-FastTest.dsn"))
        .expect("read Issue313-FastTest.dsn");
    let s = summarize_dsn(&dsn).expect("summarize");
    assert!(s.layer_count >= 2);
    assert!(s.net_count > 0);
    assert_eq!(s.component_count, 1);
    assert_eq!(s.pin_count, 108);
}

#[test]
fn parse_unicode_filename_fixture_smoke() {
    // Cyrillic filename fixture; ensures UTF-8 paths and tokenization don't panic.
    let path = ee_root().join("freerouting/tests/Issue110-Паяльная станция.dsn");
    let dsn = std::fs::read_to_string(path).expect("read unicode DSN");
    let s = summarize_dsn(&dsn).expect("summarize");
    assert!(s.layer_count >= 1);
}

#[test]
fn parse_issue026_net_count_matches_fixture() {
    let dsn = std::fs::read_to_string(ee_root().join("freerouting/tests/Issue026-J2_reference.dsn"))
        .expect("read Issue026-J2_reference.dsn");
    let s = summarize_dsn(&dsn).expect("summarize");
    assert_eq!(s.net_count, 24);
}

#[test]
fn extract_issue313_vcc_pins_and_pin_coords() {
    let dsn = std::fs::read_to_string(ee_root().join("freerouting/tests/Issue313-FastTest.dsn"))
        .expect("read Issue313-FastTest.dsn");
    let m = extract_model_from_str(&dsn).expect("extract");

    let vcc = m.nets.get("VCC").expect("VCC net");
    assert_eq!(vcc.pins.len(), 6);
    assert!(m.pins.contains_key("u1-2406"));

    let p = &m.pins["u1-2406"];
    assert!((p.x - 57.5).abs() < 1e-9);
    assert!((p.y - (-9.0)).abs() < 1e-9);

    // Padstack radii (simple approximations)
    let r = m.padstacks.get("p2391").copied().expect("p2391 radius");
    assert!((r - (7.0866 / 2.0)).abs() < 1e-9);
    let r = m.padstacks.get("p17076").copied().expect("p17076 radius");
    // The polygon reaches (±3.4599, ±2.5512), so the bounding radius is the hypotenuse.
    assert!((r - (3.4599_f64.hypot(2.5512))).abs() < 1e-9);

    // Padstack layer presence (1-based in DSN -> 0-based in model).
    let layers = m.padstack_layers.get("p2391").expect("p2391 layers");
    assert_eq!(layers, &vec![0, 1]);
    let layers = m.padstack_layers.get("p17076").expect("p17076 layers");
    assert_eq!(layers, &vec![0]);
}

#[test]
fn extract_issue313_boundary_polygon_points() {
    let dsn = std::fs::read_to_string(ee_root().join("freerouting/tests/Issue313-FastTest.dsn"))
        .expect("read Issue313-FastTest.dsn");
    let pts = extract_boundary_polygon_from_str(&dsn).expect("extract boundary");
    assert_eq!(pts.len(), 6);
    assert_eq!(pts[0], pts[5]);

    // Fixture-specific sanity checks: first vertex matches the expected outline.
    assert!((pts[0].0 - 0.0).abs() < 1e-9);
    assert!((pts[0].1 - (-196.5)).abs() < 1e-9);
}

#[test]
fn boundary_rect_and_polygon_are_supported() {
    let dsn = r#"
(pcb demo
  (resolution um 10)
  (unit um)
  (structure
    (layer a)
    (layer b)
    (boundary (rect pcb 0 0 10 5))
    (boundary (polygon signal 0 0 0  10 0  10 5  0 5  0 0))
  )
)
"#;
    let s = summarize_dsn(dsn).expect("summarize");
    assert_eq!(s.layer_count, 2);
    let bbox = s.boundary_bbox.expect("bbox");
    assert_eq!(bbox.min_x, 0.0);
    assert_eq!(bbox.min_y, 0.0);
    assert_eq!(bbox.max_x, 10.0);
    assert_eq!(bbox.max_y, 5.0);

    let pts = extract_boundary_polygon_from_str(dsn).expect("boundary polygon");
    assert!(pts.len() >= 4);
}

#[test]
fn placement_applies_image_pin_transform() {
    // Image pin is at (10,0). With a 90-degree rotation, it should end up at (0,10) relative.
    let dsn = r#"
(pcb demo
  (resolution um 10)
  (unit um)
  (structure (layer a) (boundary (rect pcb 0 0 100 100)))
  (library (image "FP" (pin p1 1 10 0)))
  (placement (component "FP" (place U1 50 50 front 90)))
  (network (net N1 (pins U1-1)))
  (padstack p1 (shape(circle 1 10 0 0)))
)
"#;
    let m = extract_model_from_str(dsn).expect("extract");
    let p = m.pins.get("U1-1").expect("U1-1");
    assert!((p.x - 50.0).abs() < 1e-9);
    assert!((p.y - 60.0).abs() < 1e-9);
    assert!(p.shapes.iter().any(|s| matches!(
        s,
        PadShapeDef::Circle { layer, diameter, x, y }
            if layer == "1" && (*diameter - 10.0).abs() < 1e-9 && (*x - 50.0).abs() < 1e-9 && (*y - 60.0).abs() < 1e-9
    )));
}

#[test]
fn padstack_layers_support_named_layers() {
    let dsn = r#"
(pcb demo
  (resolution um 10)
  (unit um)
  (structure (layer F.Cu) (layer B.Cu) (boundary (rect pcb 0 0 100 100)))
  (library (image U1 (pin p1 1 0 0)))
  (padstack p1
    (shape (circle F.Cu 10))
    (shape (circle B.Cu 10))
  )
  (network (net N1 (pins U1-1)))
)
"#;
    let m = extract_model_from_str(dsn).expect("extract");
    let layers = m.padstack_layers.get("p1").expect("p1 layers");
    assert_eq!(layers, &vec![0, 1]);
}

#[test]
fn placement_back_side_mirrors_geometry_and_layers() {
    let dsn = r#"
(pcb demo
  (resolution um 10)
  (unit um)
  (structure (layer F.Cu) (layer B.Cu) (boundary (rect pcb 0 0 100 100)))
  (library (image "FP" (pin p1 1 0 0)))
  (padstack p1 (shape (circle F.Cu 10 10 0)))
  (placement (component "FP" (place U1 0 0 back 0)))
  (network (net N1 (pins U1-1)))
)
"#;
    let m = extract_model_from_str(dsn).expect("extract");
    let p = m.pins.get("U1-1").expect("U1-1");
    assert!((p.x - 0.0).abs() < 1e-9);
    assert!((p.y - 0.0).abs() < 1e-9);

    assert!(p.shapes.iter().any(|s| matches!(
        s,
        PadShapeDef::Circle { layer, diameter, x, y }
            if layer == "B.Cu" && (*diameter - 10.0).abs() < 1e-9 && (*x - (-10.0)).abs() < 1e-9 && (*y - 0.0).abs() < 1e-9
    )));
}

#[test]
fn placement_pin_clearance_class_is_recorded() {
    let dsn = r#"
(pcb demo
  (resolution um 10)
  (unit um)
  (structure (layer F.Cu) (layer B.Cu) (boundary (rect pcb 0 0 100 100)))
  (library (image "FP" (pin p1 1 0 0)))
  (padstack p1 (shape (circle F.Cu 10)))
  (placement (component "FP"
    (place U1 0 0 front 0
      (pin 1 (clearance_class "kicad_default"))
    )
  ))
  (network (net N1 (pins U1-1)))
)
"#;
    let m = extract_model_from_str(dsn).expect("extract");
    assert_eq!(
        m.pin_clearance_classes.get("U1-1").map(|s| s.as_str()),
        Some("kicad_default")
    );
}
