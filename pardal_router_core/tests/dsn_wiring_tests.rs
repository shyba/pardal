use std::path::PathBuf;

use pardal_router_core::dsn::extract_wiring_from_str;

fn ee_root() -> PathBuf {
    // pardal-pcb/pardal_router_core/tests -> pardal-pcb -> ee root
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|p| p.parent())
        .expect("expected pardal-pcb/pardal_router_core structure")
        .to_path_buf()
}

#[test]
fn extract_issue313_wiring_has_wires_and_vias() {
    let dsn = std::fs::read_to_string(ee_root().join("freerouting/tests/Issue313-FastTest.dsn"))
        .expect("read Issue313-FastTest.dsn");
    let w = extract_wiring_from_str(&dsn).expect("extract wiring");

    assert!(w.wires.len() > 10, "expected many wires");
    assert!(w.vias.len() > 10, "expected many vias");
    assert!(w.wires.iter().any(|x| x.path_kind.eq_ignore_ascii_case("path")));
    assert!(w.wires.iter().any(|x| x.net == "GND"));
    assert!(w.vias.iter().any(|v| v.net == "VCC"));
}

#[test]
fn extract_minimal_polyline_wire_and_via() {
    let dsn = r#"
(pcb demo
  (structure (layer F.Cu) (layer B.Cu))
  (wiring
    (wire
      (polyline_path F.Cu 250.0  0 0  10 0)
      (net "N1" 1)
      (clearance_class "c1")
      (type shove_fixed)
    )
    (via "Via[0-1]" 5 5
      (net N1 1)
      (clearance_class "c1")
      (type protect)
    )
  )
)
"#;
    let w = extract_wiring_from_str(dsn).expect("extract wiring");
    assert_eq!(w.wires.len(), 1);
    assert_eq!(w.vias.len(), 1);

    let wire = &w.wires[0];
    assert_eq!(wire.layer, "F.Cu");
    assert!((wire.width - 250.0).abs() < 1e-9);
    assert_eq!(wire.net, "N1");
    assert_eq!(wire.clearance_class.as_deref(), Some("c1"));
    assert_eq!(wire.wire_type.as_deref(), Some("shove_fixed"));
    assert_eq!(wire.points.first().copied(), Some((0.0, 0.0)));
    assert_eq!(wire.points.last().copied(), Some((10.0, 0.0)));

    let via = &w.vias[0];
    assert_eq!(via.padstack, "Via[0-1]");
    assert_eq!(via.net, "N1");
    assert!((via.x - 5.0).abs() < 1e-9);
    assert!((via.y - 5.0).abs() < 1e-9);
    assert_eq!(via.clearance_class.as_deref(), Some("c1"));
    assert_eq!(via.via_type.as_deref(), Some("protect"));
}

