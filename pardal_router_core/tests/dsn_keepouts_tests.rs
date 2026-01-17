use std::path::PathBuf;

use pardal_router_core::dsn::{extract_model_from_str, KeepoutShapeDef};

fn ee_root() -> PathBuf {
    // pardal-pcb/pardal_router_core/tests -> pardal-pcb -> ee root
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|p| p.parent())
        .expect("expected pardal-pcb/pardal_router_core structure")
        .to_path_buf()
}

#[test]
fn image_keepout_is_transformed_by_placement() {
    let dsn = r#"
(pcb demo
  (resolution um 10)
  (unit um)
  (structure (layer F.Cu) (layer B.Cu) (boundary (rect pcb 0 0 100 100)))
  (library (image FP (keepout "" (circle F.Cu 10 10 0))))
  (placement (component FP (place U1 50 50 front 90)))
)
"#;
    let m = extract_model_from_str(dsn).expect("extract model");
    assert_eq!(m.keepouts.len(), 1);
    match &m.keepouts[0] {
        KeepoutShapeDef::Circle { layer, diameter, x, y, .. } => {
            assert_eq!(layer, "F.Cu");
            assert!((*diameter - 10.0).abs() < 1e-9);
            // (10,0) rotated 90deg => (0,10), then translated to (50,60)
            assert!((*x - 50.0).abs() < 1e-9);
            assert!((*y - 60.0).abs() < 1e-9);
        }
        _ => panic!("expected circle keepout"),
    }
}

#[test]
fn structure_keepout_polygon_fixture_is_parsed() {
    let dsn = std::fs::read_to_string(ee_root().join("freerouting/tests/Issue209-split05.dsn"))
        .expect("read Issue209-split05.dsn");
    let m = extract_model_from_str(&dsn).expect("extract model");
    assert!(
        m.keepouts.iter().any(|k| matches!(k, KeepoutShapeDef::Polygon { .. })),
        "expected at least one polygon keepout"
    );
}
