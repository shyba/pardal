use std::collections::HashMap;

use pardal_router_core::dsn::{extract_model_from_str, extract_wiring_from_str, summarize_dsn};
use pardal_router_core::dsn_to_nm::dsn_to_board_nm;
use pardal_router_core::ses::write_ses_minimal;

#[test]
fn ses_writer_scales_nm_to_integer_session_coords() {
    let dsn = r#"
(pcb demo
  (resolution mm 10)
  (structure (layer F.Cu) (layer B.Cu) (boundary (rect pcb 0 0 20 20)))
  (padstack via0 (shape (circle F.Cu 2)) (shape (circle B.Cu 2)))
  (network (net N1 (pins)))
  (wiring
    (wire (path F.Cu 1.0  0 0  10 0) (net N1))
    (via via0 10 0 (net N1))
  )
)
"#;
    let summary = summarize_dsn(dsn).expect("summarize");
    let model = extract_model_from_str(dsn).expect("model");
    let wiring = extract_wiring_from_str(dsn).expect("wiring");
    let board = dsn_to_board_nm(&summary, &model, &wiring).expect("board");

    let mut id_to_name: HashMap<u32, String> = HashMap::new();
    for (name, id) in &board.net_name_to_id {
        id_to_name.insert(*id, name.clone());
    }

    let ses = write_ses_minimal(
        "demo.ses",
        "demo.dsn",
        &summary,
        &model,
        &board.tracks,
        &board.vias,
        &id_to_name,
    );

    assert!(ses.contains("(session demo.ses"));
    assert!(ses.contains("(base_design demo.dsn)"));
    assert!(ses.contains("(net N1"));

    // With (resolution mm 10):
    // - 10mm becomes 100 in session integer coords.
    assert!(
        ses.contains("(wire (path F.Cu 10 0 0 100 0))"),
        "expected scaled integer coords in SES, got:\n{ses}"
    );
    assert!(
        ses.contains("(via via0 100 0)"),
        "expected via in SES, got:\n{ses}"
    );
}

#[test]
fn ses_writer_emits_non_circle_padstack_shapes_in_library_out() {
    let dsn = r#"
(pcb demo
  (resolution mm 10)
  (structure (layer F.Cu) (layer B.Cu) (boundary (rect pcb 0 0 20 20)))
  (padstack via_poly
    (shape (polygon F.Cu 0  0 0  1 0  1 1  0 1))
    (shape (circle B.Cu 2))
  )
  (network (net N1 (pins)))
  (wiring
    (via via_poly 10 0 (net N1))
  )
)
"#;
    let summary = summarize_dsn(dsn).expect("summarize");
    let model = extract_model_from_str(dsn).expect("model");
    let wiring = extract_wiring_from_str(dsn).expect("wiring");
    let board = dsn_to_board_nm(&summary, &model, &wiring).expect("board");

    let mut id_to_name: HashMap<u32, String> = HashMap::new();
    for (name, id) in &board.net_name_to_id {
        id_to_name.insert(*id, name.clone());
    }

    let ses = write_ses_minimal(
        "demo.ses",
        "demo.dsn",
        &summary,
        &model,
        &board.tracks,
        &board.vias,
        &id_to_name,
    );

    // With (resolution mm 10), 1mm -> 10 in session integer coords.
    assert!(
        ses.contains("(padstack via_poly"),
        "expected padstack in library_out, got:\n{ses}"
    );
    assert!(
        ses.contains("(shape (polygon F.Cu 0 0 0 10 0 10 10 0 10))"),
        "expected polygon pad shape in library_out, got:\n{ses}"
    );
    assert!(
        ses.contains("(shape (circle B.Cu 20 0 0))"),
        "expected circle pad shape in library_out, got:\n{ses}"
    );
}
