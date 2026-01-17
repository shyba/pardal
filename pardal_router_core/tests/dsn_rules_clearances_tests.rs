use std::path::PathBuf;

use pardal_router_core::dsn::extract_rules_clearances_from_str;

fn ee_root() -> PathBuf {
    // pardal-pcb/pardal_router_core/tests -> pardal-pcb -> ee root
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|p| p.parent())
        .expect("expected pardal-pcb/pardal_router_core structure")
        .to_path_buf()
}

#[test]
fn parse_issue442_rules_extracts_typed_and_matrix_clearances() {
    let rules_text =
        std::fs::read_to_string(ee_root().join("freerouting/tests/Issue442-clearance_type_tests.rules"))
            .expect("read Issue442-clearance_type_tests.rules");
    let r = extract_rules_clearances_from_str(&rules_text).expect("extract rules clearances");

    assert!(r.default_clearance.is_some());
    assert!(r.typed.contains_key("smd_smd"));
    assert!(r.typed.contains_key("smd_to_turn_gap"));

    let key = ("1A EXTERNAL 1oz".to_string(), "default".to_string());
    assert!(r.matrix.contains_key(&key));

    let smd_key = ("smd".to_string(), "smd".to_string());
    assert!(r.matrix.contains_key(&smd_key));
}

