use std::collections::HashMap;

use pardal_router_core::dsn::{extract_model_from_str, summarize_dsn};
use pardal_router_core::dsn_to_ir::GridTransform;
use pardal_router_core::export_ses::grid_path_to_nm_tracks_and_vias;
use pardal_router_core::router::Point3;
use pardal_router_core::ses::write_ses_minimal;

#[test]
fn grid_path_exports_tracks_and_vias_to_ses() {
    let dsn = r#"
(pcb demo
  (resolution mm 10)
  (structure
    (layer F.Cu)
    (layer B.Cu)
    (boundary (rect pcb 0 0 20 20))
  )
  (padstack via0
    (shape (circle F.Cu 2 0 0))
    (shape (circle B.Cu 2 0 0))
  )
  (network (net N1 (pins)))
)
"#;
    let summary = summarize_dsn(dsn).expect("summarize");
    let model = extract_model_from_str(dsn).expect("model");

    let tx = GridTransform {
        origin_x: 0.0,
        origin_y: 0.0,
        pitch: 1.0,
    };

    let path = vec![
        Point3 { layer: 0, x: 0, y: 0 },
        Point3 { layer: 0, x: 1, y: 0 },
        Point3 { layer: 1, x: 1, y: 0 },
        Point3 { layer: 1, x: 2, y: 0 },
    ];

    let (tracks, vias) = grid_path_to_nm_tracks_and_vias(
        &summary,
        &model,
        tx,
        &path,
        1,
        0,
        1.0,
        Some("via0"),
    )
    .expect("export");

    assert_eq!(tracks.len(), 2);
    assert_eq!(vias.len(), 1);

    let mut id_to_name: HashMap<u32, String> = HashMap::new();
    id_to_name.insert(1, "N1".to_string());

    let ses = write_ses_minimal(
        "demo.ses",
        "demo.dsn",
        &summary,
        &model,
        &tracks,
        &vias,
        &id_to_name,
    );

    assert!(ses.contains("(net N1"));
    assert!(ses.contains("(via via0"), "expected via in SES, got:\n{ses}");
    assert!(ses.contains("(wire (path"), "expected wire in SES, got:\n{ses}");
}

