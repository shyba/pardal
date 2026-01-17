use std::path::PathBuf;

use pardal_router_core::dsn::{extract_model_from_str, extract_wiring_from_str, summarize_dsn};
use pardal_router_core::dsn_to_ir::build_net_name_to_id_sorted;
use pardal_router_core::dsn_to_nm::dsn_to_board_nm;
use pardal_router_core::dsn_to_nm::wiring_to_nm_tracks_and_vias;
use pardal_router_core::geom_nm::Nm;

fn ee_root() -> PathBuf {
    // pardal-pcb/pardal_router_core/tests -> pardal-pcb -> ee root
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|p| p.parent())
        .expect("expected pardal-pcb/pardal_router_core structure")
        .to_path_buf()
}

#[test]
fn dsn_wiring_converts_to_nm_tracks_and_vias() {
    let dsn = r#"
(pcb demo
  (resolution mm 1)
  (structure
    (layer F.Cu)
    (layer B.Cu)
    (boundary (polygon signal 0  0 0  20 0  20 20  0 20  0 0))
  )
  (padstack via0
    (shape (circle F.Cu 2))
    (shape (circle B.Cu 2))
  )
  (network (net N1 (pins)))
  (wiring
    (wire (path 1 1.0  0 0  10 0) (net N1))
    (via via0 5 0 (net N1))
  )
)
"#;
    let summary = summarize_dsn(dsn).expect("summarize");
    let model = extract_model_from_str(dsn).expect("model");
    let wiring = extract_wiring_from_str(dsn).expect("wiring");
    let net_map = build_net_name_to_id_sorted(&model);

    let (tracks, vias) = wiring_to_nm_tracks_and_vias(&summary, &model, &wiring, &net_map).expect("convert");
    assert_eq!(tracks.len(), 1);
    assert_eq!(vias.len(), 1);

    let t = &tracks[0];
    assert_eq!(t.layer, 0);
    assert_eq!(t.r, Nm(500_000)); // 0.5mm
    assert_eq!(t.seg.a.x, Nm(0));
    assert_eq!(t.seg.b.x, Nm(10_000_000)); // 10mm

    let v = &vias[0];
    assert_eq!(v.layers, (0, 1));
    assert_eq!(v.circle.r, Nm(1_000_000)); // 1mm
    assert_eq!(v.circle.center.x, Nm(5_000_000));
}

#[test]
fn issue270_pin_refs_with_concatenated_dash_resolve_to_terminals() {
    let dsn = std::fs::read_to_string(ee_root().join("freerouting/tests/Issue270-non-ansi_bracket.dsn"))
        .expect("read Issue270 DSN");
    let summary = summarize_dsn(&dsn).expect("summarize");
    let model = extract_model_from_str(&dsn).expect("model");
    let wiring = extract_wiring_from_str(&dsn).expect("wiring");

    // Regression: FreeRouting can emit `"J3"-"D+"` which tokenizes as `"J3" "-" "D+"`, but the
    // pin reference should be treated as a single `J3-D+` key.
    let dplus = model.nets.get("D+").expect("D+ net");
    assert!(dplus.pins.contains(&"J3-D+".to_string()));
    assert!(model.pins.contains_key("J3-D+"));

    let board = dsn_to_board_nm(&summary, &model, &wiring).expect("dsn_to_board_nm");
    let net_id = *board.net_name_to_id.get("D+").expect("D+ net id");
    let term_count = board.terminals.iter().filter(|t| t.net_id == net_id).count();
    assert_eq!(term_count, 2);
}
